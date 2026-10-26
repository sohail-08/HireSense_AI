"""Application-scoped encrypted biometric references; never scoring inputs."""
from datetime import datetime, timezone
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class FaceReference(Base):
    __tablename__ = "candidate_face_references"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("candidate_applications.id", ondelete="CASCADE"), unique=True)
    status: Mapped[str] = mapped_column(String(30))
    consent: Mapped[str] = mapped_column(String(20))
    notice_version: Mapped[str] = mapped_column(String(40))
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_hash: Mapped[str] = mapped_column(String(64))
    generation: Mapped[str] = mapped_column(String(32))
    photo_cipher: Mapped[str | None] = mapped_column(Text)
    embedding_cipher: Mapped[str | None] = mapped_column(Text)
    model_version: Mapped[str | None] = mapped_column(String(160))
    error: Mapped[str | None] = mapped_column(String(80))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class IdentityCheck(Base):
    __tablename__ = "candidate_identity_checks"
    id: Mapped[int] = mapped_column(primary_key=True)
    interview_id: Mapped[int] = mapped_column(ForeignKey("interview_schedules.id", ondelete="CASCADE"), unique=True)
    reference_generation: Mapped[str | None] = mapped_column(String(32))
    join_generation: Mapped[int] = mapped_column(Integer)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("candidate_interview_sessions.id", ondelete="SET NULL"))
    live_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notice_version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), default="not_checked")
    reason: Mapped[str] = mapped_column(String(80), default="not_checked")
    similarity: Mapped[float | None] = mapped_column(Float)
    threshold: Mapped[float | None] = mapped_column(Float)
    model_version: Mapped[str | None] = mapped_column(String(160))
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    capture_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    manual_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    manual_note: Mapped[str | None] = mapped_column(String(500))
    version: Mapped[int] = mapped_column(Integer, default=0)
