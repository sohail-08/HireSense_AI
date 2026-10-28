from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.knowledge import KnowledgeSourceType


class KnowledgeDocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    source_type: KnowledgeSourceType = (
        KnowledgeSourceType.PREVIOUS_JOB_DESCRIPTION
    )
    source_uri: str | None = Field(default=None, max_length=2048)
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    source_type: KnowledgeSourceType
    source_uri: str | None
    content_hash: str
    metadata_json: dict[str, Any]
    created_by_user_id: int | None
    created_at: datetime
    updated_at: datetime
