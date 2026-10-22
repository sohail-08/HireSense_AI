import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models.candidate import ApplicationImportExclusion, Candidate, CandidateApplication, CVDocument
from app.models.job import JobDescription, JobPosting
from app.routes import candidates
from app.security import create_access_token, require_interviewer
from app.services.candidate_application_service import CandidateApplicationService
from test_screening import _application_with_docx, _records, _settings


@pytest.fixture
def batch(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False, autoflush=False) as db:
        owner, other, posting = _records(db)
        first, doc1 = _application_with_docx(db, tmp_path, posting, 1)
        second, doc2 = _application_with_docx(db, tmp_path, posting, 2)
        db.commit()
        settings = _settings(tmp_path)
        monkeypatch.setattr(candidates, "get_settings", lambda: settings)
        api = FastAPI(); api.include_router(candidates.router)
        api.dependency_overrides[get_db] = lambda: db
        api.dependency_overrides[require_interviewer] = lambda: owner
        with TestClient(api) as client:
            yield db, owner, other, first, second, doc1, doc2, tmp_path, client, api, settings
    engine.dispose()


def test_bulk_delete_commits_all_records_and_cleans_files_and_import_references(batch):
    db, owner, _, first, second, doc1, doc2, root, client, _, _ = batch
    paths = [root / doc1.storage_path, root / doc2.storage_path]
    ids = [first.id, second.id]
    candidate_ids = [first.candidate_id, second.candidate_id]
    response = client.post("/api/candidates/applications/bulk-delete", json={"application_ids": [*ids, first.id]})
    assert response.status_code == 200
    assert response.json() == {"deleted_application_ids": ids, "deleted_count": 2}
    assert db.scalar(select(func.count()).select_from(CandidateApplication)) == 0
    assert db.scalar(select(func.count()).select_from(CVDocument)) == 0
    assert all(db.get(Candidate, value) is None for value in candidate_ids)
    assert all(not path.exists() for path in paths)
    assert db.scalar(select(func.count()).select_from(ApplicationImportExclusion)) == 2


@pytest.mark.parametrize("values", [[], [0], [-1], [True], ["1"], list(range(1, 102))])
def test_bulk_delete_rejects_invalid_selections_without_mutation(batch, values):
    db, _, _, first, _, doc1, _, root, client, _, _ = batch
    assert client.post("/api/candidates/applications/bulk-delete", json={"application_ids": values}).status_code == 422
    assert db.get(CandidateApplication, first.id) is not None
    assert (root / doc1.storage_path).is_file()


def test_unknown_id_rejects_entire_selection(batch):
    db, _, _, first, _, doc1, _, root, client, _, _ = batch
    response = client.post("/api/candidates/applications/bulk-delete", json={"application_ids": [first.id, 999999]})
    assert response.status_code == 404
    assert db.get(CandidateApplication, first.id) is not None
    assert (root / doc1.storage_path).is_file()
    assert db.scalar(select(func.count()).select_from(ApplicationImportExclusion)) == 0


def test_mixed_ownership_rejects_whole_selection(batch):
    db, _, other, first, second, doc1, doc2, root, client, _, _ = batch
    posting = db.get(JobPosting, second.job_posting_id)
    job = db.get(JobDescription, posting.job_description_id)
    foreign_job = JobDescription(requirement_profile_id=job.requirement_profile_id,
        title="Other job", content="Synthetic", created_by_user_id=other.id)
    db.add(foreign_job); db.flush()
    foreign_posting = JobPosting(job_description_id=foreign_job.id)
    db.add(foreign_posting); db.flush()
    second.job_posting_id = foreign_posting.id; db.commit()
    response = client.post("/api/candidates/applications/bulk-delete", json={"application_ids": [first.id, second.id]})
    assert response.status_code == 404
    assert db.scalar(select(func.count()).select_from(CandidateApplication)) == 2
    assert all((root / doc.storage_path).is_file() for doc in [doc1, doc2])


def test_failure_rolls_back_earlier_deletes_and_keeps_all_files(batch, monkeypatch):
    db, owner, _, first, second, doc1, doc2, root, _, _, settings = batch
    ids = [first.id, second.id]
    paths = [root / doc1.storage_path, root / doc2.storage_path]
    service = CandidateApplicationService(settings)
    original = service.delete_record
    calls = 0
    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2: raise ValueError("Synthetic deletion failure")
        return original(*args, **kwargs)
    monkeypatch.setattr(service, "delete_record", fail_second)
    with pytest.raises(ValueError, match="Synthetic"):
        service.delete_many(db, application_ids=ids, interviewer_user_id=owner.id)
    assert db.scalar(select(func.count()).select_from(CandidateApplication)) == 2
    assert db.scalar(select(func.count()).select_from(CVDocument)) == 2
    assert db.scalar(select(func.count()).select_from(ApplicationImportExclusion)) == 0
    assert all(path.is_file() for path in paths)


def test_shared_candidate_is_preserved_when_another_application_remains(batch):
    db, _, _, first, second, doc1, _, root, client, _, _ = batch
    candidate_id = first.candidate_id
    second.candidate_id = candidate_id; db.commit()
    assert client.post("/api/candidates/applications/bulk-delete", json={"application_ids": [first.id]}).status_code == 200
    assert db.get(Candidate, candidate_id) is not None
    assert db.get(CandidateApplication, second.id) is not None
    assert not (root / doc1.storage_path).exists()


def test_bulk_delete_requires_authentication(batch):
    db, _, other, first, _, _, _, _, client, api, _ = batch
    del api.dependency_overrides[require_interviewer]
    assert client.post("/api/candidates/applications/bulk-delete", json={"application_ids": [first.id]}).status_code == 401
    response = client.post("/api/candidates/applications/bulk-delete", json={"application_ids": [first.id]},
        headers={"Authorization": "Bearer " + create_access_token(other.id)})
    assert response.status_code == 403
    assert db.get(CandidateApplication, first.id) is not None
