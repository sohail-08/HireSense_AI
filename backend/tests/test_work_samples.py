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
from app.schemas.work_sample import Task, SaveTask, Action, CandidateReady, SaveSubmission, ScoreExercise, ApproveScore
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
    def __init__(self, score=75, mode="valid"):
        self.calls, self.score, self.mode, self.hook = [], score, mode, None
    def generate_json(self, **kwargs):
        self.calls.append(kwargs)
        if self.hook:
            hook, self.hook = self.hook, None
            hook()
        if self.mode == "error":
            raise RuntimeError("PRIVATE provider details and secret")
        if "supported" in kwargs["schema"].get("properties", {}):
            return {"supported": self.mode != "unsupported", "reason": "The proposed score follows from the task and submitted work."}
        return {"score": None if self.mode == "uncertain" else self.score,
            "summary": "The submitted quote is mostly correct against the supplied catalogue.",
            "evidence": [{"line_start": 1, "line_end": 1, "quote": "Invented quote" if self.mode == "bad_quote" else "Two Basic units cost 200 BDT."}]}

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

def approve(ctx):
    db, owner, _, row, service, *_ = ctx
    current = service.read(db, owner.id, row.id)["exercise"]["assessment"]
    service.process(current["id"])
    db.expire_all()
    current = service.read(db, owner.id, row.id)["exercise"]["assessment"]
    return service.approve(db, owner.id, row.id, ApproveScore(assessment_id=current["id"],
        submission_hash=current["submission_hash"], result_hash=current["result_hash"], confirmed=True))

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

@pytest.mark.parametrize("score", [0, 75, 100])
def test_llm_score_is_automatic_cached_private_and_requires_human_approval(exercise_setup, score):
    state = submit(exercise_setup)
    db, owner, _, row, service, cookie, _, _, model, _ = exercise_setup
    model.score = score
    current = service.read(db, owner.id, row.id)["exercise"]["assessment"]
    assert current["status"] == "queued" and not model.calls  # No model call in candidate request.
    assert service.report_sources(db, owner.id, row.application_id)[0]["assessment"] is None
    service.process(current["id"])
    db.expire_all()
    current = service.read(db, owner.id, row.id)["exercise"]["assessment"]
    assert current["status"] == "scored" and current["result"]["score"] == score and current["result"]["verified"]
    assert len(model.calls) == 2
    assert service.report_sources(db, owner.id, row.application_id)[0]["assessment"] is None
    service.score(db, owner.id, row.id, ScoreExercise(submission_hash=current["submission_hash"]))
    service.process(current["id"])
    assert len(model.calls) == 2  # Successfully scored work cannot be rerolled.
    request = ApproveScore(assessment_id=current["id"], submission_hash=current["submission_hash"],
        result_hash=current["result_hash"], confirmed=True)
    approved = service.approve(db, owner.id, row.id, request)["exercise"]["assessment"]
    assert approved["status"] == "approved" and approved["approved_by"] == owner.id
    assert service.approve(db, owner.id, row.id, request)["exercise"]["assessment"] == approved
    report = service.report_sources(db, owner.id, row.application_id)[0]["assessment"]
    assert report["score"] == score and report["result_hash"] == current["result_hash"]
    assert report["submission_hash"] == state["exercise"]["attempt"]["submission_hash"]
    candidate = service.candidate_read(db, cookie)["exercise"]
    assert not {"assessment", "decision", "assessments", "events", "attempts"} & candidate.keys()

def test_approval_requires_verified_score_matching_hash_and_confirmation(exercise_setup):
    start(exercise_setup)
    db, owner, _, row, service, cookie, *_ = exercise_setup
    with pytest.raises(RoomConflict):
        service.score(db, owner.id, row.id, ScoreExercise(submission_hash="a" * 64))
    state = service.candidate_read(db, cookie)
    service.save_submission(db, cookie, SaveSubmission(attempt_id=state["exercise"]["attempt"]["id"], revision=0, content=ANSWER, submit=True))
    current = service.read(db, owner.id, row.id)["exercise"]["assessment"]
    request = ApproveScore(assessment_id=current["id"], submission_hash=current["submission_hash"], result_hash="a" * 64, confirmed=True)
    with pytest.raises(RoomConflict): service.approve(db, owner.id, row.id, request)
    service.process(current["id"])
    db.expire_all()
    with pytest.raises(RoomConflict): service.approve(db, owner.id, row.id, request)
    with pytest.raises(ValidationError): ApproveScore(**{**request.model_dump(), "confirmed": False})
    with pytest.raises(ValidationError): ApproveScore(**{**request.model_dump(), "score": 100})
    with pytest.raises(ValidationError): ApproveScore(**{**request.model_dump(), "correct": True})

