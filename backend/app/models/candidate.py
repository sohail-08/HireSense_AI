from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ApplicationSource(str, Enum):
    DIRECT_UPLOAD = "direct_upload"
    GOOGLE_FORM = "google_form"
    IMPORT = "import"


class ApplicationStatus(str, Enum):
    RECEIVED = "received"
    SCREENING = "screening"
    REVIEWED = "reviewed"
    SHORTLISTED = "shortlisted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class CVProcessingStatus(str, Enum):
    RECEIVED = "received"
    VALIDATED = "validated"
    PROCESSING = "processing"
    PROCESSED = "processed"
    REJECTED = "rejected"
    FAILED = "failed"


def _values(enum_type: type[Enum]) -> list[str]:
    return [item.value for item in enum_type]


class Candidate(Base):
    __tablename__ = "candidates"
    __table_args__ = (
        Index("ix_candidates_email", "email"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(
        String(2048), nullable=True
    )
    portfolio_url: Mapped[str | None] = mapped_column(
        String(2048), nullable=True
    )
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    applications: Mapped[list["CandidateApplication"]] = relationship(
        back_populates="candidate"
    )
    cv_documents: Mapped[list["CVDocument"]] = relationship(
        back_populates="candidate"
    )


class CandidateApplication(Base):
    __tablename__ = "candidate_applications"
    __table_args__ = (
        Index("ix_candidate_applications_job_posting_id", "job_posting_id"),
        Index("ix_candidate_applications_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_posting_id: Mapped[int] = mapped_column(
        ForeignKey("job_postings.id")
    )
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("candidates.id"), nullable=True
    )
    source: Mapped[ApplicationSource] = mapped_column(
        SqlEnum(
            ApplicationSource,
            native_enum=False,
            create_constraint=True,
            values_callable=_values,
        ),
        default=ApplicationSource.DIRECT_UPLOAD,
    )
    source_reference: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    status: Mapped[ApplicationStatus] = mapped_column(
        SqlEnum(
            ApplicationStatus,
            native_enum=False,
            create_constraint=True,
            values_callable=_values,
        ),
        default=ApplicationStatus.RECEIVED,
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    candidate: Mapped[Candidate | None] = relationship(
        back_populates="applications"
    )
    cv_documents: Mapped[list["CVDocument"]] = relationship(
        back_populates="application"
    )


class CVDocument(Base):
    __tablename__ = "cv_documents"
    __table_args__ = (
        Index("ix_cv_documents_application_id", "application_id"),
        Index("ix_cv_documents_status", "status"),
        Index("ix_cv_documents_sha256", "sha256"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("candidate_applications.id"), nullable=True
    )
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("candidates.id"), nullable=True
    )
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(2048))
    mime_type: Mapped[str] = mapped_column(String(100))
    file_size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    source: Mapped[ApplicationSource] = mapped_column(
        SqlEnum(
            ApplicationSource,
            native_enum=False,
            create_constraint=True,
            values_callable=_values,
        ),
        default=ApplicationSource.DIRECT_UPLOAD,
    )
    status: Mapped[CVProcessingStatus] = mapped_column(
        SqlEnum(
            CVProcessingStatus,
            native_enum=False,
            create_constraint=True,
            values_callable=_values,
        ),
        default=CVProcessingStatus.RECEIVED,
    )
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    extraction_warnings: Mapped[list[str]] = mapped_column(
        JSON, default=list
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    application: Mapped[CandidateApplication | None] = relationship(
        back_populates="cv_documents"
    )
    candidate: Mapped[Candidate | None] = relationship(
        back_populates="cv_documents"
    )
