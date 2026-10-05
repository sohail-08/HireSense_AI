from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import (
    RequirementDiscoveryStatus,
    RequirementProfile,
    User,
    UserRole,
)
from app.schemas.requirements import (
    RequirementExtraction,
    RequirementItem,
    RequirementProfileDraft,
)
from app.agents.requirement_discovery import RequirementDiscoveryGraph
from app.services.requirement_discovery_service import RequirementDiscoveryService


class FakeRequirementModel:
    def __init__(self, responses: list[RequirementExtraction]):
        self.responses = list(responses)

    def extract(self, *, messages, current_profile):  # noqa: ANN001
        return self.responses.pop(0)


def _complete_profile() -> RequirementProfileDraft:
    return RequirementProfileDraft(
        title="Backend Engineer",
        summary="Build reliable backend services.",
        required_skills=[RequirementItem(name="Python")],
        preferred_skills=[RequirementItem(name="AWS")],
        qualifications=[RequirementItem(name="Computer Science degree")],
        min_years_experience=3,
        selection_criteria=[RequirementItem(name="System design interview")],
    )


def test_requirement_graph_collects_requirements_and_confirmation():
    profile = _complete_profile()
    model = FakeRequirementModel(
        [
            RequirementExtraction(
                profile=RequirementProfileDraft(title="Backend Engineer"),
                missing_fields=[
                    "required_skills",
                    "qualifications",
                    "experience",
                    "selection_criteria",
                ],
                follow_up_question="Which skills and experience are required?",
            ),
            RequirementExtraction(profile=profile),
        ]
    )
    graph = RequirementDiscoveryGraph(model)

    first = graph.invoke("I want to hire a backend engineer")
    assert first["status"] == "active"
    assert first["missing_fields"] == [
        "required_skills",
        "qualifications",
        "experience",
        "selection_criteria",
    ]
    assert first["assistant_message"] == "Which skills and experience are required?"

    second = graph.invoke(
        "Python is required, AWS is preferred, 3 years, a CS degree, and a system design interview.",
        first,
    )
    assert second["status"] == "awaiting_confirmation"
    assert second["missing_fields"] == []
    assert second["profile"]["title"] == "Backend Engineer"

    confirmed = graph.invoke("confirm", second)
    assert confirmed["status"] == "confirmed"
    assert confirmed["confirmed"] is True


def test_requirement_discovery_service_persists_confirmed_profile(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'requirements.db'}")
    Base.metadata.create_all(engine)
    profile = _complete_profile()
    model = FakeRequirementModel(
        [
            RequirementExtraction(
                profile=profile,
                missing_fields=[],
            )
        ]
    )
    service = RequirementDiscoveryService(model)

    with Session(engine) as session:
        interviewer = User(
            name="Interviewer",
            email="requirements@example.com",
            password_hash="hashed-password",
            role=UserRole.INTERVIEWER,
        )
        session.add(interviewer)
        session.flush()

        discovery_session, result = service.chat(
            session,
            interviewer_user_id=interviewer.id,
            message="Backend engineer with Python, AWS preferred, 3 years, CS degree, and system design interview.",
        )

        assert result["status"] == "awaiting_confirmation"
        assert discovery_session.requirement_profile_id is None

        discovery_session, result = service.chat(
            session,
            interviewer_user_id=interviewer.id,
            session_id=discovery_session.id,
            message="confirm",
        )

        assert result["status"] == "confirmed"
        assert discovery_session.status is RequirementDiscoveryStatus.CONFIRMED
        assert discovery_session.requirement_profile_id is not None

        saved_profile = session.get(
            RequirementProfile,
            discovery_session.requirement_profile_id,
        )
        assert saved_profile is not None
        assert saved_profile.title == "Backend Engineer"
        assert saved_profile.min_years_experience == 3
        assert saved_profile.required_skills[0]["name"] == "Python"
