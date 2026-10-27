from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.job import JobDescriptionStatus
from app.schemas.requirements import RequirementItem


class JobDescriptionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_profile_id: int = Field(gt=0)
    title: str = Field(min_length=2, max_length=200)
    content: str = Field(min_length=1)
    structured_content: dict[str, Any] = Field(default_factory=dict)
    source_references: list[dict[str, Any]] = Field(default_factory=list)
    version: int = Field(default=1, ge=1)


class JobDescriptionResponse(JobDescriptionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: JobDescriptionStatus
    created_by_user_id: int | None
    created_at: datetime
    updated_at: datetime


class JobDescriptionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=2, max_length=200)
    summary: str = Field(min_length=1, max_length=10_000)
    responsibilities: list[str] = Field(min_length=1, max_length=30)
    required_skills: list[RequirementItem] = Field(default_factory=list)
    preferred_skills: list[RequirementItem] = Field(default_factory=list)
    qualifications: list[RequirementItem] = Field(default_factory=list)
    experience_requirement: str = Field(min_length=1, max_length=2000)
    selection_criteria: list[str] = Field(default_factory=list, max_length=20)


class JobDescriptionGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_profile_id: int = Field(gt=0)


class JobDescriptionManualCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=2, max_length=200)
    content: str = Field(min_length=1, max_length=50_000)
    required_skills: list[RequirementItem] = Field(min_length=1, max_length=50)
    preferred_skills: list[RequirementItem] = Field(default_factory=list, max_length=50)
    qualifications: list[RequirementItem] = Field(default_factory=list, max_length=50)
    min_years_experience: int | None = Field(default=None, ge=0, le=100, strict=True)

    @field_validator("title", "content", mode="before")
    @classmethod
    def trim_text(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class JobDescriptionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=2, max_length=200)
    content: str | None = Field(default=None, min_length=1)
    structured_content: JobDescriptionDraft | None = None
