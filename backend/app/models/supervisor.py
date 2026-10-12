from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SupervisorSession(Base):
    __tablename__ = "supervisor_sessions"
    __table_args__ = (
        Index("ix_supervisor_sessions_interviewer_user_id", "interviewer_user_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    interviewer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    requirement_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("requirement_discovery_sessions.id"),
        nullable=True,
    )
    requirement_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("requirement_profiles.id"),
        nullable=True,
    )
    job_description_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_descriptions.id"),
        nullable=True,
    )
    job_posting_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_postings.id"),
        nullable=True,
    )
    phase: Mapped[str] = mapped_column(String(50), default="requirements")
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
