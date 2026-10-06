"""Use previous job descriptions as the only knowledge source.

Revision ID: 0006_unify_knowledge_source
Revises: 0005_requirement_provenance
Create Date: 2026-10-06
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_unify_knowledge_source"
down_revision = "0005_requirement_provenance"
branch_labels = None
depends_on = None


old_source_type = sa.Enum(
    "company_policy",
    "previous_job_description",
    name="knowledgesourcetype",
    native_enum=False,
    create_constraint=True,
)
unified_source_type = sa.Enum(
    "previous_job_description",
    name="knowledgesourcetype",
    native_enum=False,
    create_constraint=True,
)


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE knowledge_documents "
            "SET source_type = 'previous_job_description' "
            "WHERE source_type = 'company_policy'"
        )
    )
    with op.batch_alter_table("knowledge_documents") as batch_op:
        batch_op.alter_column(
            "source_type",
            existing_type=old_source_type,
            type_=unified_source_type,
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("knowledge_documents") as batch_op:
        batch_op.alter_column(
            "source_type",
            existing_type=unified_source_type,
            type_=old_source_type,
            existing_nullable=False,
        )
