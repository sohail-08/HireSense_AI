from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.candidate import (
    ApplicationSource,
    ApplicationStatus,
    CVProcessingStatus,
)


class CandidateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    linkedin_url: str | None = Field(default=None, max_length=2048)
    portfolio_url: str | None = Field(default=None, max_length=2048)
    location: str | None = Field(default=None, max_length=200)


class CandidateResponse(CandidateCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class CandidateApplicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_posting_id: int = Field(gt=0)
    candidate_id: int | None = Field(default=None, gt=0)
    source: ApplicationSource = ApplicationSource.DIRECT_UPLOAD
    source_reference: str | None = Field(default=None, max_length=255)


class CandidateApplicationResponse(CandidateApplicationCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: ApplicationStatus
    submitted_at: datetime
    created_at: datetime
    updated_at: datetime


class CVDocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    application_id: int | None = Field(default=None, gt=0)
    candidate_id: int | None = Field(default=None, gt=0)
    original_filename: str = Field(min_length=1, max_length=255)
    storage_path: str = Field(min_length=1, max_length=2048)
    mime_type: str = Field(min_length=1, max_length=100)
    file_size_bytes: int = Field(gt=0)
    sha256: str = Field(min_length=64, max_length=64)
    source: ApplicationSource = ApplicationSource.DIRECT_UPLOAD


class CVDocumentResponse(CVDocumentCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: CVProcessingStatus
    extracted_text: str | None
    extraction_data: dict[str, Any] | None
    extraction_warnings: list[str]
    error_message: str | None
    processed_at: datetime | None
    created_at: datetime
    updated_at: datetime
