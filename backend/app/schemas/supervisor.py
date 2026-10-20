from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.job import JobDescriptionResponse
from app.schemas.job_posting import DiscordJobPostResponse
from app.schemas.requirements import RequirementProfileDraft
from app.schemas.candidate import GoogleFormsSyncResponse
from app.schemas.screening import ScreeningBatchResponse


SupervisorPhase = Literal[
    "requirements",
    "requirement_confirmation",
    "requirement_confirmed",
    "job_description_draft",
    "job_description_approved",
    "posting_details",
    "posting_approval",
    "published",
    "error",
    "interview_selection", "interview_schedule", "interview_approval", "interview_sent", "interview_reschedule",
]


class SupervisorMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=200_000)
    outcome: Literal["info", "success", "failure"] = "info"


class SupervisorRequirementState(BaseModel):
    profile: RequirementProfileDraft = Field(
        default_factory=RequirementProfileDraft,
    )
    missing_fields: list[str] = Field(default_factory=list)
    knowledge_status: Literal["not_searched", "found", "empty", "error"] = (
        "not_searched"
    )
    proposal_ready: bool = False
    source_references: list[dict[str, Any]] = Field(default_factory=list)


class SupervisorChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str | None = Field(default=None, min_length=1, max_length=36)
    message: str = Field(min_length=1, max_length=10_000)
    selected_job_description_id: int | None = Field(default=None, gt=0)
    page_context: Literal["jobs", "candidates", "assessments", "interviews", "other"] = "jobs"
    selected_job_posting_id: int | None = Field(default=None, gt=0)
    selected_application_ids: list[int] = Field(default_factory=list, max_length=50)

    @field_validator("message", mode="before")
    @classmethod
    def normalize_message(cls, value):
        return value.strip() if isinstance(value, str) else value


class SupervisorChatResponse(BaseModel):
    session_id: str
    phase: SupervisorPhase
    route: str
    assistant_message: str
    outcome: Literal["info", "success", "failure"]
    messages: list[SupervisorMessage]
    requirement_profile_id: int | None = None
    requirement_state: SupervisorRequirementState
    job_description: JobDescriptionResponse | None = None
    job_posting: DiscordJobPostResponse | None = None
    refresh_required: bool = False
    sync_result: GoogleFormsSyncResponse | None = None
    screening_batch: ScreeningBatchResponse | None = None
    interview_batch_id: int | None = None
    assessment_links: list[dict[str, str]] = Field(default_factory=list)
