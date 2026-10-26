"""Retire the obsolete graph without removing shared requirements or history."""
import ast
import importlib.util
from copy import deepcopy
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.models import RequirementProfile, RequirementProfileStatus, SupervisorSession
from app.models.requirement_session import RequirementDiscoverySession, RequirementDiscoveryStatus
from direct_job_fakes import FakeDirectModel, FakeKnowledgeBase
from test_direct_job_description import setup, supervisor, count


def test_standalone_discovery_api_and_modules_are_removed():
    # Do not start the application lifespan/workers or contact live providers.
    response = TestClient(app).post("/api/requirements/chat", json={"message": "Hire an engineer"})
    assert response.status_code == 404
    schema = app.openapi()
    assert not any(path.startswith("/api/requirements") for path in schema["paths"])
    assert not {"RequirementChatRequest", "RequirementChatResponse", "RequirementExtraction"} & set(schema["components"]["schemas"])
    assert "/api/supervisor/chat" in schema["paths"]
    for module in ("app.agents.requirement_discovery", "app.services.requirement_discovery_service", "app.routes.requirements"):
        assert importlib.util.find_spec(module) is None


def test_application_keeps_seven_distinct_graph_definitions():
    definitions = set()
    for source in (Path(__file__).parents[1] / "app").rglob("*.py"):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.ClassDef) and any(
                isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "StateGraph"
                for call in ast.walk(node)
            ):
                definitions.add(node.name)
    assert definitions == {"HireSenseSupervisorGraph", "JobPostingAssistantGraph", "ScreeningWorkflow",
        "CandidateScoringWorkflow", "InterviewAnalysisGraph", "ConsolidatedAssessmentGraph", "WorkSampleGraph"}


def test_legacy_session_and_profile_survive_resuming_through_direct_rag_drafting(setup):
    db, owner = setup
    profile = RequirementProfile(title="Historical backend role", required_skills=[{"name": "Python", "details": "Existing evidence"}],
        status=RequirementProfileStatus.CONFIRMED, created_by_user_id=owner.id)
    db.add(profile); db.flush()
    snapshot = {"messages": [{"role": "user", "content": "Historical request"}], "confirmed": True}
    legacy = RequirementDiscoverySession(interviewer_user_id=owner.id, requirement_profile_id=profile.id,
        status=RequirementDiscoveryStatus.CONFIRMED, state_json=deepcopy(snapshot))
    db.add(legacy); db.flush()
    session = SupervisorSession(interviewer_user_id=owner.id, requirement_session_id=legacy.id,
        requirement_profile_id=profile.id, phase="requirement_confirmed",
        state_json={"messages": [{"role": "user", "content": "Hire a backend engineer"}]})
    db.add(session); db.commit()
    model, knowledge = FakeDirectModel(), FakeKnowledgeBase()
    result = supervisor(model, knowledge).chat(db, interviewer_user_id=owner.id, session_id=session.id, message="Continue")
    assert result["phase"] == "job_description_draft"
    assert knowledge.calls and len(model.generate_calls) == 1
    assert result["job_description"].source_references[0]["chunk_id"] == 41
    assert result["requirement_profile_id"] != profile.id
    assert db.get(RequirementProfile, profile.id).required_skills == [{"name": "Python", "details": "Existing evidence"}]
    assert db.get(RequirementDiscoverySession, legacy.id).state_json == snapshot
    assert db.get(SupervisorSession, session.id).requirement_session_id == legacy.id
    assert count(db, RequirementDiscoverySession) == 1

