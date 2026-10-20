from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class CopilotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=2000)
    version: int = Field(ge=0)

    @field_validator("message")
    @classmethod
    def meaningful(cls, value):
        if not value.strip():
            raise ValueError("Please enter a question")
        return value.strip()


class SuggestedQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=1200)
    requirement: str = Field(min_length=1, max_length=500)
    source_ids: list[int] = Field(min_length=1, max_length=6)


class CopilotAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=2000)
    questions: list[SuggestedQuestion] = Field(default_factory=list, max_length=6)


class QuestionSource(BaseModel):
    chunk_id: int
    document_title: str
    excerpt: str


class CopilotMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    questions: list[SuggestedQuestion] = Field(default_factory=list)
    sources: list[QuestionSource] = Field(default_factory=list)
    tool_name: Literal["suggest_interview_questions", "help", "interview_analysis"] | None = None
    analysis_citations: list[dict] = Field(default_factory=list)
    analysis_run_id: int | None = None


class CandidateContext(BaseModel):
    name: str
    email: str | None
    phone: str | None
    location: str | None
    skills: list[str]
    qualifications: list[str]
    experience_years: float | None
    recent_roles: list[str]


class InterviewCopilotContext(BaseModel):
    candidate: CandidateContext
    job_title: str
    required_skills: list[str]
    preferred_skills: list[str]
    qualifications: list[str]
    minimum_experience: int | None
    selection_criteria: list[str]
    messages: list[CopilotMessage]
    version: int
