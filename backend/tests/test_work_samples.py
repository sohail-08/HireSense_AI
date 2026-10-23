"""Synthetic exercises only: no media, mail, model, browser or candidate data calls."""
import copy
import json
from datetime import timedelta
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.work_sample import WorkSampleExercise, WorkSampleAttempt, WorkSampleAssessment
from app.schemas.work_sample import Task, SaveTask, Action, CandidateReady, SaveSubmission, Evaluation, Review, validated_evaluation
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


TASK = {"title": "Customer quotation", "instructions": "Recommend the supplied product and calculate a quote for two units.",
    "materials": "Fictional catalogue: Basic costs 100 BDT per unit. No discounts or taxes apply.",
    "deliverables": "A customer email with the total and a short explanation.", "duration_minutes": 15,
    "tools_policy": "Use the supplied catalogue only. No external AI or assistance.", "response_type": "text",
    "criteria": [{"id": "calculation", "title": "Calculation", "description": "The quote correctly totals two Basic units.", "weight": 60},
                 {"id": "explanation", "title": "Explanation", "description": "The response explains the calculation.", "weight": 40}]}
ANSWER = "Two Basic units cost 200 BDT.\nNo discount applies."
EXPLANATION = "I multiplied the unit price of 100 by 2."


def evaluation():
    return {"summary": "The response gives a correct quote and explains its calculation.", "findings": [
        {"criterion_id": "calculation", "label": "met", "reason": "The total is correct for two units priced at 100 each.",
         "evidence": [{"field": "content", "line_start": 1, "line_end": 1, "quote": "Two Basic units cost 200 BDT."}]},
        {"criterion_id": "explanation", "label": "met", "reason": "The explanation identifies the multiplication used.",
         "evidence": [{"field": "explanation", "line_start": 1, "line_end": 1, "quote": EXPLANATION}]}]}


class Model:
    def __init__(self, bad_quote=False, unsupported=False):
        self.calls, self.bad_quote, self.unsupported = [], bad_quote, unsupported

    def generate_json(self, **kwargs):
        self.calls.append(kwargs)
        if "Independently verify" in kwargs["system_instruction"]:
            return {"checks": [{"criterion_id": c["id"], "supported": not self.unsupported,
                                "reason": "The cited work supports this finding." if not self.unsupported else "The supplied evidence does not establish this outcome."}
                               for c in TASK["criteria"]]}
        result = evaluation()
        if self.bad_quote:
            result["findings"][0]["evidence"][0]["quote"] = "Fabricated quote"
        return result


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
    attempt = shared["exercise"]["attempt"]
    service.ready(db, cookie, CandidateReady(attempt_id=attempt["id"]))
    return act(ctx, "start")


def submit(ctx):
    state = start(ctx)
    db, _, _, _, service, cookie, *_ = ctx
    attempt = state["exercise"]["attempt"]
    return service.save_submission(db, cookie, SaveSubmission(attempt_id=attempt["id"], revision=0,
        content=ANSWER, explanation=EXPLANATION, submit=True))


def test_draft_private_and_rubric_locks_at_share(exercise_setup):
    db, owner, _, row, service, cookie, *_ = exercise_setup
    assert service.candidate_read(db, cookie)["exercise"] is None
    shared = act(exercise_setup, "share")
    assert shared["exercise"]["approved_at"]
    assert service.candidate_read(db, cookie)["exercise"]["task"] == TASK
    with pytest.raises(RoomConflict):
        service.save_task(db, owner.id, row.id, SaveTask(task=Task(**TASK), version=shared["exercise"]["version"]))


def test_readiness_no_timer_until_interviewer_starts(exercise_setup):
    db, _, _, _, service, cookie, *_ = exercise_setup
    shared = act(exercise_setup, "share")
    assert shared["exercise"]["attempt"]["deadline_at"] is None
    with pytest.raises(RoomConflict): act(exercise_setup, "start")
    ready = service.ready(db, cookie, CandidateReady(attempt_id=shared["exercise"]["attempt"]["id"]))
    assert ready["exercise"]["status"] == "ready" and ready["exercise"]["attempt"]["deadline_at"] is None
    assert act(exercise_setup, "start")["exercise"]["status"] == "running"


def test_autosave_exact_text_revision_conflict_and_recovery(exercise_setup):
    state = start(exercise_setup)
    db, owner, _, row, service, cookie, *_ = exercise_setup
    request = SaveSubmission(attempt_id=state["exercise"]["attempt"]["id"], revision=0,
        content="  leading whitespace\n\treturn 1\n", explanation="  exact explanation  ")
    saved = service.save_submission(db, cookie, request)
    assert saved["exercise"]["attempt"]["content"] == request.content
    assert saved["exercise"]["attempt"]["explanation"] == request.explanation
    assert saved["exercise"]["attempt"]["revision"] == 1
    with pytest.raises(RoomConflict, match="another tab"):
        service.save_submission(db, cookie, request)
    assert service.read(db, owner.id, row.id)["exercise"]["attempt"]["content"] == request.content
    assert service.candidate_read(db, cookie)["exercise"]["attempt"]["content"] == request.content


