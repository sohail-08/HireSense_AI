"""Pending Google Forms response counts and their read-only API."""
import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.database import Base, get_db
from app.models import Candidate, CandidateApplication, CVDocument, JobDescription, JobPosting
from app.routes import candidates as routes
from app.security import create_access_token
from app.services import google_forms_intake_service as intake_module
from app.services.candidate_application_service import CandidateApplicationService
from app.services.google_forms_notifications import SheetSnapshotCache
from test_google_forms_intake import _settings
from test_screening import _records

HEADERS = ["Timestamp", "Full Name", "Email Address", "Phone Number", "Job Posting", "Upload your CV"]


class SheetOnlyReader:
    def __init__(self):
        self.rows = [HEADERS]
        self.reads = 0
        self.fail = False

    def read_sheet(self, **kwargs):
        self.reads += 1
        if self.fail:
            raise RuntimeError("private-provider-details")
        return [list(row) for row in self.rows]

    def get_file(self, *args, **kwargs):
        raise AssertionError("Notification checks must not access Drive")

    download_file = get_file


@pytest.fixture
def notification_setup(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    clock = [0]
    monkeypatch.setattr(intake_module, "sheet_snapshots", SheetSnapshotCache(clock=lambda: clock[0]))
    with Session(engine, expire_on_commit=False) as db:
        owner, candidate_user, posting = _records(db)
        job = JobDescription(requirement_profile_id=posting.job_description.requirement_profile_id,
            title="Frontend Engineer", content="Frontend job", created_by_user_id=owner.id)
        db.add(job); db.flush()
        frontend = JobPosting(job_description_id=job.id, platform="discord")
        db.add(frontend); db.commit()
        settings = _settings(tmp_path / "storage")
        credential = tmp_path / "fake-google.json"
        credential.write_text("{}", encoding="utf-8")
        settings = settings.model_copy(update={"google_service_account_file": str(credential)})
        reader = SheetOnlyReader()
        service = intake_module.GoogleFormsIntakeService(reader, settings)
        yield db, owner, candidate_user, posting, frontend, service, reader, clock
    engine.dispose()


def response(name, job):
    return ["10/14/2026 09:00:00", name, name.lower() + "@example.com", "", str(job), ""]


def test_counts_by_job_without_importing_downloading_or_exposing_candidate_data(notification_setup):
    db, owner, _, backend, frontend, service, reader, _ = notification_setup
    reader.rows += [response("Ada", backend.id), response("Grace", "Backend Engineer"),
                    response("Lin", frontend.id), response("Unknown", "Unknown job")]
    reader.rows += [response("Ada", backend.id), [], ["", "", "invalid-email", "", str(backend.id), ""]]
    before = [db.scalar(select(func.count(model.id))) for model in (Candidate, CandidateApplication, CVDocument)]
    summary = service.pending_responses(db, interviewer_user_id=owner.id)
    assert summary["pending_count"] == 3 and summary["unmatched_count"] == 1
    assert summary["jobs"] == [{"job_posting_id": backend.id, "job_title": "Backend Engineer", "count": 2},
                               {"job_posting_id": frontend.id, "job_title": "Frontend Engineer", "count": 1}]
    assert "example.com" not in json.dumps(summary, default=str)
    assert before == [db.scalar(select(func.count(model.id))) for model in (Candidate, CandidateApplication, CVDocument)]
    from pathlib import Path
    assert not Path(service.settings.storage_root).exists()


def test_sync_and_deleted_imports_disappear_even_with_cached_sheet(notification_setup):
    db, owner, _, posting, _, service, reader, _ = notification_setup
    reader.rows += [response("Ada", posting.id)]
    assert service.pending_responses(db, interviewer_user_id=owner.id)["pending_count"] == 1
    assert reader.reads == 1
    service.sync(db, interviewer_user_id=owner.id)
    assert service.pending_responses(db, interviewer_user_id=owner.id)["pending_count"] == 0
    assert reader.reads == 2  # One notification read plus the explicit sync read.
    application = db.scalar(select(CandidateApplication))
    CandidateApplicationService(service.settings).delete(db, application_id=application.id, interviewer_user_id=owner.id)
    assert service.pending_responses(db, interviewer_user_id=owner.id)["pending_count"] == 0
    assert reader.reads == 2


def test_edited_imported_rows_are_not_new_and_ambiguous_jobs_are_flagged(notification_setup):
    db, owner, _, posting, _, service, reader, clock = notification_setup
    reader.rows += [response("Ada", posting.id)]
    service.sync(db, interviewer_user_id=owner.id)
    reader.rows[1][1] = "Updated candidate name"
    duplicate = JobPosting(job_description_id=posting.job_description_id, platform="discord")
    db.add(duplicate); db.commit()
    reader.rows += [response("Grace", "Backend Engineer")]
    clock[0] = 65
    summary = service.pending_responses(db, interviewer_user_id=owner.id)
    assert summary["pending_count"] == 0 and summary["unmatched_count"] == 1


def test_cache_refreshes_after_a_minute_and_cools_down_failures(notification_setup):
    db, owner, _, posting, _, service, reader, clock = notification_setup
    assert service.pending_responses(db, interviewer_user_id=owner.id)["pending_count"] == 0
    reader.rows += [response("New", posting.id)]
    assert service.pending_responses(db, interviewer_user_id=owner.id)["pending_count"] == 0
    assert reader.reads == 1
    clock[0] = 61
    assert service.pending_responses(db, interviewer_user_id=owner.id)["pending_count"] == 1
    reader.fail = True
    clock[0] = 122
    for _ in range(2):
        with pytest.raises(RuntimeError, match="temporarily unavailable"):
            service.pending_responses(db, interviewer_user_id=owner.id)
    assert reader.reads == 3


def test_notifications_require_interviewer_and_errors_do_not_claim_zero(notification_setup, monkeypatch):
    db, owner, candidate_user, posting, _, service, reader, clock = notification_setup
    reader.rows += [response("Ada", posting.id)]
    monkeypatch.setattr(routes, "get_settings", lambda: service.settings)
    monkeypatch.setattr(routes, "_notification_service", lambda: service)
    app = FastAPI(); app.include_router(routes.router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        path = "/api/candidates/notifications"
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"Authorization": "Bearer " + create_access_token(candidate_user.id)}).status_code == 403
        assert reader.reads == 0
        headers = {"Authorization": "Bearer " + create_access_token(owner.id)}
        result = client.get(path, headers=headers)
        assert result.status_code == 200 and result.json()["pending_count"] == 1
        assert result.headers["cache-control"] == "no-store"
        reader.fail = True; clock[0] = 61
        result = client.get(path, headers=headers).json()
        assert result["status"] == "unavailable" and result["pending_count"] is None
        assert "private-provider-details" not in json.dumps(result)
        monkeypatch.setattr(routes, "get_settings", lambda: service.settings.model_copy(update={"google_forms_spreadsheet_id": None}))
        result = client.get(path, headers=headers).json()
        assert result["status"] == "not_configured" and result["pending_count"] is None
