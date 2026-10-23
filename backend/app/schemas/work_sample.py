from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

class Task(Strict):
    title: str = Field(min_length=3, max_length=180)
    instructions: str = Field(min_length=20, max_length=12000)
    materials: str = Field(default="", max_length=20000)
    deliverables: str = Field(min_length=5, max_length=2000)
    duration_minutes: int = Field(strict=True, ge=1, le=15)
    tools_policy: str = Field(min_length=5, max_length=2000)
    response_type: Literal["code", "text"]

class TaskIdea(Strict):
    title: str = Field(min_length=3, max_length=180)
    summary: str = Field(min_length=15, max_length=700)
    duration_minutes: int = Field(strict=True, ge=1, le=15)
    response_type: Literal["code", "text"]

class TaskIdeas(Strict):
    options: list[TaskIdea] = Field(min_length=2, max_length=3)

class SuggestedTask(TaskIdea):
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    job_hash: str
    exercise_version: int

class SaveTask(Strict):
    task: Task
    version: int = Field(strict=True, ge=0)

class Action(Strict):
    version: int = Field(strict=True, ge=1)
    action: Literal["share", "start", "pause", "resume"]
    reason: str = Field(default="", max_length=1000)

class CandidateReady(Strict):
    attempt_id: int = Field(strict=True, ge=1)

class SaveSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attempt_id: int = Field(strict=True, ge=1)
    revision: int = Field(strict=True, ge=0)
    content: str = Field(max_length=50000)
    submit: bool = Field(default=False, strict=True)

class ScoreExercise(Strict):
    submission_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

class ApproveScore(ScoreExercise):
    assessment_id: int = Field(strict=True, ge=1)
    result_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: Literal[True]
