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
