import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agents.job_description import render_job_description
from app.database import Base
from app.models import (
    JobDescription,
    JobDescriptionStatus,
    JobPosting,
    JobPostingStatus,
    KnowledgeSourceType,
    RequirementProfile,
    RequirementProfileStatus,
    SupervisorSession,
    User,
    UserRole,
)
from app.rag.service import RetrievedKnowledgeChunk
from app.schemas.job import JobDescriptionDraft, JobDescriptionUpdateRequest
from app.schemas.requirements import RequirementItem
from app.services.job_description_service import JobDescriptionService


class FakeJobDescriptionModel:
    def __init__(self, draft: JobDescriptionDraft):
        self.draft = draft
        self.evidence_seen: list[RetrievedKnowledgeChunk] = []

    def generate(self, *, profile, evidence):  # noqa: ANN001
        self.evidence_seen = evidence
        return self.draft


def _draft() -> JobDescriptionDraft:
    return JobDescriptionDraft(
        title="Backend Engineer",
        summary="Build reliable backend services.",
        responsibilities=["Build and test backend APIs"],
        required_skills=[RequirementItem(name="Python")],
        preferred_skills=[RequirementItem(name="AWS")],
        qualifications=[RequirementItem(name="Computer Science degree")],
        experience_requirement="At least 3 years of backend experience.",
        selection_criteria=["System design interview"],
    )


def test_render_job_description_contains_structured_sections():
    rendered = render_job_description(_draft())

    assert "# Backend Engineer" in rendered
    assert "## Responsibilities" in rendered
    assert "## Required Skills" in rendered
    assert "- Python" in rendered
    assert "## Selection Process" in rendered


def test_job_description_generation_retrieves_evidence_and_supports_review(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'job-description.db'}")
    Base.metadata.create_all(engine)
    model = FakeJobDescriptionModel(_draft())
    service = JobDescriptionService(model)

    with Session(engine) as session:
        interviewer = User(
            name="Interviewer",
            email="jd@example.com",
            password_hash="hashed-password",
            role=UserRole.INTERVIEWER,
        )
        session.add(interviewer)
        session.flush()

        profile = RequirementProfile(
            title="Backend Engineer",
            summary="Build reliable backend services.",
            required_skills=[{"name": "Python"}],
            preferred_skills=[{"name": "AWS"}],
            qualifications=[{"name": "Computer Science degree"}],
            min_years_experience=3,
            selection_criteria=[{"name": "System design interview"}],
            status=RequirementProfileStatus.CONFIRMED,
            created_by_user_id=interviewer.id,
        )
        session.add(profile)
        session.flush()

        from app.rag.service import KnowledgeBaseService

        KnowledgeBaseService().ingest_document(
            session,
            title="Backend Engineer JD 2025",
            content="Backend roles require Python API development and testing.",
            source_type=KnowledgeSourceType.PREVIOUS_JOB_DESCRIPTION,
            created_by_user_id=interviewer.id,
        )

        job_description = service.generate(
            session,
            requirement_profile_id=profile.id,
            interviewer_user_id=interviewer.id,
        )

        assert job_description.status is JobDescriptionStatus.DRAFT
        assert job_description.version == 1
        assert job_description.source_references
        assert model.evidence_seen[0].document_title == "Backend Engineer JD 2025"

        updated = service.update_draft(
            session,
            job_description_id=job_description.id,
            interviewer_user_id=interviewer.id,
            update=JobDescriptionUpdateRequest(
                structured_content=JobDescriptionDraft(
                    **{
                        **_draft().model_dump(),
                        "title": "Senior Backend Engineer",
                    }
                )
            ),
        )
        assert updated.title == "Senior Backend Engineer"

        approved = service.approve(
            session,
            job_description_id=job_description.id,
            interviewer_user_id=interviewer.id,
        )
        assert approved.status is JobDescriptionStatus.APPROVED

        listed = service.list_for_interviewer(
            session,
            interviewer_user_id=interviewer.id,
        )
        assert [item.id for item in listed] == [approved.id]

        revision = service.revise(
            session,
            job_description_id=approved.id,
            interviewer_user_id=interviewer.id,
        )
        assert revision.status is JobDescriptionStatus.DRAFT
        assert revision.version == 2
        assert revision.content == approved.content

        service.delete(
            session,
            job_description_id=revision.id,
            interviewer_user_id=interviewer.id,
        )
        assert session.get(type(revision), revision.id) is None

        with pytest.raises(ValueError, match="Only draft"):
            service.approve(
                session,
                job_description_id=job_description.id,
                interviewer_user_id=interviewer.id,
            )


def test_unconfirmed_profile_cannot_generate_job_description(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'unconfirmed.db'}")
    Base.metadata.create_all(engine)
    service = JobDescriptionService(FakeJobDescriptionModel(_draft()))

    with Session(engine) as session:
        interviewer = User(
            name="Interviewer",
            email="unconfirmed@example.com",
            password_hash="hashed-password",
            role=UserRole.INTERVIEWER,
        )
        session.add(interviewer)
        session.flush()
        profile = RequirementProfile(
            title="Backend Engineer",
            status=RequirementProfileStatus.DRAFT,
            created_by_user_id=interviewer.id,
        )
        session.add(profile)
        session.flush()

        with pytest.raises(ValueError, match="must be confirmed"):
            service.generate(
                session,
                requirement_profile_id=profile.id,
                interviewer_user_id=interviewer.id,
            )


def test_delete_archives_posted_job_and_clears_supervisor_state(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'posted-delete.db'}")
    Base.metadata.create_all(engine)
    service = JobDescriptionService(FakeJobDescriptionModel(_draft()))

    with Session(engine) as session:
        interviewer = User(
            name="Interviewer",
            email="posted-delete@example.com",
            password_hash="hashed-password",
            role=UserRole.INTERVIEWER,
        )
        session.add(interviewer)
        session.flush()
        profile = RequirementProfile(
            title="Backend Engineer",
            status=RequirementProfileStatus.CONFIRMED,
            created_by_user_id=interviewer.id,
        )
        session.add(profile)
        session.flush()
        job = JobDescription(
            requirement_profile_id=profile.id,
            title="Backend Engineer",
            content="Backend engineer job description",
            structured_content=_draft().model_dump(mode="json"),
            status=JobDescriptionStatus.APPROVED,
            created_by_user_id=interviewer.id,
        )
        session.add(job)
        session.flush()
        posting = JobPosting(
            job_description_id=job.id,
            platform="discord",
            status=JobPostingStatus.PUBLISHED,
            external_post_id="discord-message-1",
        )
        session.add(posting)
        session.flush()
        supervisor = SupervisorSession(
            interviewer_user_id=interviewer.id,
            requirement_profile_id=profile.id,
            job_description_id=job.id,
            job_posting_id=posting.id,
            phase="published",
            state_json={"messages": []},
        )
        session.add(supervisor)
        session.commit()
        job_id = job.id
        posting_id = posting.id
        supervisor_id = supervisor.id

        service.delete(
            session,
            job_description_id=job_id,
            interviewer_user_id=interviewer.id,
        )

        archived = session.get(JobDescription, job_id)
        assert archived is not None
        assert archived.status is JobDescriptionStatus.ARCHIVED
        assert session.get(JobPosting, posting_id) is not None
        saved_supervisor = session.get(SupervisorSession, supervisor_id)
        assert saved_supervisor is not None
        assert saved_supervisor.job_description_id is None
        assert saved_supervisor.job_posting_id is None
        assert saved_supervisor.phase == "requirement_confirmed"
        assert service.list_for_interviewer(
            session,
            interviewer_user_id=interviewer.id,
        ) == []
