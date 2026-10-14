import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.database import get_db
from app.models.knowledge import KnowledgeDocument, KnowledgeSourceType
from app.rag.embeddings import HashEmbeddingProvider
from app.rag.service import KnowledgeBaseService
from app.routes import interview_rooms as routes
from app.schemas.interview_copilot import CopilotRequest
from app.security import create_access_token
from app.seed_interview_questions import seed_interview_questions
from app.services.interview_copilot import InterviewCopilot
from app.services.interview_rooms import RoomConflict
from test_interview_rooms import room_setup, setup, records  # noqa: F401


class FakeModel:
    def __init__(self):
        self.calls = []
        self.invalid = False

    def generate_json(self, **kwargs):
        prompt = json.loads(kwargs["prompt"])
        self.calls.append(prompt)
        return {"message": "Here is a relevant interview question.", "questions": [{
            "question": "How would you validate a Python API request?", "requirement": "Python",
            "source_ids": [999999 if self.invalid else prompt["question_bank"][0]["chunk_id"]]}]}


def copilot(db):
    knowledge = KnowledgeBaseService(HashEmbeddingProvider())
    knowledge.ingest_document(db, title="Python interview questions", content="Backend Engineer Python API validation interview questions",
        source_type=KnowledgeSourceType.INTERVIEW_QUESTION)
    return InterviewCopilot(knowledge, FakeModel())


def test_question_seed_is_idempotent_and_not_used_as_previous_jds(room_setup):
    db = room_setup[0][0]
    assert seed_interview_questions(db, HashEmbeddingProvider()) == 24
    assert seed_interview_questions(db, HashEmbeddingProvider()) == 0
    assert db.scalar(select(func.count(KnowledgeDocument.id))) == 24
    knowledge = KnowledgeBaseService(HashEmbeddingProvider())
    assert knowledge.list_documents(db) == []
    assert knowledge.search(db, "Frontend Engineer React") == []
    assert knowledge.search(db, "Frontend Engineer React", source_type=KnowledgeSourceType.INTERVIEW_QUESTION)


def test_context_and_rag_history_are_private_persistent_and_cited(room_setup):
    db, owner, other, _, apps, _, _, _ = room_setup[0]
    row = room_setup[4]
    service = copilot(db)
    context = service.context(db, owner.id, row.id)
    assert context["candidate"]["name"] == apps[0].candidate.name
    assert context["candidate"]["skills"]
    with pytest.raises(PermissionError): service.context(db, other.id, row.id)
    result = service.ask(db, owner.id, row.id, CopilotRequest(message="Suggest Python interview questions", version=0))
    assert result["version"] == 1 and len(result["messages"]) == 2
    assert result["messages"][1]["questions"][0]["source_ids"][0] == result["messages"][1]["sources"][0]["chunk_id"]
    assert "candidate" not in service.model.calls[0]
    assert apps[0].candidate.email not in json.dumps(service.model.calls[0])
    assert service.context(db, owner.id, row.id)["messages"] == result["messages"]
    with pytest.raises(RoomConflict):
        service.ask(db, owner.id, row.id, CopilotRequest(message="Again", version=0))


def test_no_sources_and_provider_failures_do_not_fabricate_questions(room_setup):
    db, owner, *_ = room_setup[0]
    row = room_setup[4]
    service = InterviewCopilot(KnowledgeBaseService(HashEmbeddingProvider()), FakeModel())
    result = service.ask(db, owner.id, row.id, CopilotRequest(message="Suggest questions", version=0))
    assert not result["messages"][-1]["questions"] and not service.model.calls
    service = copilot(db)
    service.model.invalid = True
    with pytest.raises(RuntimeError):
        service.ask(db, owner.id, row.id, CopilotRequest(message="Backend Engineer Python questions", version=1))
    assert service.context(db, owner.id, row.id)["version"] == 1


def test_candidate_cookie_cannot_access_private_context_or_chat(room_setup):
    db, owner, other, *_ = room_setup[0]
    row = room_setup[4]
    service = copilot(db)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[routes.get_copilot] = lambda: service
    with TestClient(app) as client:
        path = f"/api/interview-rooms/{row.id}/copilot"
        client.cookies.set(routes.COOKIE_NAME, "candidate-test-cookie")
        assert client.get(path).status_code == 401
        assert client.post(path, json={"message": "Suggest questions", "version": 0}).status_code == 401
        headers = {"Authorization": "Bearer " + create_access_token(other.id)}
        assert client.get(path, headers=headers).status_code == 403
        # This app intentionally permits one interviewer account. Simulate an
        # unowned schedule instead of bypassing that business constraint.
        row.created_by_user_id = other.id
        db.commit()
        unauthorized = {"Authorization": "Bearer " + create_access_token(owner.id)}
        assert client.get(path, headers=unauthorized).status_code == 404
        assert client.post(path, headers=unauthorized, json={"message": "Suggest questions", "version": 0}).status_code == 404
        row.created_by_user_id = owner.id
        db.commit()
        headers = {"Authorization": "Bearer " + create_access_token(owner.id)}
        response = client.get(path, headers=headers)
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert client.post(path, headers=headers, json={"message": "   ", "version": 0}).status_code == 422
        response = client.post(path, headers=headers, json={"message": "Backend Engineer Python questions", "version": 0})
        assert response.status_code == 200
        assert response.json()["version"] == 1
