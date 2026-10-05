from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, JSON, String
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RequirementDiscoveryStatus(str, Enum):
    ACTIVE = "active"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    CONFIRMED = "confirmed"
    ERROR = "error"


def _values(enum_type: type[Enum]) -> list[str]:
    return [item.value for item in enum_type]


class RequirementDiscoverySession(Base):
    __tablename__ = "requirement_discovery_sessions"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    interviewer_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id")
    )
    requirement_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("requirement_profiles.id"), nullable=True
    )
    status: Mapped[RequirementDiscoveryStatus] = mapped_column(
        SqlEnum(
            RequirementDiscoveryStatus,
            native_enum=False,
            create_constraint=True,
            values_callable=_values,
        ),
        default=RequirementDiscoveryStatus.ACTIVE,
    )
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
