import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

from supervisor_fakes import QueueToolModel
from app.database import Base, get_db
from app.models import (
    Candidate, CandidateApplication, JobDescription, JobDescriptionStatus,
    JobPosting, JobPostingStatus, RequirementProfile, RequirementProfileStatus,
    ScreeningBatch, SupervisorSession, User, UserRole,
)
from app.routes import supervisor as routes
from app.schemas.supervisor import SupervisorChatResponse
from app.security import require_interviewer
from app.services.google_forms_intake_service import GoogleFormsIntakeService
from app.services.screening_service import ScreeningService
from app.services.supervisor_service import SupervisorService
from app.services.job_description_service import JobDescriptionService
from test_google_forms_intake import FakeGoogleReader, _settings
from test_screening import FakeScreeningAI


@pytest.fixture
def scenario(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'supervisor-candidates.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    settings = _settings(tmp_path / "storage")
    model = QueueToolModel()
    service = SupervisorService(
        model=model, job_description_service=None,
        job_edit_model=None, job_posting_service=None,
        candidate_intake_service=GoogleFormsIntakeService(FakeGoogleReader(), settings),
        screening_service=ScreeningService(settings, ai=FakeScreeningAI()),
    )
    with Session(engine) as db:
        owner = User(name="Owner", email="owner@example.com", password_hash="hash", role=UserRole.INTERVIEWER)
        outsider = User(name="Other", email="other@example.com", password_hash="hash", role=UserRole.CANDIDATE)
        db.add_all([owner, outsider])
        db.flush()
        postings = []
        for title, user in [("Backend Engineer", owner), ("Frontend Engineer", owner), ("Other Job", outsider)]:
            profile = RequirementProfile(title=title, required_skills=[{"name": "Python"}], status=RequirementProfileStatus.CONFIRMED, created_by_user_id=user.id)
            db.add(profile)
            db.flush()
            job = JobDescription(requirement_profile_id=profile.id, title=title, content="Role", structured_content={}, status=JobDescriptionStatus.APPROVED, created_by_user_id=user.id)
            db.add(job)
            db.flush()
            posting = JobPosting(job_description_id=job.id, platform="discord", status=JobPostingStatus.PUBLISHED)
            db.add(posting)
            db.flush()
            postings.append(posting)
        candidate = Candidate(name="Candidate", email="candidate@example.com")
        db.add(candidate)
        db.flush()
        applications = [CandidateApplication(job_posting_id=p.id, candidate_id=candidate.id) for p in postings]
        db.add_all(applications)
        db.commit()
        yield db, owner, postings, applications, service, model
    engine.dispose()


def test_conversation_sync_imports_and_is_idempotent(scenario, tmp_path):
    db, owner, postings, applications, service, model = scenario
    model.tool_name = "sync_responses"
    model.tool_args = {}
    first = service.chat(db, interviewer_user_id=owner.id, message="Sync responses", page_context="candidates")
    validated = SupervisorChatResponse.model_validate(first)
    assert validated.sync_result.imported_applications == 1
    assert validated.sync_result.downloaded_cvs == 1
    assert validated.refresh_required and validated.outcome == "success"
    assert model.context["page_context"] == "candidates"
    assert len(model.context["available_screening_jobs"]) == 2
    second = service.chat(db, interviewer_user_id=owner.id, session_id=first["session_id"], message="Sync again")
    assert second["sync_result"]["imported_applications"] == 0
    assert second["sync_result"]["skipped_existing"] == 1
    assert list((tmp_path / "storage" / "cvs").rglob("*.pdf"))


def test_screening_uses_selected_job_and_applications_and_prevents_duplicate(scenario):
    db, owner, postings, applications, service, model = scenario
    model.tool_name = "screen_candidates"
    model.tool_args = {"screening_scope": "selected"}
    result = service.chat(db, interviewer_user_id=owner.id, message="Screen selected candidates", page_context="assessments", selected_job_posting_id=postings[1].id, selected_application_ids=[applications[1].id])
    validated = SupervisorChatResponse.model_validate(result)
    assert validated.screening_batch.job_posting_id == postings[1].id
    assert validated.screening_batch.application_ids == [applications[1].id]
    assert result["screening_started"] is True
    saved = db.get(SupervisorSession, result["session_id"])
    assert saved.state_json["last_screening_batch_id"] == validated.screening_batch.id
    duplicate = service.chat(db, interviewer_user_id=owner.id, session_id=saved.id, message="Screen again", selected_job_posting_id=postings[1].id, selected_application_ids=[applications[1].id])
    assert duplicate["outcome"] == "failure"
    assert "already running" in duplicate["assistant_message"]
    assert duplicate["screening_started"] is False
    assert db.scalar(select(func.count()).select_from(ScreeningBatch)) == 1


def test_missing_or_ambiguous_job_prompts_then_routes_reply(scenario):
    db, owner, postings, applications, service, model = scenario
    result = service.chat(db, interviewer_user_id=owner.id, message="Screen candidates")
    assert result["outcome"] == "info"
    assert "Which job posting" in result["assistant_message"]
    assert "Other Job" not in result["assistant_message"]
    assert result["screening_batch"] is None
    model.tool_name = "screen_candidates"
    model.tool_args = {"job_posting_id": postings[0].id}
    started = service.chat(db, interviewer_user_id=owner.id, session_id=result["session_id"], message="Backend Engineer")
    assert model.context["pending_screening_selection"] is True
    assert started["screening_batch"]["application_ids"] == [applications[0].id]
    model.tool_name = "screen_candidates"
    model.tool_args = {"needs_job_selection": True}
    ambiguous = service.chat(db, interviewer_user_id=owner.id, message="Screen Engineer", selected_job_posting_id=postings[1].id)
    assert ambiguous["screening_started"] is False
    assert "Which job posting" in ambiguous["assistant_message"]


def test_screening_never_accepts_foreign_job_or_cross_job_applications(scenario):
    db, owner, postings, applications, service, model = scenario
    model.tool_name = "screen_candidates"
    model.tool_args = {"job_posting_id": postings[2].id}
    result = service.chat(db, interviewer_user_id=owner.id, message="Screen post", selected_job_posting_id=postings[0].id)
    assert result["screening_batch"] is None
    model.tool_name = "screen_candidates"
    model.tool_args = {"screening_scope": "selected"}
    wrong = service.chat(db, interviewer_user_id=owner.id, message="Screen selected", selected_job_posting_id=postings[0].id, selected_application_ids=[applications[1].id])
    assert wrong["outcome"] == "failure"
    assert "do not belong" in wrong["assistant_message"]
    empty = service.chat(db, interviewer_user_id=owner.id, message="Screen selected", selected_job_posting_id=postings[0].id)
    assert empty["outcome"] == "failure"
    assert "Check at least one" in empty["assistant_message"]
    assert db.scalar(select(func.count()).select_from(ScreeningBatch)) == 0


def test_route_queues_only_new_batch_and_restore_does_not_repeat_work(scenario, monkeypatch):
    db, owner, postings, applications, service, model = scenario
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_interviewer] = lambda: owner
    monkeypatch.setattr(routes, "_service", lambda: service)
    queued = []
    monkeypatch.setattr(routes, "_process_batch", lambda batch_id: queued.append(batch_id))
    with TestClient(app) as client:
        result = client.post("/api/supervisor/chat", json={"message": "Screen candidates", "page_context": "assessments", "selected_job_posting_id": postings[0].id})
        assert result.status_code == 200, result.text
        data = result.json()
        assert queued == [data["screening_batch"]["id"]]
        assert "screening_started" not in data
        restored = client.get(f"/api/supervisor/sessions/{data['session_id']}")
        assert restored.status_code == 200
        assert restored.json()["screening_batch"]["id"] == queued[0]
        assert len(queued) == 1


