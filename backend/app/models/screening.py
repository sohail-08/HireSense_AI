from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _values(enum_type: type[Enum]) -> list[str]:
    return [item.value for item in enum_type]


class ScreeningBatchStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"


class ScreeningRunStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    REVIEW_REQUIRED = "review_required"
    FAILED = "failed"


class RequirementMatchStatus(str, Enum):
    MET = "met"
    PARTIALLY_MET = "partially_met"
    UNMET = "unmet"
    UNABLE_TO_DETERMINE = "unable_to_determine"


class RankingDisposition(str, Enum):
    RANKED = "ranked"
    REVIEW = "review"


class ScreeningBatch(Base):
    __tablename__ = "screening_batches"
    __table_args__ = (
        Index("ix_screening_batches_job_posting_id", "job_posting_id"),
        Index("ix_screening_batches_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_posting_id: Mapped[int] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE")
    )
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    status: Mapped[ScreeningBatchStatus] = mapped_column(
        SqlEnum(
            ScreeningBatchStatus,
            native_enum=False,
            create_constraint=True,
            values_callable=_values,
        ),
        default=ScreeningBatchStatus.QUEUED,
    )
    application_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    total_applications: Mapped[int] = mapped_column(Integer, default=0)
    processed_applications: Mapped[int] = mapped_column(Integer, default=0)
    successful_applications: Mapped[int] = mapped_column(Integer, default=0)
    review_applications: Mapped[int] = mapped_column(Integer, default=0)
    failed_applications: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ScreeningRun(Base):
    __tablename__ = "screening_runs"
    __table_args__ = (
        Index("ix_screening_runs_application_id", "application_id"),
        Index("ix_screening_runs_job_posting_id", "job_posting_id"),
        Index("ix_screening_runs_status", "status"),
        Index(
            "ix_screening_runs_compatibility",
            "application_id",
            "cv_sha256",
            "requirement_snapshot_hash",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_applications.id", ondelete="CASCADE")
    )
    cv_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("cv_documents.id", ondelete="SET NULL"), nullable=True
    )
    job_posting_id: Mapped[int] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE")
    )
    requirement_profile_id: Mapped[int] = mapped_column(
        ForeignKey("requirement_profiles.id", ondelete="CASCADE")
    )
    status: Mapped[ScreeningRunStatus] = mapped_column(
        SqlEnum(
            ScreeningRunStatus,
            native_enum=False,
            create_constraint=True,
            values_callable=_values,
        ),
        default=ScreeningRunStatus.QUEUED,
    )
    cv_sha256: Mapped[str] = mapped_column(String(64))
    input_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    processing_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    requirement_snapshot_hash: Mapped[str] = mapped_column(String(64))
    requirement_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    extracted_profile: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    suitability_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    strengths: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    gaps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    points_to_verify: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list
    )
    requirement_coverage: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    met_count: Mapped[int] = mapped_column(Integer, default=0)
    partially_met_count: Mapped[int] = mapped_column(Integer, default=0)
    unmet_count: Mapped[int] = mapped_column(Integer, default=0)
    uncertain_count: Mapped[int] = mapped_column(Integer, default=0)
    review_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(50), default="v1")
    calculation_version: Mapped[str] = mapped_column(String(50), default="v1")
    reused_from_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("screening_runs.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ScreeningBatchItem(Base):
    __tablename__ = "screening_batch_items"
    __table_args__ = (
        Index(
            "uq_screening_batch_items_batch_application",
            "batch_id",
            "application_id",
            unique=True,
        ),
        Index("ix_screening_batch_items_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("screening_batches.id", ondelete="CASCADE")
    )
    application_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_applications.id", ondelete="CASCADE")
    )
    screening_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("screening_runs.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[ScreeningRunStatus] = mapped_column(
        SqlEnum(
            ScreeningRunStatus,
            native_enum=False,
            create_constraint=True,
            values_callable=_values,
        ),
        default=ScreeningRunStatus.QUEUED,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class RequirementMatch(Base):
    __tablename__ = "requirement_matches"
    __table_args__ = (
        Index("ix_requirement_matches_screening_run_id", "screening_run_id"),
        Index("ix_requirement_matches_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    screening_run_id: Mapped[int] = mapped_column(
        ForeignKey("screening_runs.id", ondelete="CASCADE")
    )
    requirement_key: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(500))
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    status: Mapped[RequirementMatchStatus] = mapped_column(
        SqlEnum(
            RequirementMatchStatus,
            native_enum=False,
            create_constraint=True,
            values_callable=_values,
        )
    )
    explanation: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    evidence_gaps: Mapped[list[str]] = mapped_column(JSON, default=list)
    review_flags: Mapped[list[str]] = mapped_column(JSON, default=list)


class RankingSnapshot(Base):
    __tablename__ = "ranking_snapshots"
    __table_args__ = (
        Index("ix_ranking_snapshots_job_posting_id", "job_posting_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_posting_id: Mapped[int] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE")
    )
    requirement_snapshot_hash: Mapped[str] = mapped_column(String(64))
    calculation_version: Mapped[str] = mapped_column(String(50), default="v1")
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class RankingEntry(Base):
    __tablename__ = "ranking_entries"
    __table_args__ = (
        Index("ix_ranking_entries_snapshot_id", "ranking_snapshot_id"),
        Index("ix_ranking_entries_application_id", "application_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ranking_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("ranking_snapshots.id", ondelete="CASCADE")
    )
    screening_run_id: Mapped[int] = mapped_column(
        ForeignKey("screening_runs.id", ondelete="CASCADE")
    )
    application_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_applications.id", ondelete="CASCADE")
    )
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disposition: Mapped[RankingDisposition] = mapped_column(
        SqlEnum(
            RankingDisposition,
            native_enum=False,
            create_constraint=True,
            values_callable=_values,
        )
    )
    requirement_coverage: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    met_count: Mapped[int] = mapped_column(Integer, default=0)
    partially_met_count: Mapped[int] = mapped_column(Integer, default=0)
    unmet_count: Mapped[int] = mapped_column(Integer, default=0)
    uncertain_count: Mapped[int] = mapped_column(Integer, default=0)
    suitability_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    strengths: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    gaps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    points_to_verify: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list
    )
