"""Opt in new exercises to LLM scoring without grading historical submissions."""
from alembic import op
import sqlalchemy as sa

revision = "0026_practical_llm_scoring"
down_revision = "0025_work_sample_decisions"
branch_labels = depends_on = None


def upgrade():
    op.add_column("work_sample_exercises", sa.Column("grading_policy", sa.String(80), nullable=True))


def downgrade():
    op.drop_column("work_sample_exercises", "grading_policy")
