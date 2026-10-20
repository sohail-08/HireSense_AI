"""Add private consolidated assessments and report artifacts without changing upstream data."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0022_consolidated_assessment"
down_revision = "0021_interview_analysis"
branch_labels = None
depends_on = None


def upgrade():
    data = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table("assessment_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("candidate_applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_posting_id", sa.Integer(), sa.ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("stage", sa.String(60), nullable=False),
        sa.Column("completeness", sa.String(20), nullable=False), sa.Column("snapshot", data, nullable=False),
        sa.Column("result", data, nullable=False), sa.Column("error", sa.String(250)),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("application_id", "version", name="uq_assessment_version"),
        sa.UniqueConstraint("application_id", "fingerprint", name="uq_assessment_input"))
    for name in ("application_id", "job_posting_id", "status"):
        op.create_index(f"ix_assessment_runs_{name}", "assessment_runs", [name])
    op.create_table("assessment_reviews", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("assessment_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("note", sa.Text(), nullable=False), sa.Column("reviewed", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_assessment_reviews_run_id", "assessment_reviews", ["run_id"])
    op.create_table("assessment_comparisons", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_posting_id", sa.Integer(), sa.ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False), sa.Column("assessment_ids", data, nullable=False),
        sa.Column("snapshot", data, nullable=False), sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("job_posting_id", "fingerprint", name="uq_assessment_comparison_input"))
    op.create_index("ix_assessment_comparisons_job_posting_id", "assessment_comparisons", ["job_posting_id"])
    op.create_table("report_artifacts", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assessment_id", sa.Integer(), sa.ForeignKey("assessment_runs.id", ondelete="CASCADE")),
        sa.Column("comparison_id", sa.Integer(), sa.ForeignKey("assessment_comparisons.id", ondelete="CASCADE")),
        sa.Column("format", sa.String(8), nullable=False), sa.Column("template_version", sa.String(50), nullable=False), sa.Column("payload", data, nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False), sa.Column("status", sa.String(20), nullable=False),
        sa.Column("storage_key", sa.String(150)), sa.Column("sha256", sa.String(64)), sa.Column("error", sa.String(250)),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("(assessment_id IS NULL) != (comparison_id IS NULL)", name="ck_report_one_target"),
        sa.UniqueConstraint("fingerprint", name="uq_report_artifact_input"))
    for name in ("assessment_id", "comparison_id", "status"):
        op.create_index(f"ix_report_artifacts_{name}", "report_artifacts", [name])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM assessment_runs")).scalar():
        raise RuntimeError("Explicitly remove consolidated assessments before downgrading")
    for table in ("report_artifacts", "assessment_reviews", "assessment_comparisons", "assessment_runs"):
        op.drop_table(table)
