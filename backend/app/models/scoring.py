from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, ForeignKey, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


SNAPSHOT_JSON = JSON().with_variant(JSONB(), "postgresql")
SCORE_DECIMAL = Numeric(80, 60)


class ScoringConfiguration(Base):
    __tablename__ = "scoring_configurations"
    __table_args__ = (UniqueConstraint("job_posting_id", "input_hash", name="uq_scoring_configurations_job_input"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_posting_id: Mapped[int] = mapped_column(ForeignKey("job_postings.id", ondelete="CASCADE"), index=True)
    requirement_version: Mapped[str] = mapped_column(String(64))
    input_hash: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict[str, Any]] = mapped_column(SNAPSHOT_JSON)
    approved_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ScoringRun(Base):
    __tablename__ = "scoring_runs"
    __table_args__ = (UniqueConstraint("job_posting_id", "input_hash", name="uq_scoring_runs_job_input"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_posting_id: Mapped[int] = mapped_column(ForeignKey("job_postings.id", ondelete="CASCADE"), index=True)
    configuration_id: Mapped[int] = mapped_column(ForeignKey("scoring_configurations.id", ondelete="CASCADE"))
    requirement_version: Mapped[str] = mapped_column(String(64))
    formula_version: Mapped[str] = mapped_column(String(80))
    input_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="completed")
    snapshot: Mapped[dict[str, Any]] = mapped_column(SNAPSHOT_JSON)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class CandidateScore(Base):
    __tablename__ = "candidate_scores"
    __table_args__ = (UniqueConstraint("scoring_run_id", "application_id", name="uq_candidate_scores_run_application"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    scoring_run_id: Mapped[int] = mapped_column(ForeignKey("scoring_runs.id", ondelete="CASCADE"), index=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("candidate_applications.id", ondelete="CASCADE"), index=True)
    screening_run_id: Mapped[int | None] = mapped_column(ForeignKey("screening_runs.id", ondelete="SET NULL"), nullable=True)
    technical_score: Mapped[Decimal | None] = mapped_column(SCORE_DECIMAL, nullable=True)
    experience_score: Mapped[Decimal | None] = mapped_column(SCORE_DECIMAL, nullable=True)
    qualification_score: Mapped[Decimal | None] = mapped_column(SCORE_DECIMAL, nullable=True)
    final_score: Mapped[Decimal | None] = mapped_column(SCORE_DECIMAL, nullable=True)
    rank: Mapped[int | None] = mapped_column(nullable=True)
    review_state: Mapped[str] = mapped_column(String(30))
    breakdown: Mapped[dict[str, Any]] = mapped_column(SNAPSHOT_JSON)
    written_justification: Mapped[str] = mapped_column(Text)


class ScoringRequestKey(Base):
    __tablename__ = "scoring_request_keys"
    __table_args__ = (UniqueConstraint("job_posting_id", "key", name="uq_scoring_request_keys_job_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_posting_id: Mapped[int] = mapped_column(ForeignKey("job_postings.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    scoring_run_id: Mapped[int] = mapped_column(ForeignKey("scoring_runs.id", ondelete="CASCADE"))
