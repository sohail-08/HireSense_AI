"""Versioned private semantic CV evidence; preserve existing screenings and scores."""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "0023_cv_semantic_evidence"
down_revision = "0022_consolidated_assessment"
branch_labels = depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql": op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column("screening_runs", sa.Column("input_fingerprint", sa.String(64), nullable=True))
    op.add_column("screening_runs", sa.Column("processing_metadata", sa.JSON(), nullable=False, server_default="{}"))
    op.create_index("ix_screening_runs_input_fingerprint", "screening_runs", ["input_fingerprint"])
    op.create_table("cv_passages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("cv_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cv_sha256", sa.String(64), nullable=False), sa.Column("encoder", sa.String(64), nullable=False),
        sa.Column("passage_id", sa.String(160), nullable=False), sa.Column("source_block_id", sa.String(160), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False), sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("locator", sa.String(255), nullable=False), sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(768).with_variant(sa.JSON(), "sqlite"), nullable=False))
    op.create_index("ix_cv_passages_document_id", "cv_passages", ["document_id"])
    op.create_index("uq_cv_passage_version", "cv_passages", ["document_id", "encoder", "passage_id"], unique=True)


def downgrade():
    op.drop_table("cv_passages")
    op.drop_index("ix_screening_runs_input_fingerprint", table_name="screening_runs")
    op.drop_column("screening_runs", "processing_metadata")
    op.drop_column("screening_runs", "input_fingerprint")
