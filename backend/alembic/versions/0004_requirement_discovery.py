"""Add persistent requirement discovery sessions.

Revision ID: 0004_requirement_discovery
Revises: 0003_knowledge_base
Create Date: 2026-10-05
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_requirement_discovery"
down_revision = "0003_knowledge_base"
branch_labels = None
depends_on = None


def upgrade() -> None:
    status = sa.Enum(
        "active",
        "awaiting_confirmation",
        "confirmed",
        "error",
        name="requirementdiscoverystatus",
        native_enum=False,
        create_constraint=True,
    )

    op.create_table(
        "requirement_discovery_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("interviewer_user_id", sa.Integer(), nullable=False),
        sa.Column("requirement_profile_id", sa.Integer(), nullable=True),
        sa.Column("status", status, nullable=False),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["interviewer_user_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["requirement_profile_id"],
            ["requirement_profiles.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("requirement_discovery_sessions")
