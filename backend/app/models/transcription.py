"""Text only. No audio, video, provider credentials or bearer tokens are persisted."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

STRUCTURED = JSON().with_variant(JSONB(), "postgresql")


def now():
    return datetime.now(timezone.utc)


class TranscriptionSession(Base):
    __tablename__ = "transcription_sessions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    interview_id: Mapped[int] = mapped_column(ForeignKey("interview_schedules.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(30), default="deepgram")
    model: Mapped[str] = mapped_column(String(40))
    language: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="starting")
    configuration: Mapped[dict] = mapped_column(STRUCTURED, default=dict)
    keyterms: Mapped[list] = mapped_column(STRUCTURED, default=list)
    started_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    stop_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    failure_code: Mapped[str | None] = mapped_column(String(60))
    connection_status: Mapped[str] = mapped_column(String(30), default="connecting")
    worker_identity: Mapped[str] = mapped_column(String(100))
    claim_hash: Mapped[str | None] = mapped_column(String(64))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_sequence: Mapped[int] = mapped_column(Integer, default=1)
    metrics: Mapped[dict] = mapped_column(STRUCTURED, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (Index("ix_transcription_interview_created", "interview_id", "created_at"),)


class TranscriptionConsent(Base):
    __tablename__ = "transcription_consents"
    id: Mapped[int] = mapped_column(primary_key=True)
    interview_id: Mapped[int] = mapped_column(ForeignKey("interview_schedules.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    participant_reference: Mapped[int] = mapped_column(Integer)
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    notice_version: Mapped[str] = mapped_column(String(40))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("interview_id", "role", name="uq_transcription_consent_role"),)


class TranscriptionStream(Base):
    __tablename__ = "transcription_streams"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("transcription_sessions.id", ondelete="CASCADE"), index=True)
    speaker: Mapped[str] = mapped_column(String(20))
    participant_reference: Mapped[int] = mapped_column(Integer)
    participant_identity: Mapped[str] = mapped_column(String(100))
    track_sid: Mapped[str] = mapped_column(String(100))
    start_offset_ms: Mapped[int] = mapped_column(Integer)
    last_end_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("transcription_sessions.id", ondelete="CASCADE"))
    interview_id: Mapped[int] = mapped_column(ForeignKey("interview_schedules.id", ondelete="CASCADE"))
    stream_id: Mapped[str] = mapped_column(ForeignKey("transcription_streams.id", ondelete="CASCADE"))
    speaker: Mapped[str] = mapped_column(String(20))
    participant_reference: Mapped[int] = mapped_column(Integer)
    participant_identity: Mapped[str] = mapped_column(String(100))
    track_sid: Mapped[str] = mapped_column(String(100))
    provider_request_id: Mapped[str] = mapped_column(String(100))
    provider_segment_id: Mapped[str] = mapped_column(String(100))
    sequence: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    start_offset_ms: Mapped[int] = mapped_column(Integer)
    end_offset_ms: Mapped[int] = mapped_column(Integer)
    stream_start_offset_ms: Mapped[int] = mapped_column(Integer)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[float | None]
    language: Mapped[str] = mapped_column(String(20))
    words: Mapped[list] = mapped_column(STRUCTURED, default=list)
    provider_timing: Mapped[dict] = mapped_column(STRUCTURED, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        UniqueConstraint("session_id", "sequence", name="uq_transcript_sequence"),
        UniqueConstraint("stream_id", "provider_segment_id", name="uq_transcript_provider_segment"),
        Index("ix_transcript_interview_time", "interview_id", "start_at", "sequence"),
        Index("ix_transcript_session_time", "session_id", "start_offset_ms"),
    )
