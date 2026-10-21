from datetime import date, time
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Boundary(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SelectionRequest(Boundary):
    job_posting_id: int = Field(gt=0)
    ranking_run_id: int | None = Field(default=None, gt=0)
    mode: Literal["top_n", "threshold", "manual"]
    top_n: int | None = Field(default=None, ge=1, le=100)
    threshold: Decimal | None = Field(default=None, ge=0, le=100)
    operator: Literal["gt", "gte"] = "gte"
    application_ids: list[int] = Field(default_factory=list, max_length=100)
    stage: str = Field(default="technical", min_length=1, max_length=80)

    @field_validator("stage")
    @classmethod
    def stage_name(cls, value):
        value = value.strip().casefold()
        if not value or "\n" in value or "\r" in value:
            raise ValueError("Provide an interview stage")
        return value


class ScheduleRequest(Boundary):
    date: date
    start_time: time
    timezone: str = Field(default="Asia/Dhaka", min_length=1, max_length=100)
    duration_minutes: int = Field(ge=5, le=480)
    mode: Literal["sequential"] = "sequential"
    buffer_minutes: int = Field(default=0, ge=0, le=240)
    instructions: str = Field(default="", max_length=4000)
    subject_template: str = Field(default="", max_length=250)
    body_template: str = Field(default="", max_length=10000)


class PrepareInvites(ScheduleRequest):
    selection_token: str = Field(min_length=10, max_length=50000)


class ConfirmInvites(Boundary):
    confirmed: Literal[True]
    confirmation_token: str = Field(min_length=10, max_length=2000000)
    idempotency_key: str = Field(min_length=1, max_length=128)


class RescheduleRequest(ScheduleRequest):
    schedule_ids: list[int] = Field(min_length=1, max_length=100)
    reason: str = Field(default="", max_length=1000)


class RetryDelivery(Boundary):
    confirmed: Literal[True]
    expected_attempts: int = Field(ge=1)


class CandidateReference(Boundary):
    application_id: int
    name: str
    masked_email: str | None
    email: str | None = None
    rank: int | None = None
    score: str | None = None
    reasons: list[str] = Field(default_factory=list)


class SelectionPreview(Boundary):
    job_posting_id: int
    job_title: str
    ranking_run_id: int
    selection_type: str
    stage: str
    selected: list[CandidateReference]
    excluded: list[CandidateReference]
    recipient_count: int
    tie_at_boundary: bool
    warnings: list[str]
    fingerprint: str
    selection_token: str


class SenderIdentity(Boundary):
    from_email: str
    from_name: str
    reply_to: str


class InvitationRecipient(CandidateReference):
    start_utc: str
    end_utc: str
    local_start: str
    local_end: str
    timezone: str
    duration_minutes: int
    buffer_minutes: int
    mode: Literal["shared", "sequential"]
    calendar_uid: str
    sequence: int
    subject: str
    body: str
    template_version: str
    schedule_id: int | None = None
    expected_version: int | None = None
    email_hash: str | None = None
    stage: str | None = None
    old_schedule: dict[str, str] | None = None
    join_url: str | None = None


class DeliveryResult(Boundary):
    id: int
    schedule_id: int
    application_id: int
    masked_email: str | None
    email: str | None = None
    status: Literal["pending", "sent", "failed", "uncertain"]
    attempts: int
    in_flight: bool
    retryable: bool
    error_category: str | None
    sent_at: str | None


class InvitationPreview(Boundary):
    recipient_count: int
    recipients: list[InvitationRecipient]
    sender: SenderIdentity
    confirmation_token: str | None = None


class InvitationBatchResult(InvitationPreview):
    id: int
    kind: str
    job_posting_id: int
    status: str
    selection: dict | None
    deliveries: list[DeliveryResult]
    sent: int
    failed: int
    uncertain: int
    pending: int


class InterviewScheduleResult(Boundary):
    id: int
    application_id: int
    candidate_name: str
    job_posting_id: int
    job_title: str
    stage: str
    start_utc: str
    end_utc: str
    local_start: str
    timezone: str
    duration_minutes: int
    status: str
    sequence: int
    version: int
    meeting_url: str | None
    room_status: str
    has_join_link: bool
    delivery_status: str
    delivery_id: int | None
    delivery_in_flight: bool
    delivery_retryable: bool
    delivery_attempts: int
    history: list[dict]
    batch_id: int
