import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import JobDescription, JobDescriptionStatus, RequirementProfile, RequirementProfileStatus, User, UserRole
from app.routes import job_descriptions
from app.security import get_current_user


@pytest.fixture
def api(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        owner = User(name="Synthetic interviewer", email="manual@example.test", password_hash="test-only", role=UserRole.INTERVIEWER)
        # The app deliberately permits only one stored interviewer. A synthetic
        # foreign identity still verifies ownership checks without changing that rule.
        other = User(id=99999, name="Other interviewer", email="other-manual@example.test", password_hash="test-only", role=UserRole.INTERVIEWER)
        candidate = User(name="Synthetic candidate", email="candidate-manual@example.test", password_hash="test-only", role=UserRole.CANDIDATE)
        db.add_all([owner, candidate]); db.commit()

    def database():
        with sessions() as db:
            yield db

    # Constructing a generation service must never be necessary to create a manual job.
    def no_model():
        raise AssertionError("Manual creation attempted to construct an AI/RAG service")

    monkeypatch.setattr(job_descriptions, "_service", no_model)
    app = FastAPI()
    app.include_router(job_descriptions.router)
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = lambda: owner
    with TestClient(app) as client:
        yield client, sessions, app, owner, other, candidate
    engine.dispose()


def payload():
    return {"title": "  Frontend Engineer  ", "content": "  Build accessible React applications.\nWork with designers.  ",
            "required_skills": [{"name": "React"}, {"name": "TypeScript"}], "preferred_skills": [{"name": "Cypress"}],
            "qualifications": [{"name": "Computer Science degree"}], "min_years_experience": 3}


def test_manual_creation_saves_owned_draft_and_screening_requirements_without_ai(api):
    client, sessions, _, owner, _, _ = api
    response = client.post("/api/job-descriptions/manual", json=payload())
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved["title"] == "Frontend Engineer"
    assert saved["content"] == "Build accessible React applications.\nWork with designers."
    assert saved["status"] == "draft"
    assert saved["version"] == 1
    assert saved["created_by_user_id"] == owner.id
    assert saved["source_references"] == []
    with sessions() as db:
        profile = db.get(RequirementProfile, saved["requirement_profile_id"])
        assert profile.created_by_user_id == owner.id
        assert profile.status == RequirementProfileStatus.CONFIRMED
        assert profile.required_skills == [{"name": "React", "details": None}, {"name": "TypeScript", "details": None}]
        assert profile.qualifications[0]["name"] == "Computer Science degree"
        assert profile.preferred_skills[0]["name"] == "Cypress"
        assert profile.min_years_experience == 3
        assert profile.generation_metadata == {"source": "manual", "model_used": False}
        assert profile.selection_criteria == []
        assert db.get(JobDescription, saved["id"]).status == JobDescriptionStatus.DRAFT
        from app.services.screening_service import ScreeningService
        snapshot, _ = ScreeningService._requirement_snapshot(profile)
        names = [item["name"] for item in snapshot["requirements"]]
        assert "React" in names and "Computer Science degree" in names
        assert "At least 3 years of relevant experience" in names


@pytest.mark.parametrize("changes", [
    {"title": "  "}, {"content": "\n "}, {"required_skills": []}, {"required_skills": [{"name": "  "}]},
    {"min_years_experience": -1}, {"min_years_experience": 101}, {"min_years_experience": 1.5},
    {"created_by_user_id": 999}, {"status": "approved"}, {"source_references": [{"quote": "forged"}]},
])
def test_invalid_manual_input_creates_no_partial_records(api, changes):
    client, sessions, *_ = api
    response = client.post("/api/job-descriptions/manual", json={**payload(), **changes})
    assert response.status_code == 422
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(JobDescription)) == 0
        assert db.scalar(select(func.count()).select_from(RequirementProfile)) == 0


def test_manual_creation_preserves_unspecified_experience_without_inventing_requirements(api):
    client, sessions, *_ = api
    data = payload(); data.pop("min_years_experience"); data.pop("preferred_skills"); data.pop("qualifications")
    response = client.post("/api/job-descriptions/manual", json=data)
    assert response.status_code == 201
    saved = response.json()
    with sessions() as db:
        profile = db.get(RequirementProfile, saved["requirement_profile_id"])
        assert profile.min_years_experience is None
        assert profile.qualifications == []
        assert profile.preferred_skills == []
    assert saved["structured_content"]["experience_requirement"] == "Not specified."


def test_candidates_cannot_create_manual_jobs(api):
    client, sessions, app, _, _, candidate = api
    app.dependency_overrides[get_current_user] = lambda: candidate
    assert client.post("/api/job-descriptions/manual", json=payload()).status_code == 403
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(JobDescription)) == 0


def test_anonymous_users_cannot_create_manual_jobs(api):
    client, _, app, *_ = api
    app.dependency_overrides.pop(get_current_user)
    assert client.post("/api/job-descriptions/manual", json=payload()).status_code == 401


def test_other_interviewers_cannot_read_or_approve_manual_jobs(api, monkeypatch):
    client, _, app, _, other, _ = api
    saved = client.post("/api/job-descriptions/manual", json=payload()).json()
    from app.services.job_description_service import JobDescriptionService
    monkeypatch.setattr(job_descriptions, "_service", lambda: JobDescriptionService(model=None))
    app.dependency_overrides[get_current_user] = lambda: other
    assert client.get(f"/api/job-descriptions/{saved['id']}").status_code == 404
    assert client.post(f"/api/job-descriptions/{saved['id']}/approve").status_code == 404


def test_manual_job_can_be_approved_and_listed_using_existing_flow(api, monkeypatch):
    client, _, _, *_ = api
    saved = client.post("/api/job-descriptions/manual", json=payload()).json()
    from app.services.job_description_service import JobDescriptionService
    monkeypatch.setattr(job_descriptions, "_service", lambda: JobDescriptionService(model=None))
    response = client.post(f"/api/job-descriptions/{saved['id']}/approve")
    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert client.get("/api/job-descriptions").json()[0]["id"] == saved["id"]


def test_manual_profile_and_job_are_rolled_back_together_on_save_failure(api, monkeypatch):
    _, sessions, _, owner, *_ = api
    from app.services.job_description_service import JobDescriptionService
    from app.schemas.job import JobDescriptionManualCreate
    with sessions() as db:
        def fail_commit():
            raise RuntimeError("Synthetic database failure")
        monkeypatch.setattr(db, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="Synthetic database failure"):
            JobDescriptionService.create_manual(db, data=JobDescriptionManualCreate(**payload()), interviewer_user_id=owner.id)
        assert db.scalar(select(func.count()).select_from(JobDescription)) == 0
        assert db.scalar(select(func.count()).select_from(RequirementProfile)) == 0
