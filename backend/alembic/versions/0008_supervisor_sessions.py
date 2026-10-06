"""Add persistent supervisor workflow sessions.

Revision ID: 0008_supervisor_sessions
Revises: 0007_discord_job_posting
Create Date: 2026-10-06
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_supervisor_sessions"
down_revision = "0007_discord_job_posting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "supervisor_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("interviewer_user_id", sa.Integer(), nullable=False),
        sa.Column("requirement_session_id", sa.String(length=36), nullable=True),
        sa.Column("requirement_profile_id", sa.Integer(), nullable=True),
        sa.Column("job_description_id", sa.Integer(), nullable=True),
        sa.Column("job_posting_id", sa.Integer(), nullable=True),
        sa.Column("phase", sa.String(length=50), nullable=False),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["interviewer_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["requirement_session_id"],
            ["requirement_discovery_sessions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["requirement_profile_id"],
            ["requirement_profiles.id"],
        ),
        sa.ForeignKeyConstraint(
            ["job_description_id"],
            ["job_descriptions.id"],
        ),
        sa.ForeignKeyConstraint(["job_posting_id"], ["job_postings.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_supervisor_sessions_interviewer_user_id",
        "supervisor_sessions",
        ["interviewer_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_supervisor_sessions_interviewer_user_id",
        table_name="supervisor_sessions",
    )
    op.drop_table("supervisor_sessions")
