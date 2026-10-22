import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.agents.direct_job_description import GeminiDirectJobDescriptionModel, JobDraftPlan
from app.database import Base
from app.models import JobDescription, JobDescriptionStatus, JobPosting, RequirementProfile, RequirementProfileStatus, SupervisorSession, User, UserRole
from app.models.requirement_session import RequirementDiscoverySession
from app.models.knowledge import KnowledgeSourceType
from app.rag.service import KnowledgeBaseService
from app.schemas.supervisor import SupervisorChatResponse
from app.services.direct_job_description_service import DirectJobDescriptionService
from app.services.supervisor_service import SupervisorService
from direct_job_fakes import FakeDirectModel, FakeKnowledgeBase, grounded_draft, reference
from supervisor_fakes import QueueToolModel


@pytest.fixture
def setup(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'direct-jobs.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        owner = User(name="Test interviewer", email="direct@example.test", password_hash="test", role=UserRole.INTERVIEWER)
        db.add(owner)
        db.commit()
        yield db, owner
    engine.dispose()


def supervisor(model, knowledge=None, routes=None):
    service = SupervisorService(model=routes or QueueToolModel(["generate_job_description"]),
        direct_job_service=DirectJobDescriptionService(model, knowledge or FakeKnowledgeBase()),
        job_description_service=None, job_edit_model=None, job_posting_service=None)
    # Existing saved-job lookup remains owner-scoped in production; this test
    # uses the real service with no generation model or external embedding calls.
    from app.services.job_description_service import JobDescriptionService
    service.job_description_service = JobDescriptionService(model=None)
    return service


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_role_request_creates_jd_in_one_turn_and_internal_screening_data(setup):
    db, owner = setup
    model = FakeDirectModel()
    service = supervisor(model)
    result = service.chat(db, interviewer_user_id=owner.id, message="I want to hire a backend engineer")
    validated = SupervisorChatResponse.model_validate(result)
    assert validated.phase == "job_description_draft"
    assert validated.job_description.status == JobDescriptionStatus.DRAFT
    profile = db.get(RequirementProfile, result["requirement_profile_id"])
    assert profile.status == RequirementProfileStatus.CONFIRMED
    assert profile.required_skills == [{"name": "Python", "details": None}]
    assert profile.min_years_experience == 3
    assert profile.qualifications == profile.selection_criteria == []
    assert count(db, RequirementDiscoverySession) == count(db, JobPosting) == 0
    assert len(model.generate_calls) == 1
    assert result["job_description"].source_references[0]["chunk_id"] == 41
    assert "## Qualifications" not in result["job_description"].content
    assert "## Selection Process" not in result["job_description"].content
    assert "approve" in validated.assistant_message


@pytest.mark.parametrize("evidence", [[], [reference()]])
def test_missing_or_unrelated_knowledge_asks_for_details_without_saving(setup, evidence):
    db, owner = setup
    model = FakeDirectModel([JobDraftPlan(role_title="Marine Biologist", follow_up_question="What skills and duties should this role include?")])
    result = supervisor(model, FakeKnowledgeBase(evidence)).chat(db, interviewer_user_id=owner.id,
        message="I want to hire a marine biologist")
    assert result["phase"] == "job_details" and result["outcome"] == "info"
    assert "knowledge base" in result["assistant_message"] and "skills" in result["assistant_message"]
    assert result["job_description"] is None and result["requirement_profile_id"] is None
    assert count(db, RequirementProfile) == count(db, JobDescription) == 0
    assert model.generate_calls == []


def test_user_details_create_jd_on_followup_without_an_extra_generate_or_confirm_step(setup):
    db, owner = setup
    details = "Use Python and build and test APIs. We need 3 years of experience."
    model = FakeDirectModel([
        JobDraftPlan(role_title="Backend Engineer"),
        JobDraftPlan(role_title="Backend Engineer", user_details_sufficient=True,
            detail_quotes=["Use Python", "build and test APIs"]),
    ])
    kb = FakeKnowledgeBase([])
    service = supervisor(model, kb, QueueToolModel(["generate_job_description"] * 2))
    first = service.chat(db, interviewer_user_id=owner.id, message="I want to hire a backend engineer")
    restored = service.get_session(db, interviewer_user_id=owner.id, session_id=first["session_id"])
    assert restored["job_description"] is None and model.generate_calls == []
    result = service.chat(db, interviewer_user_id=owner.id, session_id=first["session_id"], message=details)
    assert result["phase"] == "job_description_draft"
    assert len(result["messages"]) == 4
    assert model.generate_calls[0]["evidence"] == []
    assert model.generate_calls[0]["messages"][-1]["content"] == details
    assert "Backend Engineer" in kb.calls[-1]["query"]
    assert result["job_description"].source_references == []


@pytest.mark.parametrize("quotes", [[], ["Invented Python skills and API responsibilities"]])
def test_model_cannot_substitute_its_own_details_for_the_interviewers(setup, quotes):
    db, owner = setup
    model = FakeDirectModel([JobDraftPlan(role_title="Backend Engineer", user_details_sufficient=True, detail_quotes=quotes)])
    result = supervisor(model, FakeKnowledgeBase([])).chat(db, interviewer_user_id=owner.id,
        message="I want to hire a backend engineer")
    assert result["job_description"] is None
    assert model.generate_calls == [] and count(db, RequirementProfile) == 0


def test_a_complete_initial_request_can_supply_missing_knowledge(setup):
    db, owner = setup
    model = FakeDirectModel([JobDraftPlan(role_title="Backend Engineer", user_details_sufficient=True,
        detail_quotes=["Python", "build and test APIs"])])
    result = supervisor(model, FakeKnowledgeBase([])).chat(db, interviewer_user_id=owner.id,
        message="Hire a backend engineer using Python to build and test APIs. At least 3 years of experience.")
    assert result["phase"] == "job_description_draft" and len(model.generate_calls) == 1


def test_old_assistant_proposals_cannot_supply_missing_user_details(setup):
    db, owner = setup
    session = SupervisorSession(interviewer_user_id=owner.id, phase="requirement_confirmation",
        state_json={"messages": [{"role": "user", "content": "Hire a backend engineer"},
            {"role": "assistant", "content": "Use Python to build and test APIs"}]})
    db.add(session); db.commit()
    model = FakeDirectModel([JobDraftPlan(role_title="Backend Engineer", user_details_sufficient=True,
        detail_quotes=["Use Python", "build and test APIs"])])
    result = supervisor(model, FakeKnowledgeBase([])).chat(db, interviewer_user_id=owner.id,
        session_id=session.id, message="Continue")
    assert result["job_description"] is None and model.generate_calls == []


def test_missing_experience_and_qualifications_are_not_filled_with_defaults(setup):
    db, owner = setup
    draft = grounded_draft().model_copy(update={"min_years_experience": None, "experience_requirement": "Not specified."})
    result = supervisor(FakeDirectModel(draft=draft)).chat(db, interviewer_user_id=owner.id, message="Hire a backend engineer")
    profile = db.get(RequirementProfile, result["requirement_profile_id"])
    assert profile.min_years_experience is None
    assert profile.qualifications == []


def test_explicit_jd_approval_is_still_required_even_if_router_selects_approval(setup):
    db, owner = setup
    service = supervisor(FakeDirectModel(), routes=QueueToolModel(["generate_job_description", "approve_job_description"]))
    first = service.chat(db, interviewer_user_id=owner.id, message="Hire a backend engineer")
    result = service.chat(db, interviewer_user_id=owner.id, session_id=first["session_id"], message="What happens next?")
    assert result["outcome"] == "failure"
    assert result["job_description"].status == JobDescriptionStatus.DRAFT
    assert count(db, JobPosting) == 0


def test_only_relevant_validated_chunks_reach_the_writer(setup):
    db, owner = setup
    model = FakeDirectModel()
    supervisor(model, FakeKnowledgeBase([reference(), reference(42)])).chat(db,
        interviewer_user_id=owner.id, message="I want to hire a backend engineer")
    assert [item.chunk_id for item in model.generate_calls[0]["evidence"]] == [41]


def test_unknown_citation_is_rejected_without_creating_records(setup):
    db, owner = setup
    model = FakeDirectModel([JobDraftPlan(role_title="Backend Engineer", relevant_chunk_ids=[999])])
    result = supervisor(model).chat(db, interviewer_user_id=owner.id, message="Hire a backend engineer")
    assert result["outcome"] == "failure" and "unknown knowledge source" in result["assistant_message"]
    assert model.generate_calls == [] and count(db, RequirementProfile) == 0


def test_embedding_outage_is_not_reported_as_a_missing_role(setup):
    db, owner = setup
    model = FakeDirectModel()
    result = supervisor(model, FakeKnowledgeBase(error=RuntimeError("test outage"))).chat(db,
        interviewer_user_id=owner.id, message="Hire a backend engineer")
    assert result["outcome"] == "failure" and "could not be checked" in result["assistant_message"]
    assert model.plan_calls == model.generate_calls == [] and count(db, RequirementProfile) == 0


def test_failed_generation_leaves_no_profile_or_job_and_can_be_retried(setup):
    db, owner = setup
    model = FakeDirectModel([JobDraftPlan(role_title="Backend Engineer", relevant_chunk_ids=[41])] * 2,
        draft=RuntimeError("Synthetic model failure"))
    service = supervisor(model, routes=QueueToolModel(["generate_job_description"] * 2))
    first = service.chat(db, interviewer_user_id=owner.id, message="Hire a backend engineer")
    assert first["outcome"] == "failure" and count(db, RequirementProfile) == 0
    model.draft = grounded_draft()
    retry = service.chat(db, interviewer_user_id=owner.id, session_id=first["session_id"], message="Try again")
    assert retry["phase"] == "job_description_draft" and count(db, JobDescription) == 1


def test_profile_and_jd_save_is_atomic_when_insert_fails(setup):
    db, owner = setup
    def fail(*_):
        raise RuntimeError("Synthetic insert failure")
    event.listen(JobDescription, "before_insert", fail)
    try:
        result = supervisor(FakeDirectModel()).chat(db, interviewer_user_id=owner.id, message="Hire a backend engineer")
    finally:
        event.remove(JobDescription, "before_insert", fail)
    assert result["outcome"] == "failure"
    assert count(db, RequirementProfile) == count(db, JobDescription) == 0


@pytest.mark.parametrize("phase", ["requirements", "requirement_confirmation", "requirement_confirmed"])
def test_legacy_sessions_continue_directly_without_requirements_approval(setup, phase):
    db, owner = setup
    session = SupervisorSession(interviewer_user_id=owner.id, phase=phase,
        state_json={"messages": [{"role": "user", "content": "Hire a backend engineer"}],
            "requirement_state": {"profile": {"title": "Backend Engineer"}, "proposal_ready": True}})
    db.add(session); db.commit()
    result = supervisor(FakeDirectModel()).chat(db, interviewer_user_id=owner.id,
        session_id=session.id, message="Continue")
    assert result["phase"] == "job_description_draft"
    assert "requirement_state" not in db.get(SupervisorSession, session.id).state_json


def test_repeat_generation_does_not_duplicate_or_approve_a_draft(setup):
    db, owner = setup
    model = FakeDirectModel()
    service = supervisor(model, routes=QueueToolModel(["generate_job_description"] * 2))
    first = service.chat(db, interviewer_user_id=owner.id, message="Hire a backend engineer")
    second = service.chat(db, interviewer_user_id=owner.id, session_id=first["session_id"], message="Generate again")
    assert second["outcome"] == "failure" and count(db, JobDescription) == count(db, RequirementProfile) == 1
    assert len(model.generate_calls) == 1 and second["job_description"].status == JobDescriptionStatus.DRAFT


def test_session_ownership_is_enforced_before_knowledge_lookup(setup):
    db, owner = setup
    session = SupervisorSession(interviewer_user_id=owner.id, state_json={})
    db.add(session); db.commit()
    model = FakeDirectModel()
    with pytest.raises(PermissionError):
        supervisor(model).chat(db, interviewer_user_id=99999, session_id=session.id, message="Hire a backend engineer")
    assert model.plan_calls == []


def test_direct_result_is_not_rewritten_into_another_approval_step(setup):
    db, owner = setup
    routes = QueueToolModel(["generate_job_description"])
    routes.final_response = AIMessage(content="Please approve the requirements first.")
    result = supervisor(FakeDirectModel(), routes=routes).chat(db, interviewer_user_id=owner.id, message="Hire a backend engineer")
    assert "approve the requirements" not in result["assistant_message"]


def test_actual_offline_kb_search_feeds_direct_drafting_and_source_references(setup):
    db, owner = setup
    kb = KnowledgeBaseService()
    doc = kb.ingest_document(db, title="Backend Engineer", content=reference().content,
        source_type=KnowledgeSourceType.PREVIOUS_JOB_DESCRIPTION, created_by_user_id=owner.id)
    class SearchModel(FakeDirectModel):
        def plan(self, **kwargs):
            assert kwargs["evidence"][0].document_id == doc.id
            return JobDraftPlan(role_title="Backend Engineer", relevant_chunk_ids=[kwargs["evidence"][0].chunk_id])
    result = supervisor(SearchModel(), kb).chat(db, interviewer_user_id=owner.id, message="Backend Engineer Python APIs")
    assert result["job_description"].source_references[0]["document_id"] == doc.id


def test_gemini_prompt_and_schema_ground_both_decisions_without_real_model_calls():
    class Client:
        calls = []
        def generate_json(self, **kwargs):
            self.calls.append(kwargs)
            return (JobDraftPlan(role_title="Backend Engineer", relevant_chunk_ids=[41]).model_dump()
                    if len(self.calls) == 1 else grounded_draft().model_dump())
    client = Client()
    model = GeminiDirectJobDescriptionModel(client=client, model="synthetic")
    model.plan(messages=[{"role": "user", "content": "Hire a backend engineer"}], evidence=[reference()])
    model.generate(messages=[], role_title="Backend Engineer", evidence=[reference()])
    assert "untrusted" in client.calls[0]["system_instruction"]
    assert "NOT sufficient" in client.calls[0]["system_instruction"]
    assert "Do not invent" in client.calls[1]["system_instruction"]
    assert "min_years_experience" in client.calls[1]["schema"]["properties"]
