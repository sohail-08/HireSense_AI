from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RequirementItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    details: str | None = Field(default=None, max_length=2000)

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class RequirementProfileDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)
    summary: str | None = Field(default=None, max_length=10_000)
    required_skills: list[RequirementItem] = Field(default_factory=list)
    preferred_skills: list[RequirementItem] = Field(default_factory=list)
    qualifications: list[RequirementItem] = Field(default_factory=list)
    min_years_experience: int | None = Field(default=None, ge=0, le=100)
    selection_criteria: list[RequirementItem] = Field(default_factory=list)


RequirementField = Literal[
    "title",
    "required_skills",
    "qualifications",
    "experience",
    "selection_criteria",
]


class RequirementExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: RequirementProfileDraft
    missing_fields: list[RequirementField] = Field(default_factory=list)
    follow_up_question: str | None = Field(default=None, max_length=2000)


class RequirementChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str | None = Field(default=None, min_length=1, max_length=36)
    message: str = Field(min_length=1, max_length=10_000)

    @field_validator("message", mode="before")
    @classmethod
    def trim_message(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class RequirementChatResponse(BaseModel):
    session_id: str
    status: str
    assistant_message: str
    profile: RequirementProfileDraft
    missing_fields: list[RequirementField]
    requirement_profile_id: int | None = None
    error: str | None = None


class OllamaMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class OllamaStructuredResponse(BaseModel):
    profile: RequirementProfileDraft
    missing_fields: list[RequirementField] = Field(default_factory=list)
    follow_up_question: str | None = None


def draft_to_storage(profile: RequirementProfileDraft) -> dict[str, Any]:
    return profile.model_dump(mode="json")
