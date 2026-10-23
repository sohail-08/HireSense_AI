"""Synthetic exercises only: no media, mail, model, browser or candidate data calls."""
from datetime import timedelta
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.work_sample import WorkSampleExercise, WorkSampleAttempt, WorkSampleAssessment, WorkSampleDecision
from app.schemas.work_sample import Task, SaveTask, Action, CandidateReady, SaveSubmission, CorrectnessDecision
from app.services.work_sample import WorkSampleService
from app.services.interview_rooms import RoomConflict, RoomAccessError
from app.services.interview_content import utc
from app.security import create_access_token
from app.routes import work_samples as routes
from app.assessments.workflow import ConsolidatedAssessmentGraph
from app.assessments.reports import render_html
from assessment_fixtures import synthetic_source
from test_interview_rooms import room_setup  # noqa: F401
from test_interviews import setup, records  # noqa: F401

TASK = {"title": "Customer quotation", "instructions": "Calculate a quote for two units using the supplied catalogue.",
    "materials": "Fictional catalogue: Basic costs 100 BDT per unit. No discounts or taxes.",
    "deliverables": "A customer email with the total.", "duration_minutes": 15,
    "tools_policy": "Use the supplied catalogue only. No external AI or assistance.", "response_type": "text"}
ANSWER = "Two Basic units cost 200 BDT.\nNo discount applies."

class Model:
    def __init__(self):
        self.calls = []
    def generate_json(self, **kwargs):
        self.calls.append(kwargs)
        raise AssertionError("No model should grade practical work")

@pytest.fixture
def exercise_setup(room_setup):
    setup, rooms, media, clock, row, token, _ = room_setup
    db, owner = setup[:2]
    model = Model()
    service = WorkSampleService(rooms=rooms, model=model,
        session_factory=lambda: Session(db.get_bind(), expire_on_commit=False))
    state = service.save_task(db, owner.id, row.id, SaveTask(task=Task(**TASK), version=0))
    cookie, _, _ = rooms.exchange(db, token)
    rooms.waiting(db, cookie)
    rooms.admit(db, owner.id, row.id)
    return db, owner, setup[2], row, service, cookie, clock, rooms, model, state

def act(ctx, name, **kwargs):
    db, owner, _, row, service, *_ = ctx
    version = service.read(db, owner.id, row.id)["exercise"]["version"]
    return service.action(db, owner.id, row.id, Action(version=version, action=name, **kwargs))

def start(ctx):
    db, _, _, _, service, cookie, *_ = ctx
    shared = act(ctx, "share")
    service.ready(db, cookie, CandidateReady(attempt_id=shared["exercise"]["attempt"]["id"]))
    return act(ctx, "start")

def submit(ctx):
    state = start(ctx)
    db, _, _, _, service, cookie, *_ = ctx
    return service.save_submission(db, cookie, SaveSubmission(attempt_id=state["exercise"]["attempt"]["id"],
        revision=0, content=ANSWER, submit=True))

def decide(ctx, correct=True, submission_hash=None):
    db, owner, _, row, service, *_ = ctx
    current = service.read(db, owner.id, row.id)
    return service.decide(db, owner.id, row.id, CorrectnessDecision(
        submission_hash=submission_hash or current["exercise"]["attempt"]["submission_hash"], correct=correct, confirmed=True))

def test_private_draft_locks_at_share(exercise_setup):
    db, owner, _, row, service, cookie, *_ = exercise_setup
    assert service.candidate_read(db, cookie)["exercise"] is None
    shared = act(exercise_setup, "share")
    assert shared["exercise"]["approved_at"]
    assert service.candidate_read(db, cookie)["exercise"]["task"] == TASK
    with pytest.raises(RoomConflict):
        service.save_task(db, owner.id, row.id, SaveTask(task=Task(**TASK), version=shared["exercise"]["version"]))

def test_readiness_does_not_start_timer(exercise_setup):
    db, _, _, _, service, cookie, *_ = exercise_setup
    shared = act(exercise_setup, "share")
    assert shared["exercise"]["attempt"]["deadline_at"] is None
    with pytest.raises(RoomConflict): act(exercise_setup, "start")
    ready = service.ready(db, cookie, CandidateReady(attempt_id=shared["exercise"]["attempt"]["id"]))
    assert ready["exercise"]["status"] == "ready"
    assert ready["exercise"]["attempt"]["deadline_at"] is None
    assert act(exercise_setup, "start")["exercise"]["status"] == "running"

def test_autosave_exact_text_and_revision_conflict(exercise_setup):
    state = start(exercise_setup)
    db, owner, _, row, service, cookie, *_ = exercise_setup
    request = SaveSubmission(attempt_id=state["exercise"]["attempt"]["id"], revision=0,
        content="  leading whitespace\n\treturn 1\n")
    saved = service.save_submission(db, cookie, request)
    assert saved["exercise"]["attempt"]["content"] == request.content
    assert saved["exercise"]["attempt"]["revision"] == 1
    assert "explanation" not in saved["exercise"]["attempt"]
    with pytest.raises(RoomConflict, match="another tab"): service.save_submission(db, cookie, request)
    assert service.read(db, owner.id, row.id)["exercise"]["attempt"]["content"] == request.content

