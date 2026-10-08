from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ScreeningBatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_posting_id: int = Field(gt=0)
    application_ids: list[int] | None = None


class ScreeningBatchItemResponse(BaseModel):
    id: int
    application_id: int
    screening_run_id: int | None
    status: str
    error_message: str | None


class ScreeningBatchResponse(BaseModel):
    id: int
    job_posting_id: int
    status: str
    application_ids: list[int]
    total_applications: int
    processed_applications: int
    successful_applications: int
    review_applications: int
    failed_applications: int
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    items: list[ScreeningBatchItemResponse] = Field(default_factory=list)


class ScreeningJobOption(BaseModel):
    id: int
    title: str
    posting_status: str
    application_count: int
    pending_count: int


class ScreeningApplicationItem(BaseModel):
    id: int
    candidate_name: str
    candidate_email: str | None
    submitted_at: datetime
    cv_filename: str | None
    screening_status: str
    screening_run_id: int | None
    requirement_coverage: float | None
    error_message: str | None


class RankingItem(BaseModel):
    application_id: int
    screening_run_id: int
    candidate_name: str
    candidate_email: str | None
    rank: int | None
    disposition: str
    requirement_coverage: float | None
    met_count: int
    partially_met_count: int
    unmet_count: int
    uncertain_count: int
    suitability_summary: str | None
    strengths: list[dict[str, Any]]
    gaps: list[dict[str, Any]]
    points_to_verify: list[dict[str, Any]]


class RankingResponse(BaseModel):
    snapshot_id: int | None
    created_at: datetime | None
    calculation_version: str
    ranked: list[RankingItem]
    review: list[RankingItem]


class ScreeningDashboardResponse(BaseModel):
    job_posting_id: int
    job_title: str
    requirement_profile_id: int
    applications: list[ScreeningApplicationItem]
    ranking: RankingResponse


class RequirementMatchResponse(BaseModel):
    requirement_key: str
    category: str
    name: str
    details: str | None
    weight: float
    status: str
    explanation: str
    evidence: list[dict[str, Any]]
    evidence_gaps: list[str]
    review_flags: list[str]


class ScreeningRunDetailResponse(BaseModel):
    id: int
    application_id: int
    status: str
    requirement_coverage: float | None
    extracted_profile: dict[str, Any] | None
    source_blocks: list[dict[str, Any]]
    suitability_summary: str | None
    strengths: list[dict[str, Any]]
    gaps: list[dict[str, Any]]
    points_to_verify: list[dict[str, Any]]
    review_flags: list[str]
    error_message: str | None
    model_name: str | None
    prompt_version: str
    calculation_version: str
    requirement_snapshot: dict[str, Any]
    matches: list[RequirementMatchResponse]
