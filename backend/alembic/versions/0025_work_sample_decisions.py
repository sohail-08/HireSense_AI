"""Human correctness decisions, without rewriting historical reviews."""
from alembic import op
import sqlalchemy as sa

revision = "0025_work_sample_decisions"
down_revision = "0024_live_work_samples"
branch_labels = depends_on = None


def upgrade():
    op.create_table("work_sample_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exercise_id", sa.Integer(), sa.ForeignKey("work_sample_exercises.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("attempt_id", sa.Integer(), sa.ForeignKey("work_sample_attempts.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("submission_hash", sa.String(64), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table("work_sample_decisions")