def test_pause_resume_extend_and_server_deadline(exercise_setup):
    state = start(exercise_setup)
    db, _, _, _, service, cookie, clock, *_ = exercise_setup
    clock.value += timedelta(minutes=3)
    paused = act(exercise_setup, "pause", reason="Connection interrupted")
    assert paused["exercise"]["attempt"]["remaining_seconds"] == 720
    clock.value += timedelta(hours=1)
    with pytest.raises(RoomConflict):
        service.save_submission(db, cookie, SaveSubmission(attempt_id=state["exercise"]["attempt"]["id"], revision=0, content="late", explanation=""))
    extended = act(exercise_setup, "extend", reason="Restore lost connection time", extra_minutes=2)
    assert extended["exercise"]["attempt"]["remaining_seconds"] == 840
    resumed = act(exercise_setup, "resume")
    assert utc(resumed["exercise"]["attempt"]["deadline_at"]) == clock.value + timedelta(seconds=840)
    clock.value += timedelta(seconds=840)
    with pytest.raises(RoomConflict):
        service.save_submission(db, cookie, SaveSubmission(attempt_id=state["exercise"]["attempt"]["id"], revision=0, content="too late", explanation=""))
    db.expire_all()
    assert service.candidate_read(db, cookie)["exercise"]["attempt"]["status"] == "time_ended"


def test_submission_idempotent_locked_and_additional_attempt_preserves_original(exercise_setup):
    state = submit(exercise_setup)
    db, _, _, _, service, cookie, *_ = exercise_setup
    attempt = state["exercise"]["attempt"]
    assert attempt["submission_hash"] and attempt["status"] == "submitted"
    repeat = service.save_submission(db, cookie, SaveSubmission(attempt_id=attempt["id"], revision=0,
        content=ANSWER, explanation=EXPLANATION, submit=True))
    assert repeat["exercise"]["attempt"]["submission_hash"] == attempt["submission_hash"]
    with pytest.raises(RoomConflict):
        service.save_submission(db, cookie, SaveSubmission(attempt_id=attempt["id"], revision=1, content="overwrite", explanation=""))
    second = act(exercise_setup, "retry", reason="Discussed a new constraint")
    assert second["exercise"]["attempt"]["number"] == 2
    assert second["exercise"]["attempt"]["deadline_at"] is None
    assert second["exercise"]["attempts"][0]["submission_hash"] == attempt["submission_hash"]
    assert db.get(WorkSampleAttempt, attempt["id"]).content == ANSWER


def test_end_interview_preserves_unfinished_work(exercise_setup):
    state = start(exercise_setup)
    db, owner, _, row, service, cookie, _, rooms, *_ = exercise_setup
    service.save_submission(db, cookie, SaveSubmission(attempt_id=state["exercise"]["attempt"]["id"], revision=0, content="partial", explanation=""))
    rooms.end(db, owner.id, row.id)
    result = service.read(db, owner.id, row.id)
    assert result["exercise"]["attempt"]["status"] == "interview_ended"
    assert result["exercise"]["attempt"]["content"] == "partial"
    with pytest.raises(RoomAccessError): service.candidate_read(db, cookie)


def test_assessment_durable_traceable_cached_and_human_reviewed(exercise_setup):
    submit(exercise_setup)
    db, owner, _, row, service, cookie, _, _, model, _ = exercise_setup
    queued = service.assess(db, owner.id, row.id)["exercise"]["assessments"][0]
    service.process(queued["id"])
    db.expire_all()
    assessment = service.read(db, owner.id, row.id)["exercise"]["assessments"][0]
    assert assessment["status"] == "draft" and assessment["result"]["score"] == 100
    assert len(model.calls) == 2
    service.assess(db, owner.id, row.id)
    service.process(queued["id"])
    assert len(model.calls) == 2
    candidate = service.candidate_read(db, cookie)["exercise"]
    assert not {"assessments", "result", "events", "attempts", "approved_result"} & candidate.keys()
    source = service.report_sources(db, owner.id, row.application_id)[0]
    assert source["assessment"] is None  # AI drafts never become report conclusions.
    request = Review(assessment_id=queued["id"], result=Evaluation(**evaluation()), reason="Reviewed the submitted quote and calculation.")
    approved = service.review(db, owner.id, row.id, request)["exercise"]["assessments"][0]
    assert approved["status"] == "approved" and approved["approved_by"] == owner.id
    assert approved["approved_result"]["score"] == 100
    assert service.report_sources(db, owner.id, row.application_id)[0]["assessment"]["score"] == 100
    with pytest.raises(RoomConflict): service.review(db, owner.id, row.id, request)


