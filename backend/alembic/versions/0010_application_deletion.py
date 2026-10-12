"""Track deleted imported applications without retaining candidate data.

Revision ID: 0010_application_deletion
Revises: 0009_google_forms_intake
Create Date: 2026-10-07
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_application_deletion"
down_revision = "0009_google_forms_intake"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "application_import_exclusions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=13), nullable=False),
        sa.Column("source_reference", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source IN ('direct_upload', 'google_form', 'import')",
            name="applicationsource",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_application_import_exclusions_owner_source_reference",
        "application_import_exclusions",
        ["created_by_user_id", "source", "source_reference"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_application_import_exclusions_owner_source_reference",
        table_name="application_import_exclusions",
    )
    op.drop_table("application_import_exclusions")
