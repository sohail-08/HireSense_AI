"""Add Google Forms response provenance to candidate applications.

Revision ID: 0009_google_forms_intake
Revises: 0008_supervisor_sessions
Create Date: 2026-10-07
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_google_forms_intake"
down_revision = "0008_supervisor_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("candidate_applications") as batch_op:
        batch_op.add_column(
            sa.Column(
                "response_data",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch_op.create_index(
            "uq_candidate_applications_source_reference",
            ["job_posting_id", "source", "source_reference"],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("candidate_applications") as batch_op:
        batch_op.drop_index(
            "uq_candidate_applications_source_reference"
        )
        batch_op.drop_column("response_data")
