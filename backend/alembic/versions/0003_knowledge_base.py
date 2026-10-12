"""Add the company-policy and previous-JD knowledge base.

Revision ID: 0003_knowledge_base
Revises: 0002_f1_domain_models
Create Date: 2026-10-05
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_knowledge_base"
down_revision = "0002_f1_domain_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    source_type = sa.Enum(
        "company_policy",
        "previous_job_description",
        name="knowledgesourcetype",
        native_enum=False,
        create_constraint=True,
    )

    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("source_type", source_type, nullable=False),
        sa.Column("source_uri", sa.String(length=2048), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_documents_source_type",
        "knowledge_documents",
        ["source_type"],
    )
    op.create_index(
        "uq_knowledge_documents_content_hash",
        "knowledge_documents",
        ["content_hash"],
        unique=True,
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_knowledge_chunks_document_index",
        "knowledge_chunks",
        ["document_id", "chunk_index"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_knowledge_chunks_document_index",
        table_name="knowledge_chunks",
    )
    op.drop_table("knowledge_chunks")

    op.drop_index(
        "uq_knowledge_documents_content_hash",
        table_name="knowledge_documents",
    )
    op.drop_index(
        "ix_knowledge_documents_source_type",
        table_name="knowledge_documents",
    )
    op.drop_table("knowledge_documents")
