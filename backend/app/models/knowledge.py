from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.database import Base


# nomic-embed-text's full-size embeddings. Changing this requires a migration
# and regeneration of the knowledge embeddings using the new model.
KNOWLEDGE_EMBEDDING_DIMENSIONS = 768


class KnowledgeSourceType(str, Enum):
    PREVIOUS_JOB_DESCRIPTION = "previous_job_description"


def _values(enum_type: type[Enum]) -> list[str]:
    return [item.value for item in enum_type]


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        Index("ix_knowledge_documents_source_type", "source_type"),
        Index(
            "uq_knowledge_documents_content_hash",
            "content_hash",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[KnowledgeSourceType] = mapped_column(
        SqlEnum(
            KnowledgeSourceType,
            native_enum=False,
            create_constraint=True,
            values_callable=_values,
        )
    )
    source_uri: Mapped[str | None] = mapped_column(
        String(2048), nullable=True
    )
    content_hash: Mapped[str] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    chunks: Mapped[list["KnowledgeChunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="KnowledgeChunk.chunk_index",
    )


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        Index(
            "uq_knowledge_chunks_document_index",
            "document_id",
            "chunk_index",
            unique=True,
        ),
        Index(
            "ix_knowledge_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_with={"m": 16, "ef_construction": 64},
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_documents.id")
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    # SQLite is retained only for deterministic offline tests.
    embedding: Mapped[list[float]] = mapped_column(
        Vector(KNOWLEDGE_EMBEDDING_DIMENSIONS).with_variant(JSON(), "sqlite"),
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    document: Mapped[KnowledgeDocument] = relationship(
        back_populates="chunks"
    )
