"""Live practical exercises, versioned submissions and private human-reviewed assessments."""
from alembic import op
import sqlalchemy as sa

revision = "0024_live_work_samples"
down_revision = "0023_cv_semantic_evidence"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("work_sample_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("task", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_work_sample_templates_owner_id", "work_sample_templates", ["owner_id"])
    op.create_table("work_sample_exercises",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("interview_id", sa.Integer(), sa.ForeignKey("interview_schedules.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("candidate_applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("task", sa.JSON(), nullable=False),
        sa.Column("task_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_work_sample_exercises_application_id", "work_sample_exercises", ["application_id"])
    op.create_index("ix_work_sample_exercises_expires_at", "work_sample_exercises", ["expires_at"])
    op.create_table("work_sample_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exercise_id", sa.Integer(), sa.ForeignKey("work_sample_exercises.id", ondelete="CASCADE"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("remaining_seconds", sa.Integer(), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("saved_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("submission_hash", sa.String(64)),
        sa.UniqueConstraint("exercise_id", "number", name="uq_work_sample_attempt_number"))
    op.create_index("ix_work_sample_attempts_exercise_id", "work_sample_attempts", ["exercise_id"])
    op.create_table("work_sample_assessments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("attempt_id", sa.Integer(), sa.ForeignKey("work_sample_attempts.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("approved_result", sa.JSON()),
        sa.Column("review_reason", sa.Text()),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.String(300)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_work_sample_assessments_status", "work_sample_assessments", ["status"])


def downgrade():
    for name in ("work_sample_assessments", "work_sample_attempts", "work_sample_exercises", "work_sample_templates"):
        op.drop_table(name)
