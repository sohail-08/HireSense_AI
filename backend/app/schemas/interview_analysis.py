from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Reference(Strict):
    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    kind: Literal["answer_guide", "technical_reference"]
    content: str = Field(min_length=1, max_length=16000)
    requirement_ids: list[str] = Field(default_factory=list, max_length=100)


class StartAnalysis(Strict):
    automatic: bool = True
    finalize_last: bool = False
    reanalyze: bool = False


class ReferenceUpdate(Strict):
    revision: int = Field(ge=0)
    references: list[Reference] = Field(max_length=20)
    approved: Literal[True]


class Turn(Strict):
    segment_id: str
    kind: Literal["question", "question_continuation", "answer", "acknowledgement", "clarification", "procedural", "other"]
    subparts: list[str] = Field(default_factory=list, max_length=12)
    reason: str = Field(max_length=500)
    uncertain: bool = False
    follow_up_of: str | None = None


class Detection(Strict):
    turns: list[Turn] = Field(max_length=120)


class PairEdit(Strict):
    id: str = Field(min_length=1, max_length=80)
    question_ids: list[str] = Field(min_length=1, max_length=100)
    answer_ids: list[str] = Field(default_factory=list, max_length=200)
    context_ids: list[str] = Field(default_factory=list, max_length=100)
    subparts: list[str] = Field(default_factory=list, max_length=12)
    excluded: bool = False
    unanswered: bool = False


class CorrectPairs(Strict):
    run_id: int
    pairs: list[PairEdit] = Field(max_length=100)
    reason: str = Field(min_length=1, max_length=2000)


class ReviewInput(Strict):
    kind: Literal["assessment_review", "suggestion_used", "suggestion_dismissed", "suggestion_linked"]
    target_id: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=2000)
    segment_ids: list[str] = Field(default_factory=list, max_length=30)


class Quote(Strict):
    segment_id: str
    quote: str = Field(min_length=1, max_length=12000)


class ReferenceQuote(Strict):
    reference_id: str
    quote: str = Field(min_length=1, max_length=4000)


class Dimension(Strict):
    label: Literal["direct", "partial", "tangent", "ambiguous", "supported", "contradicted",
                   "partially_supported", "unable_to_verify", "complete", "incomplete", "clear",
                   "mixed", "limited", "unanswered", "unreadable", "not_assessed"]
    justification: str = Field(min_length=1, max_length=1500)
    citations: list[Quote] = Field(default_factory=list, max_length=12)
    references: list[ReferenceQuote] = Field(default_factory=list, max_length=6)
    evidence_gaps: list[str] = Field(default_factory=list, max_length=12)
    flags: list[str] = Field(default_factory=list, max_length=12)


class Assessment(Strict):
    relevance: Dimension
    accuracy: Dimension
    completeness: Dimension
    quality: Dimension
    expected_elements: list[str] = Field(default_factory=list, max_length=12)
    expected_elements_basis: Literal["approved_guide", "provisional"]


class Mapping(Strict):
    requirement_id: str
    status: Literal["supporting_evidence", "partial_supporting_evidence", "contradictory_evidence", "insufficient_evidence", "not_assessed"]
    explanation: str = Field(min_length=1, max_length=1200)
    citations: list[Quote] = Field(default_factory=list, max_length=12)
    flags: list[str] = Field(default_factory=list, max_length=12)


class Mappings(Strict):
    mappings: list[Mapping] = Field(max_length=100)


class SupportFinding(Strict):
    target: str
    supported: bool
    reason: str = Field(min_length=1, max_length=800)


class SupportCheck(Strict):
    findings: list[SupportFinding] = Field(max_length=120)


class FollowUp(Strict):
    question: str = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=1, max_length=1200)
    requirement_ids: list[str] = Field(default_factory=list, max_length=12)
    citations: list[Quote] = Field(default_factory=list, max_length=12)
    expected_clarification: str = Field(min_length=1, max_length=1000)
    priority: Literal["high", "normal", "low"]
    priority_reason: str = Field(min_length=1, max_length=500)


class FollowUps(Strict):
    suggestions: list[FollowUp] = Field(max_length=3)
