"""Private, immutable report inputs/results and separately authored review notes."""
from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, UniqueConstraint, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

DATA = JSON().with_variant(JSONB(), "postgresql")


def now():
    return datetime.now(timezone.utc)


class AssessmentRun(Base):
    __tablename__ = "assessment_runs"
    __table_args__ = (UniqueConstraint("application_id", "version", name="uq_assessment_version"),
                      UniqueConstraint("application_id", "fingerprint", name="uq_assessment_input"))
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("candidate_applications.id", ondelete="CASCADE"), index=True)
    job_posting_id: Mapped[int] = mapped_column(ForeignKey("job_postings.id", ondelete="CASCADE"), index=True)
    version: Mapped[int]
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(60), default="queued")
    completeness: Mapped[str] = mapped_column(String(20), default="partial")
    snapshot: Mapped[dict] = mapped_column(DATA, default=dict)
    result: Mapped[dict] = mapped_column(DATA, default=dict)
    error: Mapped[str | None] = mapped_column(String(250))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AssessmentReview(Base):
    __tablename__ = "assessment_reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("assessment_runs.id", ondelete="CASCADE"), index=True)
    note: Mapped[str] = mapped_column(Text)
    reviewed: Mapped[bool] = mapped_column(default=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AssessmentComparison(Base):
    __tablename__ = "assessment_comparisons"
    __table_args__ = (UniqueConstraint("job_posting_id", "fingerprint", name="uq_assessment_comparison_input"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    job_posting_id: Mapped[int] = mapped_column(ForeignKey("job_postings.id", ondelete="CASCADE"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    assessment_ids: Mapped[list] = mapped_column(DATA)
    snapshot: Mapped[dict] = mapped_column(DATA)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReportArtifact(Base):
    __tablename__ = "report_artifacts"
    __table_args__ = (CheckConstraint("(assessment_id IS NULL) != (comparison_id IS NULL)", name="ck_report_one_target"),
                      UniqueConstraint("fingerprint", name="uq_report_artifact_input"))
    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int | None] = mapped_column(ForeignKey("assessment_runs.id", ondelete="CASCADE"), index=True)
    comparison_id: Mapped[int | None] = mapped_column(ForeignKey("assessment_comparisons.id", ondelete="CASCADE"), index=True)
    format: Mapped[str] = mapped_column(String(8))
    template_version: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict] = mapped_column(DATA)
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    storage_key: Mapped[str | None] = mapped_column(String(150))
    sha256: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(String(250))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
