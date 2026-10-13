from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class RoomBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExchangeInvitation(RoomBoundary):
    token: str = Field(min_length=43, max_length=43, pattern=r"^[A-Za-z0-9_-]+$")


class ConfirmRoomAction(RoomBoundary):
    confirmed: Literal[True]


class EmptyRoomAction(RoomBoundary):
    pass


class LinkResult(RoomBoundary):
    join_url: str
    expires_at: datetime
    generation: int


class CandidateRoomInfo(RoomBoundary):
    job_title: str
    scheduled_start: datetime
    scheduled_end: datetime
    timezone: str
    room_status: Literal["scheduled", "waiting", "ready", "active", "ending", "ended", "cancelled"]
    waiting: bool
    admitted: bool
    join_opens_at: datetime
    join_closes_at: datetime


class InterviewerRoomInfo(CandidateRoomInfo):
    interview_id: int
    candidate_name: str
    room_version: int
    has_join_link: bool
    link_revoked: bool
    candidate_joined_at: datetime | None
    interviewer_joined_at: datetime | None
    interview_started_at: datetime | None
    interview_ended_at: datetime | None


class MediaAccess(RoomBoundary):
    server_url: str
    participant_token: str
    expires_at: datetime
    role: Literal["candidate", "interviewer"]