@pytest.mark.parametrize("case", ["quote", "line", "missing_criterion", "duplicate", "missing_evidence"])
def test_rejects_unsupported_or_incomplete_evidence(case):
    value = evaluation()
    if case == "quote": value["findings"][0]["evidence"][0]["quote"] = "Invented"
    elif case == "line": value["findings"][0]["evidence"][0]["line_start"] = 5
    elif case == "missing_criterion": value["findings"].pop()
    elif case == "duplicate": value["findings"][1]["criterion_id"] = "calculation"
    elif case == "missing_evidence": value["findings"][0]["evidence"] = []
    with pytest.raises(ValueError): validated_evaluation(TASK, {"content": ANSWER, "explanation": EXPLANATION}, Evaluation(**value))


def test_unknown_is_not_zero_and_weights_are_deterministic():
    value = evaluation()
    value["findings"][0]["label"] = "needs_verification"
    assert validated_evaluation(TASK, {"content": ANSWER, "explanation": EXPLANATION}, Evaluation(**value))["score"] is None
    value["findings"][0]["label"] = "partially_met"
    assert validated_evaluation(TASK, {"content": ANSWER, "explanation": EXPLANATION}, Evaluation(**value))["score"] == 70


@pytest.mark.parametrize("bad_quote,unsupported,status", [(True, False, "failed"), (False, True, "draft")])
def test_model_failure_or_failed_support_never_becomes_zero(exercise_setup, bad_quote, unsupported, status):
    submit(exercise_setup)
    db, owner, _, row, service, *_ = exercise_setup
    service.model = Model(bad_quote=bad_quote, unsupported=unsupported)
    assessment = service.assess(db, owner.id, row.id)["exercise"]["assessments"][0]
    service.process(assessment["id"])
    db.expire_all()
    result = service.read(db, owner.id, row.id)["exercise"]["assessments"][0]
    assert result["status"] == status
    if status == "draft":
        assert result["result"]["score"] is None
        assert all(f["label"] == "needs_verification" for f in result["result"]["findings"])
    else: assert result["result"] == {}


def test_owner_scope_and_revocation(exercise_setup):
    db, owner, other, row, service, cookie, _, rooms, *_ = exercise_setup
    with pytest.raises((PermissionError, LookupError)): service.read(db, other.id, row.id)
    with pytest.raises(RoomAccessError): service.candidate_read(db, "a" * 43)
    rooms.revoke(db, owner.id, row.id)
    with pytest.raises(RoomAccessError): service.candidate_read(db, cookie)


def test_templates_are_private_and_copied(exercise_setup):
    db, owner, other, _, service, *_ = exercise_setup
    template = service.template(db, owner.id, Task(**TASK))
    assert service.list_templates(db, owner.id)[0]["id"] == template["id"]
    assert service.list_templates(db, other.id) == []


@pytest.mark.parametrize("change", ["weight", "duplicate", "duration"])
def test_task_constraints(change):
    value = copy.deepcopy(TASK)
    if change == "weight": value["criteria"][0]["weight"] = 20
    elif change == "duplicate": value["criteria"][1]["id"] = "calculation"
    else: value["duration_minutes"] = 200
    with pytest.raises(ValidationError): Task(**value)


