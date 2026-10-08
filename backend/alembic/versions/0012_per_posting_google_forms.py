"""Store one discovered Google Form destination per job posting.

Revision ID: 0012_per_posting_google_forms
Revises: 0011_form_tab_routing
Create Date: 2026-10-07
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_per_posting_google_forms"
down_revision = "0011_form_tab_routing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("job_postings") as batch_op:
        batch_op.drop_index("ix_job_postings_response_sheet_name")
        batch_op.create_index(
            "ix_job_postings_response_sheet_name",
            ["response_sheet_name"],
            unique=False,
        )
        batch_op.add_column(
            sa.Column("google_form_id", sa.String(length=255), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "response_spreadsheet_id",
                sa.String(length=255),
                nullable=True,
            )
        )
        batch_op.create_index(
            "ix_job_postings_google_form_id",
            ["google_form_id"],
            unique=True,
        )
        batch_op.create_index(
            "ix_job_postings_response_spreadsheet_id",
            ["response_spreadsheet_id"],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("job_postings") as batch_op:
        batch_op.drop_index("ix_job_postings_response_spreadsheet_id")
        batch_op.drop_index("ix_job_postings_google_form_id")
        batch_op.drop_column("response_spreadsheet_id")
        batch_op.drop_column("google_form_id")
        batch_op.drop_index("ix_job_postings_response_sheet_name")
        batch_op.create_index(
            "ix_job_postings_response_sheet_name",
            ["response_sheet_name"],
            unique=True,
        )
