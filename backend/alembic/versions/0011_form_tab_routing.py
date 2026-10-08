"""Route candidate intake by a response tab assigned to each posting.

Revision ID: 0011_form_tab_routing
Revises: 0010_application_deletion
Create Date: 2026-10-07
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_form_tab_routing"
down_revision = "0010_application_deletion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("job_postings") as batch_op:
        batch_op.add_column(
            sa.Column(
                "response_sheet_name",
                sa.String(length=255),
                nullable=True,
            )
        )
        batch_op.create_index(
            "ix_job_postings_response_sheet_name",
            ["response_sheet_name"],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("job_postings") as batch_op:
        batch_op.drop_index("ix_job_postings_response_sheet_name")
        batch_op.drop_column("response_sheet_name")
