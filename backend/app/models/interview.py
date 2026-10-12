from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, Index, text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class InterviewBatch(Base):
    __tablename__ = "interview_batches"
    __table_args__ = (UniqueConstraint("created_by_user_id", "idempotency_key", name="uq_interview_batch_request"),
                      UniqueConstraint("created_by_user_id", "confirmation_hash", name="uq_interview_confirmation"))
    id: Mapped[int] = mapped_column(primary_key=True)
    job_posting_id: Mapped[int] = mapped_column(ForeignKey("job_postings.id", ondelete="CASCADE"), index=True)
    ranking_run_id: Mapped[int | None] = mapped_column(ForeignKey("scoring_runs.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(20), default="invitation")
    status: Mapped[str] = mapped_column(String(30), default="draft")
    snapshot: Mapped[dict] = mapped_column(JSON)
    confirmation_hash: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class InterviewSchedule(Base):
    __tablename__ = "interview_schedules"
    __table_args__ = (Index("uq_active_interview_stage", "application_id", "stage", unique=True,
        postgresql_where=text("status IN ('scheduled', 'rescheduled')"), sqlite_where=text("status IN ('scheduled', 'rescheduled')")),)
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("interview_batches.id", ondelete="CASCADE"))
    job_posting_id: Mapped[int] = mapped_column(ForeignKey("job_postings.id", ondelete="CASCADE"), index=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("candidate_applications.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(80))
    start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(100))
    local_start: Mapped[str] = mapped_column(String(40))
    duration_minutes: Mapped[int] = mapped_column(Integer)
    buffer_minutes: Mapped[int] = mapped_column(Integer, default=0)
    mode: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="scheduled")
    calendar_uid: Mapped[str] = mapped_column(String(200), unique=True)
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    meeting_url: Mapped[str | None] = mapped_column(String(2048))
    history: Mapped[list] = mapped_column(JSON, default=list)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class InterviewDelivery(Base):
    __tablename__ = "interview_deliveries"
    __table_args__ = (UniqueConstraint("schedule_id", "sequence", name="uq_interview_delivery_sequence"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("interview_batches.id", ondelete="CASCADE"), index=True)
    schedule_id: Mapped[int] = mapped_column(ForeignKey("interview_schedules.id", ondelete="CASCADE"))
    application_id: Mapped[int] = mapped_column(ForeignKey("candidate_applications.id", ondelete="CASCADE"))
    recipient_email: Mapped[str] = mapped_column(String(254))
    template_version: Mapped[str] = mapped_column(String(40), default="interview-v1")
    subject: Mapped[str] = mapped_column(String(250))
    body: Mapped[str] = mapped_column(Text)
    calendar_text: Mapped[str] = mapped_column(Text)
    calendar_checksum: Mapped[str] = mapped_column(String(64))
    sequence: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    in_flight: Mapped[bool] = mapped_column(Boolean, default=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_category: Mapped[str | None] = mapped_column(String(80))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
