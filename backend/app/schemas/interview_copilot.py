from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.schemas.work_sample import SuggestedTask


class CopilotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=2000)
    version: int = Field(ge=0)
    selected_task_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")

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
    tool_name: Literal["suggest_interview_questions", "help", "interview_analysis", "suggest_practical_tasks", "create_practical_task"] | None = None
    task_options: list[SuggestedTask] = Field(default_factory=list)
    selected_task_id: str | None = None
    task_created: bool = False
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
    cv_score: str | None = None
    probe_areas: list[dict] = Field(default_factory=list)


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
    open_practical_exercise: bool = False
