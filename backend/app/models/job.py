from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RequirementProfileStatus(str, Enum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    ARCHIVED = "archived"


class JobDescriptionStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    ARCHIVED = "archived"


class JobPostingStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    CLOSED = "closed"
    FAILED = "failed"


def _values(enum_type: type[Enum]) -> list[str]:
    return [item.value for item in enum_type]


class RequirementProfile(Base):
    __tablename__ = "requirement_profiles"
    __table_args__ = (
        Index("ix_requirement_profiles_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    required_skills: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list
    )
    preferred_skills: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list
    )
    qualifications: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list
    )
    min_years_experience: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    selection_criteria: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list
    )
    status: Mapped[RequirementProfileStatus] = mapped_column(
        SqlEnum(
            RequirementProfileStatus,
            native_enum=False,
            create_constraint=True,
            values_callable=_values,
        ),
        default=RequirementProfileStatus.DRAFT,
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    job_descriptions: Mapped[list["JobDescription"]] = relationship(
        back_populates="requirement_profile"
    )


class JobDescription(Base):
    __tablename__ = "job_descriptions"
    __table_args__ = (
        Index("ix_job_descriptions_requirement_profile_id", "requirement_profile_id"),
        Index("ix_job_descriptions_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    requirement_profile_id: Mapped[int] = mapped_column(
        ForeignKey("requirement_profiles.id")
    )
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    structured_content: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict
    )
    source_references: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[JobDescriptionStatus] = mapped_column(
        SqlEnum(
            JobDescriptionStatus,
            native_enum=False,
            create_constraint=True,
            values_callable=_values,
        ),
        default=JobDescriptionStatus.DRAFT,
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    requirement_profile: Mapped[RequirementProfile] = relationship(
        back_populates="job_descriptions"
    )
    postings: Mapped[list["JobPosting"]] = relationship(
        back_populates="job_description"
    )


class JobPosting(Base):
    __tablename__ = "job_postings"
    __table_args__ = (
        Index("ix_job_postings_status", "status"),
        Index("ix_job_postings_platform", "platform"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_description_id: Mapped[int] = mapped_column(
        ForeignKey("job_descriptions.id")
    )
    platform: Mapped[str] = mapped_column(String(100), default="manual")
    application_url: Mapped[str | None] = mapped_column(
        String(2048), nullable=True
    )
    external_post_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    external_url: Mapped[str | None] = mapped_column(
        String(2048), nullable=True
    )
    status: Mapped[JobPostingStatus] = mapped_column(
        SqlEnum(
            JobPostingStatus,
            native_enum=False,
            create_constraint=True,
            values_callable=_values,
        ),
        default=JobPostingStatus.DRAFT,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    job_description: Mapped[JobDescription] = relationship(
        back_populates="postings"
    )
