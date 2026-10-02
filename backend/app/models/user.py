from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SqlEnum,
    Index,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserRole(str, Enum):
    INTERVIEWER = "interviewer"
    CANDIDATE = "candidate"


class User(Base):
    __tablename__ = "users"

    __table_args__ = (
        Index(
            "uq_single_interviewer",
            "role",
            unique=True,
            postgresql_where=text("role = 'interviewer'"),
            sqlite_where=text("role = 'interviewer'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str] = mapped_column(String(100))

    email: Mapped[str] = mapped_column(
        String(254),
        unique=True,
        index=True,
    )

    password_hash: Mapped[str] = mapped_column(String(255))

    role: Mapped[UserRole] = mapped_column(
        SqlEnum(
            UserRole,
            native_enum=False,
            create_constraint=True,
            values_callable=lambda roles: [
                role.value for role in roles
            ],
        ),
        default=UserRole.CANDIDATE,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )