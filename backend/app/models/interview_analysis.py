"""Immutable analysis snapshots; separate from candidate screening/ranking."""
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

DATA = JSON().with_variant(JSONB(), "postgresql")


def now():
    return datetime.now(timezone.utc)


class InterviewAnalysisControl(Base):
    __tablename__ = "interview_analysis_controls"
    interview_id: Mapped[int] = mapped_column(ForeignKey("interview_schedules.id", ondelete="CASCADE"), primary_key=True)
    automatic: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    references: Mapped[list] = mapped_column(DATA, default=list)
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class InterviewAnalysisRun(Base):
    __tablename__ = "interview_analysis_runs"
    __table_args__ = (UniqueConstraint("interview_id", "version", name="uq_interview_analysis_version"),
                     UniqueConstraint("interview_id", "fingerprint", name="uq_interview_analysis_input"))
    id: Mapped[int] = mapped_column(primary_key=True)
    interview_id: Mapped[int] = mapped_column(ForeignKey("interview_schedules.id", ondelete="CASCADE"), index=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("candidate_applications.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(60), default="queued")
    error: Mapped[str | None] = mapped_column(String(200))
    snapshot: Mapped[dict] = mapped_column(DATA)
    result: Mapped[dict] = mapped_column(DATA, default=dict)
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InterviewAnalysisReview(Base):
    __tablename__ = "interview_analysis_reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    interview_id: Mapped[int] = mapped_column(ForeignKey("interview_schedules.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("interview_analysis_runs.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(DATA)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