@pytest.mark.parametrize("mode,status", [("error", "failed"), ("bad_quote", "failed"), ("unsupported", "needs_verification"), ("uncertain", "needs_verification")])
def test_unavailable_or_unsupported_ai_review_never_becomes_zero_or_approvable(exercise_setup, mode, status):
    submit(exercise_setup)
    db, owner, _, row, service, _, _, _, model, _ = exercise_setup
    model.mode = mode
    current = service.read(db, owner.id, row.id)["exercise"]["assessment"]
    service.process(current["id"])
    db.expire_all()
    current = service.read(db, owner.id, row.id)["exercise"]["assessment"]
    assert current["status"] == status and current["result"].get("score") is None
    assert "PRIVATE" not in (current["error"] or "")
    assert service.report_sources(db, owner.id, row.application_id)[0]["assessment"] is None
    with pytest.raises(RoomConflict):
        service.approve(db, owner.id, row.id, ApproveScore(assessment_id=current["id"], submission_hash=current["submission_hash"],
            result_hash=current["result_hash"] or "a" * 64, confirmed=True))
    db.rollback()
    model.mode = "valid"
    service.score(db, owner.id, row.id, ScoreExercise(submission_hash=current["submission_hash"]))
    assert approve(exercise_setup)["exercise"]["assessment"]["status"] == "approved"

def test_processing_recovers_but_never_rerolls_a_verified_score(exercise_setup):
    submit(exercise_setup)
    db, owner, _, row, service, *_ = exercise_setup
    saved = db.scalar(select(WorkSampleAssessment))
    original_request = saved.snapshot["request_id"]
    saved.status = "processing"; db.commit()
    service.recover(db)
    assert saved.status == "queued" and saved.snapshot["request_id"] != original_request
    service.process(saved.id); db.expire_all()
    service.recover(db)
    assert service.read(db, owner.id, row.id)["exercise"]["assessment"]["status"] == "scored"

def test_result_from_changed_submission_cannot_be_persisted_or_approved(exercise_setup):
    submit(exercise_setup)
    db, owner, _, row, service, _, _, _, model, _ = exercise_setup
    saved = db.scalar(select(WorkSampleAssessment))
    def change():
        attempt = db.get(WorkSampleAttempt, saved.attempt_id)
        attempt.content = "Changed during model call"; db.commit()
    model.hook = change
    service.process(saved.id); db.expire_all()
    current = service.read(db, owner.id, row.id)["exercise"]["assessment"]
    assert current["status"] == "cancelled" and current["result"] == {}

def test_approved_score_cannot_follow_a_changed_submission_into_reports(exercise_setup):
    submit(exercise_setup)
    approve(exercise_setup)
    db, owner, _, row, service, *_ = exercise_setup
    assert service.report_sources(db, owner.id, row.application_id)[0]["assessment"]["score"] == 75
    attempt = db.scalar(select(WorkSampleAttempt))
    attempt.content = "A different response cannot inherit the approved grade."
    db.commit()
    assert service.report_sources(db, owner.id, row.application_id)[0]["assessment"] is None

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
        assert "assessment" not in response.json()["exercise"]
        assert client.post("/api/interview-rooms/candidate/work-sample/ready", json={"attempt_id": 1},
            headers={"Origin": "https://attacker.test"}).status_code == 403
        assert client.get(f"/api/work-samples/interviews/{row.id}").status_code == 401
        headers = {"Authorization": f"Bearer {create_access_token(owner.id)}"}
        assert client.get(f"/api/work-samples/interviews/{row.id}", headers=headers).status_code == 200
        submission_hash = service.read(db, owner.id, row.id)["exercise"]["attempt"]["submission_hash"]
        assert client.post(f"/api/work-samples/interviews/{row.id}/score", json={"submission_hash": submission_hash}).status_code == 401
        assert client.post(f"/api/work-samples/interviews/{row.id}/score", headers=headers,
            json={"submission_hash": submission_hash, "score": 100}).status_code == 422
        assert client.post(f"/api/work-samples/interviews/{row.id}/score", headers=headers,
            json={"submission_hash": submission_hash}).status_code == 200
        current = service.read(db, owner.id, row.id)["exercise"]["assessment"]
        assert client.post(f"/api/work-samples/interviews/{row.id}/approve", headers=headers,
            json={"assessment_id": current["id"], "submission_hash": submission_hash, "result_hash": "a" * 64, "confirmed": True, "score": 100}).status_code == 422
        for removed in ("assess", "review", "draft", "decision"):
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
    approve(exercise_setup)
    db, _, _, row, service, *_ = exercise_setup
    service.delete_for_interviews(db, [row.id])
    db.commit()
    for model in (WorkSampleExercise, WorkSampleAttempt, WorkSampleAssessment, WorkSampleDecision):
        assert db.scalar(select(model)) is None

def test_legacy_recovery_preserves_historical_approved_results(exercise_setup):
    state = submit(exercise_setup)
    db, owner, _, _, service, *_ = exercise_setup
    legacy = db.scalar(select(WorkSampleAssessment))
    legacy.snapshot = {}
    legacy.status, legacy.result, legacy.approved_result, legacy.approved_by = "approved", {"score": 70}, {"score": 70}, owner.id
    db.commit()
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