def test_pause_resume_and_server_deadline_cannot_extend_budget(exercise_setup):
    state = start(exercise_setup)
    db, _, _, _, service, cookie, clock, *_ = exercise_setup
    clock.value += timedelta(minutes=3)
    paused = act(exercise_setup, "pause", reason="Connection interrupted")
    assert paused["exercise"]["attempt"]["remaining_seconds"] == 720
    clock.value += timedelta(hours=1)
    with pytest.raises(RoomConflict):
        service.save_submission(db, cookie, SaveSubmission(attempt_id=state["exercise"]["attempt"]["id"], revision=0, content="late"))
    resumed = act(exercise_setup, "resume")
    assert utc(resumed["exercise"]["attempt"]["deadline_at"]) == clock.value + timedelta(seconds=720)
    clock.value += timedelta(seconds=720)
    with pytest.raises(RoomConflict):
        service.save_submission(db, cookie, SaveSubmission(attempt_id=state["exercise"]["attempt"]["id"], revision=0, content="too late"))
    db.expire_all()
    assert service.candidate_read(db, cookie)["exercise"]["attempt"]["status"] == "time_ended"

def test_submission_is_idempotent_immutable_and_cannot_be_retried(exercise_setup):
    state = submit(exercise_setup)
    db, _, _, _, service, cookie, *_ = exercise_setup
    attempt = state["exercise"]["attempt"]
    assert attempt["submission_hash"] and attempt["status"] == "submitted"
    repeat = service.save_submission(db, cookie, SaveSubmission(attempt_id=attempt["id"], revision=0, content=ANSWER, submit=True))
    assert repeat["exercise"]["attempt"]["submission_hash"] == attempt["submission_hash"]
    with pytest.raises(RoomConflict):
        service.save_submission(db, cookie, SaveSubmission(attempt_id=attempt["id"], revision=1, content="overwrite", submit=True))
    with pytest.raises(RoomConflict): act(exercise_setup, "share")
    assert len(list(db.scalars(select(WorkSampleAttempt)))) == 1
    assert db.get(WorkSampleAttempt, attempt["id"]).content == ANSWER
    assert "number" not in attempt

def test_end_interview_preserves_unfinished_work(exercise_setup):
    state = start(exercise_setup)
    db, owner, _, row, service, cookie, _, rooms, *_ = exercise_setup
    service.save_submission(db, cookie, SaveSubmission(attempt_id=state["exercise"]["attempt"]["id"], revision=0, content="partial"))
    rooms.end(db, owner.id, row.id)
    result = service.read(db, owner.id, row.id)
    assert result["exercise"]["attempt"]["status"] == "interview_ended"
    assert result["exercise"]["attempt"]["content"] == "partial"
    with pytest.raises(RoomAccessError): service.candidate_read(db, cookie)

@pytest.mark.parametrize("correct,score", [(True, 100), (False, 0)])
def test_correctness_is_manual_final_private_and_traceable(exercise_setup, correct, score):
    submit(exercise_setup)
    db, owner, _, row, service, cookie, _, _, model, _ = exercise_setup
    assert service.report_sources(db, owner.id, row.application_id)[0]["assessment"] is None
    reviewed = decide(exercise_setup, correct)["exercise"]["decision"]
    assert reviewed["correct"] == correct and reviewed["score"] == score
    assert reviewed["approved_by"] == owner.id and reviewed["approved_at"]
    assert reviewed["submission_hash"] == service.read(db, owner.id, row.id)["exercise"]["attempt"]["submission_hash"]
    assert decide(exercise_setup, correct)["exercise"]["decision"] == reviewed
    with pytest.raises(RoomConflict): decide(exercise_setup, not correct)
    candidate = service.candidate_read(db, cookie)["exercise"]
    assert not {"decision", "assessments", "events", "attempts"} & candidate.keys()
    assert service.report_sources(db, owner.id, row.application_id)[0]["assessment"] == reviewed
    assert not model.calls

def test_decision_requires_finished_work_matching_hash_and_confirmation(exercise_setup):
    start(exercise_setup)
    with pytest.raises(RoomConflict): decide(exercise_setup, submission_hash="a" * 64)
    db, _, _, _, service, cookie, *_ = exercise_setup
    current = service.candidate_read(db, cookie)
    service.save_submission(db, cookie, SaveSubmission(attempt_id=current["exercise"]["attempt"]["id"], revision=0, content=ANSWER, submit=True))
    with pytest.raises(RoomConflict): decide(exercise_setup, submission_hash="a" * 64)
    with pytest.raises(ValidationError):
        CorrectnessDecision(submission_hash="a" * 64, correct=True, confirmed=False)
    with pytest.raises(ValidationError):
        CorrectnessDecision(submission_hash="a" * 64, correct="true", confirmed=True)

