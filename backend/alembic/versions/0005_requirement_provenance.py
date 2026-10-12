"""Add RAG provenance to requirement profiles.

Revision ID: 0005_requirement_provenance
Revises: 0004_requirement_discovery
Create Date: 2026-10-05
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_requirement_provenance"
down_revision = "0004_requirement_discovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "requirement_profiles",
        sa.Column(
            "source_references",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.add_column(
        "requirement_profiles",
        sa.Column(
            "generation_metadata",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "requirement_profiles",
        sa.Column(
            "interviewer_overrides",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("requirement_profiles", "interviewer_overrides")
    op.drop_column("requirement_profiles", "generation_metadata")
    op.drop_column("requirement_profiles", "source_references")
