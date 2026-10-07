from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import Base
from app.integrations.google_workspace import GoogleDriveFile
from app.models import (
    ApplicationSource,
    Candidate,
    CandidateApplication,
    CVDocument,
    CVProcessingStatus,
    JobDescription,
    JobDescriptionStatus,
    JobPosting,
    JobPostingStatus,
    RequirementProfile,
    RequirementProfileStatus,
    User,
    UserRole,
)
from app.services.google_forms_intake_service import GoogleFormsIntakeService


class FakeGoogleReader:
    def read_sheet(self, *, spreadsheet_id: str, sheet_name: str):
        assert spreadsheet_id == "sheet-123"
        assert sheet_name == "Form Responses 1"
        return [
            [
                "Timestamp",
                "Full Name",
                "Email",
                "Phone Numer",
                "LinkedIn Profile",
                "Job Posting",
                "CV Upload",
            ],
            [
                "10/07/2026 09:15:00",
                "Ada Candidate",
                "ada@example.com",
                "+8801700000000",
                "https://linkedin.com/in/ada",
                "Backend Engineer",
                "https://drive.google.com/file/d/drive-file-12345/view",
            ],
        ]

    def get_file(self, file_id: str) -> GoogleDriveFile:
        assert file_id == "drive-file-12345"
        return GoogleDriveFile(
            id=file_id,
            name="Ada Candidate CV.pdf",
            mime_type="application/pdf",
            size=16,
        )

    def download_file(
        self,
        *,
        file_id: str,
        destination: Path,
        max_bytes: int,
    ) -> int:
        assert file_id == "drive-file-12345"
        assert max_bytes == 10 * 1024 * 1024
        content = b"synthetic cv pdf"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return len(content)


def _settings(storage_path: Path) -> Settings:
    return Settings(
        database_url="sqlite://",
        jwt_secret_key="test-jwt-secret-key-with-at-least-32-characters",
        interviewer_email="interviewer@example.com",
        interviewer_password="StrongInterviewerPassword123!",
        storage_root=str(storage_path),
        google_forms_spreadsheet_id="sheet-123",
        google_forms_sheet_name="Form Responses 1",
        google_forms_name_column="Full Name",
        google_forms_email_column="Email Address",
        google_forms_phone_column="Phone Number",
        google_forms_linkedin_column="LinkedIn Profile",
        google_forms_cv_column="Upload your CV",
    )


def test_google_forms_sync_is_idempotent_and_stores_cv(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'forms.db'}")
    Base.metadata.create_all(engine)
    service = GoogleFormsIntakeService(
        FakeGoogleReader(),
        _settings(tmp_path / "storage"),
    )

    with Session(engine) as db:
        interviewer = User(
            name="Interviewer",
            email="intake@example.com",
            password_hash="hashed-password",
            role=UserRole.INTERVIEWER,
        )
        db.add(interviewer)
        db.flush()
        profile = RequirementProfile(
            title="Backend Engineer",
            status=RequirementProfileStatus.CONFIRMED,
            created_by_user_id=interviewer.id,
        )
        db.add(profile)
        db.flush()
        job = JobDescription(
            requirement_profile_id=profile.id,
            title="Backend Engineer",
            content="Backend role",
            structured_content={},
            status=JobDescriptionStatus.APPROVED,
            created_by_user_id=interviewer.id,
        )
        db.add(job)
        db.flush()
        posting = JobPosting(
            job_description_id=job.id,
            platform="discord",
            status=JobPostingStatus.PUBLISHED,
        )
        db.add(posting)
        other_profile = RequirementProfile(
            title="Frontend Engineer",
            status=RequirementProfileStatus.CONFIRMED,
            created_by_user_id=interviewer.id,
        )
        db.add(other_profile)
        db.flush()
        other_job = JobDescription(
            requirement_profile_id=other_profile.id,
            title="Frontend Engineer",
            content="Frontend role",
            structured_content={},
            status=JobDescriptionStatus.APPROVED,
            created_by_user_id=interviewer.id,
        )
        db.add(other_job)
        db.flush()
        other_posting = JobPosting(
            job_description_id=other_job.id,
            platform="discord",
            status=JobPostingStatus.PUBLISHED,
        )
        db.add(other_posting)
        db.commit()

        first = service.sync(
            db,
            interviewer_user_id=interviewer.id,
        )
        assert first["imported_applications"] == 1
        assert first["downloaded_cvs"] == 1
        assert first["issues"] == []

        candidate = db.scalar(select(Candidate))
        assert candidate is not None
        assert candidate.name == "Ada Candidate"
        assert candidate.email == "ada@example.com"
        assert candidate.phone == "+8801700000000"
        application = db.scalar(select(CandidateApplication))
        assert application is not None
        assert application.job_posting_id == posting.id
        application.job_posting_id = other_posting.id
        db.commit()

        second = service.sync(
            db,
            interviewer_user_id=interviewer.id,
        )
        db.refresh(application)

        assert second["imported_applications"] == 0
        assert second["reassigned_applications"] == 1
        assert second["skipped_existing"] == 0
        assert application.job_posting_id == posting.id
        assert application.source is ApplicationSource.GOOGLE_FORM
        assert application.response_data["_google_import"]["row_number"] == 2
        document = db.scalar(select(CVDocument))
        assert document is not None
        assert document.status is CVProcessingStatus.VALIDATED
        stored = tmp_path / "storage" / document.storage_path
        assert stored.read_bytes() == b"synthetic cv pdf"


def test_job_resolution_never_guesses_between_postings(tmp_path):
    service = GoogleFormsIntakeService(
        FakeGoogleReader(),
        _settings(tmp_path / "storage"),
    )
    backend_posting = JobPosting(id=12, job_description_id=1)
    backend_job = JobDescription(id=1, title="Backend Engineer")
    duplicate_posting = JobPosting(id=13, job_description_id=2)
    duplicate_job = JobDescription(id=2, title="Backend Engineer")
    frontend_posting = JobPosting(id=14, job_description_id=3)
    frontend_job = JobDescription(id=3, title="Frontend Engineer")
    postings = [
        (backend_posting, backend_job),
        (duplicate_posting, duplicate_job),
        (frontend_posting, frontend_job),
    ]

    resolved, error = service._resolve_posting("Post #14", postings)
    assert resolved == (frontend_posting, frontend_job)
    assert error == ""

    resolved, error = service._resolve_posting("Backend Engineer", postings)
    assert resolved is None
    assert "ambiguous" in error

    resolved, error = service._resolve_posting("Unknown Role", postings)
    assert resolved is None
    assert "unknown job posting" in error