def test_owner_scope_and_revocation(exercise_setup):
    db, owner, other, row, service, cookie, _, rooms, *_ = exercise_setup
    with pytest.raises((PermissionError, LookupError)): service.read(db, other.id, row.id)
    with pytest.raises(RoomAccessError): service.candidate_read(db, "a" * 43)
    rooms.revoke(db, owner.id, row.id)
    with pytest.raises(RoomAccessError): service.candidate_read(db, cookie)

def test_templates_are_private(exercise_setup):
    db, owner, other, _, service, *_ = exercise_setup
    template = service.template(db, owner.id, Task(**TASK))
    assert service.list_templates(db, owner.id)[0]["id"] == template["id"]
    assert service.list_templates(db, other.id) == []

@pytest.mark.parametrize("duration", [0, 16, 200, 1.5, True])
def test_task_has_strict_fifteen_minute_limit(duration):
    with pytest.raises(ValidationError): Task(**{**TASK, "duration_minutes": duration})

@pytest.mark.parametrize("name", ["retry", "extend", "assess"])
def test_removed_actions_cannot_be_requested(name):
    with pytest.raises(ValidationError): Action(version=1, action=name)
    with pytest.raises(ValidationError): SaveSubmission(attempt_id=1, revision=0, content="work", explanation="removed")

def test_routes_require_auth_origin_and_exclude_old_grading_endpoints(exercise_setup, monkeypatch):
    db, owner, _, row, service, cookie, *_ = exercise_setup
    submit(exercise_setup)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[routes.get_service] = lambda: service
    monkeypatch.setattr("app.routes.interview_rooms.get_settings", lambda: service.rooms.settings)
    with TestClient(app) as client:
        assert client.get("/api/work-samples/templates").status_code == 401
        client.cookies.set("hiresense_candidate_session", cookie, path="/api/interview-rooms/candidate")
        response = client.get("/api/interview-rooms/candidate/work-sample")
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert "decision" not in response.json()["exercise"]
        assert client.post("/api/interview-rooms/candidate/work-sample/ready", json={"attempt_id": 1},
            headers={"Origin": "https://attacker.test"}).status_code == 403
        assert client.get(f"/api/work-samples/interviews/{row.id}").status_code == 401
        headers = {"Authorization": f"Bearer {create_access_token(owner.id)}"}
        assert client.get(f"/api/work-samples/interviews/{row.id}", headers=headers).status_code == 200
        for removed in ("assess", "review", "draft"):
            assert f"/api/work-samples/interviews/{{interview_id}}/{removed}" not in app.openapi()["paths"]

def test_pending_practical_blocks_final_and_report_escapes_response(exercise_setup):
    submit(exercise_setup)
    db, owner, _, row, service, *_ = exercise_setup
    source = synthetic_source()
    source["practical_assessments"] = service.report_sources(db, owner.id, row.application_id)
    source["practical_assessments"][0]["content"] = "<script>untrusted()</script>"
    result = ConsolidatedAssessmentGraph().graph.invoke({"snapshot": source})["result"]
    assert result["score_summary"]["final_score"] is None
    assert result["practical_assessments"][0]["assessment"] is None
    html = render_html({"kind": "individual", "reports": [{"id": 1, "result": result, "created_at": "2026-10-23T00:00:00Z"}]})
    assert "Practical assessment" in html and "&lt;script&gt;" in html
    assert "<script>untrusted()" not in html

def test_delete_cleans_decisions_and_submission(exercise_setup):
    submit(exercise_setup)
    decide(exercise_setup)
    db, _, _, row, service, *_ = exercise_setup
    service.delete_for_interviews(db, [row.id])
    db.commit()
    for model in (WorkSampleExercise, WorkSampleAttempt, WorkSampleAssessment, WorkSampleDecision):
        assert db.scalar(select(model)) is None

def test_legacy_recovery_preserves_historical_approved_results(exercise_setup):
    state = submit(exercise_setup)
    db, owner, _, _, service, *_ = exercise_setup
    legacy = WorkSampleAssessment(attempt_id=state["exercise"]["attempt"]["id"], status="approved",
        snapshot={}, result={"score": 70}, approved_result={"score": 70}, approved_by=owner.id)
    db.add(legacy); db.commit()
    service.recover(db)
    assert legacy.status == "approved" and legacy.approved_result == {"score": 70}
    legacy.status = "processing"; db.commit()
    service.recover(db)
    assert legacy.status == "cancelled" and legacy.approved_result == {"score": 70}

def test_expired_work_is_denied_and_purged_without_model_calls(exercise_setup):
    submit(exercise_setup)
    db, owner, _, row, service, cookie, clock, _, model, state = exercise_setup
    exercise = db.get(WorkSampleExercise, state["exercise"]["id"])
    exercise.expires_at = clock.value - timedelta(seconds=1)
    db.commit()
    with pytest.raises(RoomAccessError): service.candidate_read(db, cookie)
    db.rollback()
    assert service.read(db, owner.id, row.id)["exercise"] is None
    service.tick()
    db.expire_all()
    assert db.scalar(select(WorkSampleExercise)) is None
    assert not model.calls
