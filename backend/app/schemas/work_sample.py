from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Criterion(Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    title: str = Field(min_length=2, max_length=100)
    description: str = Field(min_length=5, max_length=1000)
    weight: int = Field(strict=True, ge=1, le=100)


class Task(Strict):
    title: str = Field(min_length=3, max_length=180)
    instructions: str = Field(min_length=20, max_length=12000)
    materials: str = Field(default="", max_length=20000)
    deliverables: str = Field(min_length=5, max_length=2000)
    duration_minutes: int = Field(strict=True, ge=3, le=120)
    tools_policy: str = Field(min_length=5, max_length=2000)
    response_type: Literal["code", "text"]
    criteria: list[Criterion] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def rubric(self):
        if sum(c.weight for c in self.criteria) != 100:
            raise ValueError("Assessment weights must total 100%")
        if len({c.id for c in self.criteria}) != len(self.criteria):
            raise ValueError("Assessment criterion IDs must be unique")
        return self


class SaveTask(Strict):
    task: Task
    version: int = Field(strict=True, ge=0)


class Action(Strict):
    version: int = Field(strict=True, ge=1)
    action: Literal["share", "start", "pause", "resume", "extend", "retry"]
    reason: str = Field(default="", max_length=1000)
    extra_minutes: int = Field(default=5, strict=True, ge=1, le=60)


class CandidateReady(Strict):
    attempt_id: int = Field(strict=True, ge=1)


class SaveSubmission(BaseModel):
    # Never strip/normalize the candidate's exact code or explanation.
    model_config = ConfigDict(extra="forbid")
    attempt_id: int = Field(strict=True, ge=1)
    revision: int = Field(strict=True, ge=0)
    content: str = Field(max_length=50000)
    explanation: str = Field(max_length=10000)
    submit: bool = False


class Evidence(Strict):
    field: Literal["content", "explanation", "discussion"]
    segment_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    line_start: int = Field(strict=True, ge=1)
    line_end: int = Field(strict=True, ge=1)
    quote: str = Field(min_length=1, max_length=4000)


class Finding(Strict):
    criterion_id: str = Field(max_length=40)
    label: Literal["met", "partially_met", "unmet", "needs_verification"]
    reason: str = Field(min_length=5, max_length=600)
    evidence: list[Evidence] = Field(max_length=6)


class Evaluation(Strict):
    summary: str = Field(min_length=5, max_length=400)
    findings: list[Finding] = Field(min_length=1, max_length=8)


class SupportCheck(Strict):
    criterion_id: str = Field(max_length=40)
    supported: bool
    reason: str = Field(min_length=5, max_length=600)


class SupportChecks(Strict):
    checks: list[SupportCheck] = Field(min_length=1, max_length=8)


class Review(Strict):
    assessment_id: int = Field(strict=True, ge=1)
    result: Evaluation
    reason: str = Field(min_length=5, max_length=1000)


class DraftTask(Strict):
    brief: str = Field(min_length=5, max_length=2000)


class AssessExercise(Strict):
    discussion_segment_ids: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def unique_ids(self):
        import re
        if len(set(self.discussion_segment_ids)) != len(self.discussion_segment_ids) or any(
                not re.fullmatch(r"[a-f0-9]{64}", value) for value in self.discussion_segment_ids):
            raise ValueError("Select distinct saved transcript passages")
        return self


def validated_evaluation(task: dict, submission: dict, evaluation: Evaluation, discussion=()) -> dict:
    """Reject fabricated citations; uncertain evidence never produces an invented zero."""
    expected = {c["id"]: c for c in task["criteria"]}
    if len(evaluation.findings) != len(expected) or {f.criterion_id for f in evaluation.findings} != set(expected):
        raise ValueError("Assess each approved criterion exactly once")
    for finding in evaluation.findings:
        if finding.label != "needs_verification" and not finding.evidence:
            raise ValueError("Scored findings require exact submission evidence")
        for evidence in finding.evidence:
            if evidence.field == "discussion":
                source = next((s for s in discussion if s["id"] == evidence.segment_id), None)
                if not source or source["speaker"] != "CANDIDATE":
                    raise ValueError("A discussion finding must cite the assigned candidate's saved speech")
                lines = source["text"].split("\n")
            else:
                if evidence.segment_id is not None:
                    raise ValueError("Submission evidence cannot reference a transcript passage")
                lines = submission[evidence.field].split("\n")
            if evidence.line_end < evidence.line_start or evidence.line_end > len(lines):
                raise ValueError("Evidence line range is invalid")
            if evidence.quote not in "\n".join(lines[evidence.line_start - 1:evidence.line_end]):
                raise ValueError("Evidence does not match the submitted text")
    result = evaluation.model_dump()
    values = {"met": 1, "partially_met": .5, "unmet": 0}
    result["score"] = None if any(f.label == "needs_verification" for f in evaluation.findings) else sum(
        expected[f.criterion_id]["weight"] * values[f.label] for f in evaluation.findings)
    result["limitation"] = ("Code was not executed. Runtime correctness and test results are not verified."
        if task["response_type"] == "code" else "Based on the supplied scenario and saved response. Uncertain findings require interviewer verification.")
    return result
