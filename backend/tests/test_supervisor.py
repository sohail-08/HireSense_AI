from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agents.job_posting import PostingCommandExtraction
from app.agents.supervisor import SupervisorDecision
from app.database import Base
from app.integrations.discord_mcp import DiscordPublishResult
from app.models import JobPostingStatus, SupervisorSession, User, UserRole
from app.schemas.job import JobDescriptionDraft
from app.schemas.requirements import (
    RequirementExtraction,
    RequirementItem,
    RequirementProfileDraft,
)
from app.schemas.supervisor import SupervisorChatResponse
from app.services.job_description_service import JobDescriptionService
from app.services.job_posting_assistant_service import JobPostingAssistantService
from app.services.job_posting_service import DiscordJobPostingService
from app.services.requirement_discovery_service import RequirementDiscoveryService
from app.services.supervisor_service import SupervisorService


class QueueRouter:
    def __init__(self, actions):
        self.actions = list(actions)

    def route(self, **_kwargs):
        return SupervisorDecision(
            action=self.actions.pop(0),
            reason="Test route",
        )


class QueueRequirementModel:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)

    def extract(self, **_kwargs):
        return self.outcomes.pop(0)


class StaticJobDescriptionModel:
    def __init__(self, draft):
        self.draft = draft

    def generate(self, **_kwargs):
        return self.draft


class StaticJobEditModel:
    def __init__(self, draft):
        self.draft = draft

    def edit(self, **_kwargs):
        return self.draft


class QueuePostingCommandModel:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)

    def extract(self, **_kwargs):
        return self.outcomes.pop(0)


class EmptyKnowledgeBase:
    def search(self, *_args, **_kwargs):
        return []


class StubPublisher:
    def __init__(self):
        self.calls = []

    def publish(self, payload):
        self.calls.append(payload)
        return DiscordPublishResult("333", "222", "111")


def _requirement_profile():
    return RequirementProfileDraft(
        title="Backend Engineer",
        summary="Build reliable backend services.",
        required_skills=[RequirementItem(name="Python")],
        preferred_skills=[RequirementItem(name="AWS")],
        qualifications=[RequirementItem(name="Computer Science degree")],
        min_years_experience=3,
        selection_criteria=[RequirementItem(name="System design interview")],
    )


def _job_draft(title="Backend Engineer"):
    return JobDescriptionDraft(
        title=title,
        summary="Build reliable backend services.",
        responsibilities=["Build and test APIs"],
        required_skills=[RequirementItem(name="Python")],
        preferred_skills=[RequirementItem(name="AWS")],
        qualifications=[RequirementItem(name="Computer Science degree")],
        experience_requirement="At least 3 years of backend experience.",
        selection_criteria=["System design interview"],
    )


def test_supervisor_coordinates_complete_hiring_workflow(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'supervisor.db'}")
    Base.metadata.create_all(engine)
    deadline = date.today() + timedelta(days=14)
    publisher = StubPublisher()
    router = QueueRouter(
        [
            "requirements",
            "requirements",
            "generate_job_description",
            "edit_job_description",
            "approve_job_description",
            "job_posting",
            "job_posting",
            "job_posting",
        ]
    )
    requirement_service = RequirementDiscoveryService(
        QueueRequirementModel(
            [RequirementExtraction(profile=_requirement_profile())]
        ),
        EmptyKnowledgeBase(),
    )
    job_service = JobDescriptionService(
        StaticJobDescriptionModel(_job_draft()),
        EmptyKnowledgeBase(),
    )
    posting_service = JobPostingAssistantService(
        QueuePostingCommandModel(
            [
                PostingCommandExtraction(action="start"),
                PostingCommandExtraction(
                    action="provide_details",
                    application_url="https://forms.example.com/apply",
                    application_deadline=deadline,
                ),
                PostingCommandExtraction(action="approve"),
            ]
        ),
        DiscordJobPostingService(publisher=publisher),
    )
    service = SupervisorService(
        router=router,
        requirement_service=requirement_service,
        job_description_service=job_service,
        job_edit_model=StaticJobEditModel(
            _job_draft("Senior Backend Engineer")
        ),
        job_posting_service=posting_service,
    )

    with Session(engine) as db:
        interviewer = User(
            name="Interviewer",
            email="supervisor@example.com",
            password_hash="hashed-password",
            role=UserRole.INTERVIEWER,
        )
        db.add(interviewer)
        db.commit()

        first = service.chat(
            db,
            interviewer_user_id=interviewer.id,
            message="I want to hire a backend engineer",
        )
        session_id = first["session_id"]
        assert first["phase"] == "requirement_confirmation"
        assert first["requirement_profile_id"] is None

        confirmed = service.chat(
            db,
            interviewer_user_id=interviewer.id,
            session_id=session_id,
            message="Confirm the requirements",
        )
        assert confirmed["phase"] == "requirement_confirmed", confirmed[
            "assistant_message"
        ]
        assert confirmed["requirement_profile_id"] is not None

        generated = service.chat(
            db,
            interviewer_user_id=interviewer.id,
            session_id=session_id,
            message="Generate the job description",
        )
        assert generated["phase"] == "job_description_draft"
        assert generated["outcome"] == "success"
        assert generated["job_description"].title == "Backend Engineer"

        edited = service.chat(
            db,
            interviewer_user_id=interviewer.id,
            session_id=session_id,
            message="Change the title to Senior Backend Engineer",
        )
        assert edited["job_description"].title == "Senior Backend Engineer"

        approved = service.chat(
            db,
            interviewer_user_id=interviewer.id,
            session_id=session_id,
            message="Approve the job description",
        )
        assert approved["phase"] == "job_description_approved"
        assert approved["outcome"] == "success"

        posting_started = service.chat(
            db,
            interviewer_user_id=interviewer.id,
            session_id=session_id,
            message="Post this job to Discord",
        )
        assert posting_started["phase"] == "posting_details"

        preview = service.chat(
            db,
            interviewer_user_id=interviewer.id,
            session_id=session_id,
            message=(
                "Use https://forms.example.com/apply and deadline "
                f"{deadline.isoformat()}"
            ),
        )
        assert preview["phase"] == "posting_approval"
        assert preview["job_posting"].status is JobPostingStatus.DRAFT
        assert publisher.calls == []

        published = service.chat(
            db,
            interviewer_user_id=interviewer.id,
            session_id=session_id,
            message="Approve the post",
        )
        validated = SupervisorChatResponse.model_validate(published)
        assert validated.phase == "published"
        assert validated.outcome == "success"
        assert validated.job_posting.status is JobPostingStatus.PUBLISHED
        assert len(publisher.calls) == 1

        saved = db.get(SupervisorSession, session_id)
        assert saved.requirement_profile_id == confirmed["requirement_profile_id"]
        assert saved.job_description_id == edited["job_description"].id
        assert saved.job_posting_id == validated.job_posting.id
        assert len(saved.state_json["messages"]) == 16

        restored = service.get_session(
            db,
            interviewer_user_id=interviewer.id,
            session_id=session_id,
        )
        assert restored["phase"] == "published"
        assert len(restored["messages"]) == 16

        outsider = User(
            name="Other user",
            email="other-supervisor@example.com",
            password_hash="hashed-password",
            role=UserRole.CANDIDATE,
        )
        db.add(outsider)
        db.commit()
        with pytest.raises(LookupError):
            service.get_session(
                db,
                interviewer_user_id=outsider.id,
                session_id=session_id,
            )
    engine.dispose()
