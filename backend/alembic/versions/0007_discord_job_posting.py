"""Add Discord job-post preview and publication state.

Revision ID: 0007_discord_job_posting
Revises: 0006_unify_knowledge_source
Create Date: 2026-10-06
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_discord_job_posting"
down_revision = "0006_unify_knowledge_source"
branch_labels = None
depends_on = None


old_status = sa.Enum(
    "draft",
    "published",
    "closed",
    "failed",
    name="jobpostingstatus",
    native_enum=False,
    create_constraint=True,
)
new_status = sa.Enum(
    "draft",
    "publishing",
    "published",
    "closed",
    "failed",
    "uncertain",
    name="jobpostingstatus",
    native_enum=False,
    create_constraint=True,
)


def upgrade() -> None:
    with op.batch_alter_table("job_postings") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=old_status,
            type_=new_status,
            existing_nullable=False,
        )
        batch_op.add_column(sa.Column("heading", sa.String(2000)))
        batch_op.add_column(sa.Column("contact_email", sa.String(254)))
        batch_op.add_column(sa.Column("location", sa.String(500)))
        batch_op.add_column(sa.Column("application_deadline", sa.Date()))
        batch_op.add_column(sa.Column("additional_instructions", sa.Text()))
        batch_op.add_column(sa.Column("reviewed_content", sa.Text()))
        batch_op.add_column(sa.Column("discord_payload", sa.JSON()))
        batch_op.add_column(sa.Column("job_description_version", sa.Integer()))
        batch_op.add_column(
            sa.Column("job_description_content_hash", sa.String(64))
        )
        batch_op.add_column(sa.Column("external_server_id", sa.String(255)))
        batch_op.add_column(sa.Column("external_channel_id", sa.String(255)))
        batch_op.add_column(sa.Column("error_code", sa.String(100)))
        batch_op.add_column(sa.Column("error_message", sa.Text()))
        batch_op.add_column(
            sa.Column("attempt_started_at", sa.DateTime(timezone=True))
        )
        batch_op.create_index(
            "ix_job_postings_job_description_id",
            ["job_description_id"],
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE job_postings SET status = 'failed' "
            "WHERE status IN ('publishing', 'uncertain')"
        )
    )
    with op.batch_alter_table("job_postings") as batch_op:
        batch_op.drop_index("ix_job_postings_job_description_id")
        batch_op.drop_column("attempt_started_at")
        batch_op.drop_column("error_message")
        batch_op.drop_column("error_code")
        batch_op.drop_column("external_channel_id")
        batch_op.drop_column("external_server_id")
        batch_op.drop_column("job_description_content_hash")
        batch_op.drop_column("job_description_version")
        batch_op.drop_column("discord_payload")
        batch_op.drop_column("reviewed_content")
        batch_op.drop_column("additional_instructions")
        batch_op.drop_column("application_deadline")
        batch_op.drop_column("location")
        batch_op.drop_column("contact_email")
        batch_op.drop_column("heading")
        batch_op.alter_column(
            "status",
            existing_type=new_status,
            type_=old_status,
            existing_nullable=False,
        )