def test_routes_candidate_auth_origin_and_no_assessment_leak(exercise_setup, monkeypatch):
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
        assert "assessments" not in response.json()["exercise"]
        assert client.post("/api/interview-rooms/candidate/work-sample/ready", json={"attempt_id": 1},
            headers={"Origin": "https://attacker.test"}).status_code == 403
        assert client.get(f"/api/work-samples/interviews/{row.id}").status_code == 401
        token = create_access_token(owner.id)
        response = client.get(f"/api/work-samples/interviews/{row.id}", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200


def test_report_approved_work_is_separate_and_html_escaped(exercise_setup):
    submit(exercise_setup)
    db, owner, _, row, service, *_ = exercise_setup
    source = synthetic_source()
    before = ConsolidatedAssessmentGraph().graph.invoke({"snapshot": source})["result"]["score_summary"]
    source["practical_assessments"] = service.report_sources(db, owner.id, row.application_id)
    source["practical_assessments"][0]["content"] = "<script>untrusted()</script>"
    result = ConsolidatedAssessmentGraph().graph.invoke({"snapshot": source})["result"]
    assert result["score_summary"] == before
    assert result["practical_assessments"][0]["assessment"] is None
    html = render_html({"kind": "individual", "reports": [{"id": 1, "result": result, "created_at": "2026-10-23T00:00:00Z"}]})
    assert "Practical assessment" in html and "&lt;script&gt;" in html
    assert "<script>untrusted()" not in html


def test_delete_removes_attempts_and_derived_reviews(exercise_setup):
    submit(exercise_setup)
    db, owner, _, row, service, *_ = exercise_setup
    service.assess(db, owner.id, row.id)
    service.delete_for_interviews(db, [row.id])
    db.commit()
    assert db.scalar(select(WorkSampleExercise)) is None
    assert db.scalar(select(WorkSampleAttempt)) is None
    assert db.scalar(select(WorkSampleAssessment)) is None


def test_interrupted_assessment_recovery_does_not_reroll_accepted_draft(exercise_setup):
    submit(exercise_setup)
    db, owner, _, row, service, *_ = exercise_setup
    assessment = service.assess(db, owner.id, row.id)["exercise"]["assessments"][0]
    saved = db.get(WorkSampleAssessment, assessment["id"])
    saved.status = "processing"
    db.commit()
    service.recover(db)
    assert saved.status == "queued"
    service.process(saved.id)
    db.expire_all()
    service.recover(db)
    assert db.get(WorkSampleAssessment, saved.id).status == "draft"


def test_unshared_task_cannot_be_assessed(exercise_setup):
    db, owner, _, row, service, *_ = exercise_setup
    with pytest.raises(RoomConflict): service.assess(db, owner.id, row.id)


def test_discussion_evidence_requires_exact_candidate_source():
    value = evaluation()
    source = {"id": "a" * 64, "speaker": "CANDIDATE", "text": "The total is 200 BDT."}
    value["findings"][0]["evidence"] = [{"field": "discussion", "segment_id": source["id"],
        "line_start": 1, "line_end": 1, "quote": source["text"]}]
    checked = validated_evaluation(TASK, {"content": ANSWER, "explanation": EXPLANATION}, Evaluation(**value), [source])
    assert checked["score"] == 100
    with pytest.raises(ValueError):
        validated_evaluation(TASK, {"content": ANSWER, "explanation": EXPLANATION}, Evaluation(**value), [])
    source["speaker"] = "INTERVIEWER"
    with pytest.raises(ValueError):
        validated_evaluation(TASK, {"content": ANSWER, "explanation": EXPLANATION}, Evaluation(**value), [source])


def test_discussion_link_scope_and_retention_cleanup(exercise_setup):
    from app.models.transcription import TranscriptionSession, TranscriptionStream, TranscriptSegment
    from app.services.transcription_service import TranscriptionService
    submit(exercise_setup)
    db, owner, _, row, service, _, clock, *_ = exercise_setup
    sid, stream_id, segment_id = "b" * 32, "c" * 32, "d" * 64
    expiry = clock.value + timedelta(days=1)
    session = TranscriptionSession(id=sid, interview_id=row.id, model="synthetic", language="en-US", status="completed",
        started_by=owner.id, expires_at=expiry, worker_identity="synthetic-worker")
    db.add(session); db.flush()
    db.add(TranscriptionStream(id=stream_id, session_id=sid, speaker="CANDIDATE", participant_reference=row.application_id,
        participant_identity="synthetic-candidate", track_sid="synthetic-track", start_offset_ms=0)); db.flush()
    db.add(TranscriptSegment(id=segment_id, session_id=sid, interview_id=row.id, stream_id=stream_id, speaker="CANDIDATE",
        participant_reference=row.application_id, participant_identity="synthetic-candidate", track_sid="synthetic-track", provider_request_id="test",
        provider_segment_id="1", sequence=1, text="The total is 200 BDT.", start_offset_ms=1000, end_offset_ms=2000,
        stream_start_offset_ms=1000, start_at=clock.value, end_at=clock.value + timedelta(seconds=1), language="en-US"))
    db.commit()
    with pytest.raises(ValueError): service.assess(db, owner.id, row.id, ["e" * 64])
    db.rollback()
    state = service.assess(db, owner.id, row.id, [segment_id])
    saved = db.get(WorkSampleAssessment, state["exercise"]["assessments"][0]["id"])
    assert saved.snapshot["discussion"][0]["id"] == segment_id
    assert utc(db.get(WorkSampleExercise, state["exercise"]["id"]).expires_at) == expiry
    TranscriptionService.delete_for_interviews(db, [row.id])
    db.commit()
    assert db.scalar(select(WorkSampleAssessment)) is None
    assert db.scalar(select(WorkSampleAttempt)).content == ANSWER


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
