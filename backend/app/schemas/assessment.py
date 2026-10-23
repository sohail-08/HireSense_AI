from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GenerateAssessment(Strict):
    scoring_run_id: int | None = Field(default=None, gt=0)
    interview_ids: list[int] | None = Field(default=None, max_length=5)
    analysis_run_ids: list[int] | None = Field(default=None, max_length=5)
    new_version: bool = False

    @model_validator(mode="after")
    def distinct(self):
        for ids in (self.interview_ids, self.analysis_run_ids):
            if ids is not None and (len(ids) != len(set(ids)) or any(i <= 0 for i in ids)):
                raise ValueError("Source IDs must be distinct positive integers")
        return self


class CompareAssessments(Strict):
    assessment_ids: list[int] = Field(min_length=2, max_length=4)

    @model_validator(mode="after")
    def distinct(self):
        if len(set(self.assessment_ids)) != len(self.assessment_ids):
            raise ValueError("Select distinct assessment versions")
        return self


class ReviewAssessment(Strict):
    note: str = Field(min_length=1, max_length=4000)
    reviewed: bool = True


class ExportReport(Strict):
    format: Literal["html", "pdf"]
    retry: bool = False


class BuildFinalRanking(Strict):
    confirmed: Literal[True]


class SummarySelection(Strict):
    """The model may prioritize supported facts, never author new claims or scores."""
    position: list[str] = Field(default_factory=list, max_length=5)
    strengths: list[str] = Field(default_factory=list, max_length=6)
    limitations: list[str] = Field(default_factory=list, max_length=6)
    verification: list[str] = Field(default_factory=list, max_length=6)


class Fact(Strict):
    id: str
    text: str
    kind: Literal["position", "strengths", "limitations", "verification"]
    evidence_ids: list[str]


class ReportData(Strict):
    identification: dict
    cv: dict | None
    interviews: list[dict]
    matrix: list[dict]
    evidence: dict
    completeness: Literal["complete", "partial"]
    missing: list[str]
    flags: list[str]
    facts: list[Fact]
    summary: dict
    policy: str
    score_summary: dict = Field(default_factory=dict)
    simple_summary: dict = Field(default_factory=dict)
    evidence_summary: dict = Field(default_factory=dict)
    practical_assessments: list[dict] = Field(default_factory=list)
