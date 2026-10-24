"""Private, interview-scoped practical exercises. Submitted attempts are immutable."""
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


def now():
    return datetime.now(timezone.utc)


class WorkSampleTemplate(Base):
    __tablename__ = "work_sample_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    task: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WorkSampleExercise(Base):
    __tablename__ = "work_sample_exercises"
    id: Mapped[int] = mapped_column(primary_key=True)
    interview_id: Mapped[int] = mapped_column(ForeignKey("interview_schedules.id", ondelete="CASCADE"), unique=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("candidate_applications.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    task: Mapped[dict] = mapped_column(JSON)
    task_hash: Mapped[str] = mapped_column(String(64))
    grading_policy: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30), default="draft")
    version: Mapped[int] = mapped_column(Integer, default=1)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    events: Mapped[list] = mapped_column(JSON, default=list)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WorkSampleAttempt(Base):
    __tablename__ = "work_sample_attempts"
    __table_args__ = (UniqueConstraint("exercise_id", "number", name="uq_work_sample_attempt_number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("work_sample_exercises.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="ready")
    content: Mapped[str] = mapped_column(Text, default="")
    explanation: Mapped[str] = mapped_column(Text, default="")
    revision: Mapped[int] = mapped_column(Integer, default=0)
    remaining_seconds: Mapped[int] = mapped_column(Integer)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submission_hash: Mapped[str | None] = mapped_column(String(64))


class WorkSampleAssessment(Base):
    __tablename__ = "work_sample_assessments"
    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("work_sample_attempts.id", ondelete="CASCADE"), unique=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    snapshot: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    approved_result: Mapped[dict | None] = mapped_column(JSON)
    review_reason: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WorkSampleDecision(Base):
    """One immutable human decision; legacy AI reviews stay untouched."""
    __tablename__ = "work_sample_decisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("work_sample_exercises.id", ondelete="CASCADE"), unique=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("work_sample_attempts.id", ondelete="CASCADE"), unique=True)
    submission_hash: Mapped[str] = mapped_column(String(64))
    correct: Mapped[bool] = mapped_column(Boolean)
    note: Mapped[str] = mapped_column(Text, default="")
    decided_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
