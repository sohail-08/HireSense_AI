from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Category = Literal["technical", "experience", "qualification"]


class RequirementWeightApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement_id: str
    category: Category | None
    classification: Literal["required", "preferred"]
    weight: Decimal = Field(ge=0, le=10000, max_digits=12, decimal_places=6)


class ScoringApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: Literal[True]
    requirement_version: str
    category_weights: dict[Category, Decimal]
    requirements: list[RequirementWeightApproval] = Field(min_length=1, max_length=1000)


class ScoreRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    configuration_id: int = Field(gt=0)
    application_ids: list[int] | None = None
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)
