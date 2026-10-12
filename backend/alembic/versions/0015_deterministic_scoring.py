"""Immutable scoring configurations, calculation runs, and candidate scores."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0015_deterministic_scoring"
down_revision = "0014_pgvector_knowledge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Freeze the schema in the revision; future model edits must not rewrite this
    # migration when upgrading an older checkout.
    snapshot = sa.JSON().with_variant(JSONB(), "postgresql")
    op.create_table(
        "scoring_configurations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_posting_id", sa.Integer(), sa.ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requirement_version", sa.String(64), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("snapshot", snapshot, nullable=False),
        sa.Column("approved_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_posting_id", "input_hash", name="uq_scoring_configurations_job_input"),
    )
    op.create_table(
        "scoring_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_posting_id", sa.Integer(), sa.ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("configuration_id", sa.Integer(), sa.ForeignKey("scoring_configurations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requirement_version", sa.String(64), nullable=False),
        sa.Column("formula_version", sa.String(80), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("snapshot", snapshot, nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_posting_id", "input_hash", name="uq_scoring_runs_job_input"),
    )
    op.create_table(
        "candidate_scores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scoring_run_id", sa.Integer(), sa.ForeignKey("scoring_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("candidate_applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("screening_run_id", sa.Integer(), sa.ForeignKey("screening_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("technical_score", sa.Numeric(80, 60), nullable=True),
        sa.Column("experience_score", sa.Numeric(80, 60), nullable=True),
        sa.Column("qualification_score", sa.Numeric(80, 60), nullable=True),
        sa.Column("final_score", sa.Numeric(80, 60), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("review_state", sa.String(30), nullable=False),
        sa.Column("breakdown", snapshot, nullable=False),
        sa.Column("written_justification", sa.Text(), nullable=False),
        sa.UniqueConstraint("scoring_run_id", "application_id", name="uq_candidate_scores_run_application"),
    )
    op.create_table(
        "scoring_request_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_posting_id", sa.Integer(), sa.ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("scoring_run_id", sa.Integer(), sa.ForeignKey("scoring_runs.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("job_posting_id", "key", name="uq_scoring_request_keys_job_key"),
    )
    for table, columns in {
        "scoring_configurations": ["job_posting_id"], "scoring_runs": ["job_posting_id"],
        "candidate_scores": ["scoring_run_id", "application_id"],
    }.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    for table in ("scoring_request_keys", "candidate_scores", "scoring_runs", "scoring_configurations"):
        op.drop_table(table)
