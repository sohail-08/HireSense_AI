"""Store existing knowledge embeddings as pgvector and index cosine distance.

Revision ID: 0014_pgvector_knowledge
Revises: 0013_cv_screening_and_ranking
"""

from alembic import op
from pgvector.sqlalchemy import Vector
import sqlalchemy as sa


revision = "0014_pgvector_knowledge"
down_revision = "0013_cv_screening_and_ranking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name == "sqlite":
        return  # Offline test databases keep their JSON embeddings.
    if connection.dialect.name != "postgresql":
        raise RuntimeError("Knowledge embeddings require PostgreSQL with pgvector")

    # Validate before rewriting the column. Alembic rolls back on any failure.
    invalid = connection.scalar(sa.text("""
        SELECT count(*) FROM knowledge_chunks
        WHERE CASE WHEN json_typeof(embedding) = 'array'
            THEN json_array_length(embedding) <> 768 ELSE true END
    """))
    if invalid:
        raise RuntimeError(
            f"Cannot migrate {invalid} knowledge chunk(s): embeddings must have "
            "768 dimensions. Regenerate them with nomic-embed-text before "
            "retrying. Existing knowledge records have not been deleted."
        )

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.alter_column(
        "knowledge_chunks", "embedding",
        existing_type=sa.JSON(), type_=Vector(768), existing_nullable=False,
        postgresql_using="embedding::text::vector(768)",
    )
    op.create_index(
        "ix_knowledge_chunks_embedding_hnsw", "knowledge_chunks", ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"m": 16, "ef_construction": 64},
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    op.drop_index("ix_knowledge_chunks_embedding_hnsw", table_name="knowledge_chunks")
    op.alter_column(
        "knowledge_chunks", "embedding",
        existing_type=Vector(768), type_=sa.JSON(), existing_nullable=False,
        postgresql_using="embedding::text::json",
    )
    # The extension may also be used by other tables; leave it installed.
