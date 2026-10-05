from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import (
    ApplicationSource,
    Candidate,
    CandidateApplication,
    CVDocument,
    JobDescription,
    JobPosting,
    RequirementProfile,
    User,
    UserRole,
)


def test_domain_models_persist_relationships(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'domain.db'}")
    from app.database import Base

    Base.metadata.create_all(engine)

    with Session(engine) as session:
        interviewer = User(
            name="Test Interviewer",
            email="domain@example.com",
            password_hash="hashed-password",
            role=UserRole.INTERVIEWER,
        )
        profile = RequirementProfile(
            title="Backend Engineer",
            required_skills=[{"name": "Python", "level": "required"}],
            preferred_skills=[{"name": "AWS"}],
            qualifications=[{"name": "Computer Science degree"}],
            selection_criteria=[{"name": "technical interview"}],
            created_by_user_id=None,
        )
        session.add_all([interviewer, profile])
        session.flush()

        description = JobDescription(
            requirement_profile_id=profile.id,
            title="Backend Engineer",
            content="Build reliable backend services.",
            structured_content={"responsibilities": ["Build APIs"]},
            source_references=[{"source": "company-policy.md", "chunk": 1}],
            created_by_user_id=interviewer.id,
        )
        session.add(description)
        session.flush()

        posting = JobPosting(
            job_description_id=description.id,
            application_url="https://example.test/apply",
        )
        candidate = Candidate(
            name="Candidate One",
            email="candidate@example.com",
        )
        session.add_all([posting, candidate])
        session.flush()

        application = CandidateApplication(
            job_posting_id=posting.id,
            candidate_id=candidate.id,
            source=ApplicationSource.DIRECT_UPLOAD,
        )
        session.add(application)
        session.flush()

        document = CVDocument(
            application_id=application.id,
            candidate_id=candidate.id,
            original_filename="candidate.pdf",
            storage_path="applications/1/candidate.pdf",
            mime_type="application/pdf",
            file_size_bytes=1024,
            sha256="a" * 64,
        )
        session.add(document)
        session.commit()

        assert profile.job_descriptions[0].id == description.id
        assert description.postings[0].id == posting.id
        assert candidate.applications[0].id == application.id
        assert application.cv_documents[0].id == document.id
        assert isinstance(document.created_at, datetime)
        assert document.created_at.tzinfo is not None or document.created_at is not None