def test_sync_failure_preserves_jd_phase_and_is_actionable(scenario):
    db, owner, _, _, service, model = scenario
    model.tool_name = "sync_responses"
    model.tool_args = {}
    session = SupervisorSession(interviewer_user_id=owner.id, phase="posting_approval", state_json={"messages": []})
    db.add(session)
    db.commit()
    service.candidate_intake_service = None
    def unavailable():
        raise RuntimeError("Google credentials are missing")
    service.candidate_intake_factory = unavailable
    result = service.chat(db, interviewer_user_id=owner.id, session_id=session.id, message="Sync responses")
    assert result["outcome"] == "failure"
    assert "Google credentials are missing" in result["assistant_message"]
    assert result["phase"] == "posting_approval"


def test_native_tool_cannot_invent_jd_approval(scenario):
    db, owner, postings, _, service, model = scenario
    job = db.get(JobDescription, postings[0].job_description_id)
    job.status = JobDescriptionStatus.DRAFT
    db.commit()
    service.job_description_service = JobDescriptionService(None)
    model.tool_name = "approve_job_description"
    model.tool_args = {"message": "Approve the job description"}
    denied = service.chat(
        db, interviewer_user_id=owner.id,
        message="Don't approve the job description",
        selected_job_description_id=job.id,
    )
    assert denied["outcome"] == "failure"
    assert job.status is JobDescriptionStatus.DRAFT
    model.tool_args = {}
    approved = service.chat(
        db, interviewer_user_id=owner.id, session_id=denied["session_id"],
        message="Approve the job description",
    )
    assert approved["outcome"] == "success"
    assert job.status is JobDescriptionStatus.APPROVED
