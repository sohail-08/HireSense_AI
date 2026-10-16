from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ConsentInput(StrictInput):
    consent: bool
    notice_version: Literal["transcription-v1"]


class WorkerClaim(StrictInput):
    claim: str = Field(pattern=r"^[a-f0-9]{64}$")


class WorkerUpdate(WorkerClaim):
    state: Literal["heartbeat", "completed", "failed"] = "heartbeat"
    connection_status: Literal["connecting", "transcribing", "reconnecting", "degraded", "stopped", "failed"] = "transcribing"
    failure_code: Literal["provider_unavailable", "provider_authentication_failed", "provider_rate_limited", "persistence_unavailable", "worker_disconnected", "missing_deepgram_key", "queue_overflow", "stream_limit", "shutdown_timeout", "invalid_configuration"] | None = None
    metrics: dict[str, float] = Field(default_factory=dict, max_length=30)
    keyterms_applied: bool | None = None


class StreamInput(WorkerClaim):
    stream_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    participant_identity: str = Field(min_length=1, max_length=100)
    track_sid: str = Field(min_length=1, max_length=100)


class WordInput(StrictInput):
    text: str = Field(max_length=200)
    start_ms: int = Field(ge=0, le=86_400_000)
    end_ms: int = Field(ge=0, le=86_400_000)
    confidence: float | None = Field(default=None, ge=0, le=1)


class SegmentInput(WorkerClaim):
    stream_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    provider_request_id: str = Field(default="", max_length=100)
    provider_segment_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=12000)
    start_ms: int = Field(ge=0, le=86_400_000)
    end_ms: int = Field(ge=0, le=86_400_000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    words: list[WordInput] = Field(default_factory=list, max_length=2000)

    @model_validator(mode="after")
    def ordered(self):
        if self.end_ms < self.start_ms or any(w.end_ms < w.start_ms for w in self.words):
            raise ValueError("Invalid transcript timing")
        return self
