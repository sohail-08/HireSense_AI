from datetime import date, datetime
from typing import Any, Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.job import JobPostingStatus


class DiscordPostPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_description_id: int = Field(gt=0)
    posting_id: int | None = Field(default=None, gt=0)
    heading: str | None = Field(default=None, max_length=2000)
    application_url: AnyHttpUrl | None = None
    contact_email: EmailStr | None = None
    location: str | None = Field(default=None, max_length=500)
    application_deadline: date | None = None
    additional_instructions: str | None = Field(
        default=None,
        max_length=1024,
    )

    @field_validator("heading", mode="before")
    @classmethod
    def normalize_heading(cls, value):
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("Heading cannot be empty")
        return value

    @field_validator(
        "application_url",
        "contact_email",
        "location",
        "additional_instructions",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class DiscordPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: Literal[True]


class DiscordPostingAssistantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_description_id: int = Field(gt=0)
    posting_id: int | None = Field(default=None, gt=0)
    message: str = Field(min_length=1, max_length=10_000)

    @field_validator("message", mode="before")
    @classmethod
    def normalize_message(cls, value):
        if isinstance(value, str):
            return value.strip()
        return value


class DiscordPostDefaultsResponse(BaseModel):
    heading: str
    application_url: str | None
    contact_email: EmailStr | None
    location: str | None
    application_deadline: date | None
    additional_instructions: str | None
    mcp_configured: bool


class DiscordJobPostResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_description_id: int
    platform: str
    heading: str | None
    application_url: str | None
    contact_email: str | None
    location: str | None
    application_deadline: date | None
    additional_instructions: str | None
    reviewed_content: str | None
    discord_payload: dict[str, Any] | None
    job_description_version: int | None
    status: JobPostingStatus
    external_post_id: str | None
    external_server_id: str | None
    external_channel_id: str | None
    external_url: str | None
    error_code: str | None
    error_message: str | None
    attempt_started_at: datetime | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DiscordPostingAssistantResponse(BaseModel):
    status: Literal[
        "awaiting_details",
        "awaiting_approval",
        "awaiting_changes",
        "published",
    ]
    assistant_message: str
    missing_fields: list[Literal["application_url", "application_deadline"]]
    posting: DiscordJobPostResponse | None = None
