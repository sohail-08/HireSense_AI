"""Versioned interviewer-only transcript analysis.

Revision ID: 0021_interview_analysis
Revises: 0020_interview_transcription
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0021_interview_analysis"
down_revision = "0020_interview_transcription"
branch_labels = None
depends_on = None


def upgrade():
    data = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table("interview_analysis_controls",
        sa.Column("interview_id", sa.Integer(), sa.ForeignKey("interview_schedules.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("automatic", sa.Boolean(), nullable=False), sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("references", data, nullable=False),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("interview_analysis_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("interview_id", sa.Integer(), sa.ForeignKey("interview_schedules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("candidate_applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False), sa.Column("stage", sa.String(60), nullable=False),
        sa.Column("error", sa.String(200)), sa.Column("snapshot", data, nullable=False), sa.Column("result", data, nullable=False),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("interview_id", "version", name="uq_interview_analysis_version"),
        sa.UniqueConstraint("interview_id", "fingerprint", name="uq_interview_analysis_input"))
    op.create_index("ix_interview_analysis_runs_interview_id", "interview_analysis_runs", ["interview_id"])
    op.create_index("ix_interview_analysis_runs_status", "interview_analysis_runs", ["status"])
    op.create_table("interview_analysis_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("interview_id", sa.Integer(), sa.ForeignKey("interview_schedules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("interview_analysis_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False), sa.Column("target_id", sa.String(80), nullable=False),
        sa.Column("payload", data, nullable=False), sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_interview_analysis_reviews_interview_id", "interview_analysis_reviews", ["interview_id"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM interview_analysis_runs")).scalar():
        raise RuntimeError("Export or explicitly remove interview analysis before downgrading")
    op.drop_table("interview_analysis_reviews")
    op.drop_table("interview_analysis_runs")
    op.drop_table("interview_analysis_controls")
