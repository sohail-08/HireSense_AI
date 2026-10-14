from dataclasses import dataclass
from hashlib import sha256
import math
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.knowledge import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSourceType,
    KNOWLEDGE_EMBEDDING_DIMENSIONS,
)
from app.rag.chunking import chunk_text, normalize_text
from app.rag.embeddings import (
    EmbeddingProvider,
    HashEmbeddingProvider,
    cosine_similarity,
)


@dataclass(frozen=True)
class RetrievedKnowledgeChunk:
    document_id: int
    document_title: str
    source_type: KnowledgeSourceType
    chunk_id: int
    chunk_index: int
    content: str
    score: float
    source_uri: str | None


class KnowledgeBaseService:
    def __init__(
        self,
        embedding_provider: EmbeddingProvider | None = None,
        *,
        chunk_size: int = 1200,
        chunk_overlap: int = 150,
    ):
        self.embedding_provider = embedding_provider or HashEmbeddingProvider()
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    @property
    def embedding_model(self) -> str:
        return getattr(self.embedding_provider, "model", self.embedding_provider.__class__.__name__)

    def _embed(self, db: Session, content: str) -> list[float]:
        vector = [float(value) for value in self.embedding_provider.embed(content)]
        if not vector or not all(math.isfinite(value) for value in vector):
            raise ValueError("Embedding model returned an empty or non-finite vector")
        if db.get_bind().dialect.name == "postgresql" and len(vector) != KNOWLEDGE_EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"Knowledge embeddings require {KNOWLEDGE_EMBEDDING_DIMENSIONS} dimensions; "
                f"{self.embedding_model} returned {len(vector)}. Use nomic-embed-text "
                "or migrate and re-index the knowledge base for the new model."
            )
        return vector

    def ingest_document(
        self,
        db: Session,
        *,
        title: str,
        content: str,
        source_type: KnowledgeSourceType,
        source_uri: str | None = None,
        metadata: dict[str, Any] | None = None,
        created_by_user_id: int | None = None,
    ) -> KnowledgeDocument:
        normalized = normalize_text(content)
        if not normalized:
            raise ValueError("Knowledge document content cannot be empty")
        if not title.strip():
            raise ValueError("Knowledge document title cannot be empty")

        content_hash = sha256(normalized.encode("utf-8")).hexdigest()
        existing = db.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.content_hash == content_hash
            )
        )
        if existing:
            stored_model = existing.metadata_json.get("embedding_model")
            if stored_model != self.embedding_model:
                raise ValueError(
                    "This document was indexed with a different embedding model. "
                    "Re-index its existing chunks before switching embedding models."
                )
            return existing

        chunks = chunk_text(
            normalized,
            max_chars=self.chunk_size,
            overlap_chars=self.chunk_overlap,
        )
        # Validate all vectors before inserting a document or any of its chunks.
        embeddings = [self._embed(db, chunk) for chunk in chunks]

        document = KnowledgeDocument(
            title=title.strip(),
            source_type=source_type,
            source_uri=source_uri,
            content_hash=content_hash,
            metadata_json={
                **(metadata or {}),
                "embedding_model": self.embedding_model,
            },
            created_by_user_id=created_by_user_id,
        )
        db.add(document)
        db.flush()

        for index, chunk in enumerate(chunks):
            db.add(
                KnowledgeChunk(
                    document_id=document.id,
                    chunk_index=index,
                    content=chunk,
                    embedding=embeddings[index],
                    metadata_json={
                        "title": document.title,
                        "embedding_model": document.metadata_json[
                            "embedding_model"
                        ],
                    },
                )
            )

        db.commit()
        db.refresh(document)
        return document

    def search(
        self,
        db: Session,
        query: str,
        *,
        top_k: int = 5,
        min_score: float = 0.0,
        source_type: KnowledgeSourceType | None = KnowledgeSourceType.PREVIOUS_JOB_DESCRIPTION,
    ) -> list[RetrievedKnowledgeChunk]:
        if not query.strip():
            raise ValueError("Knowledge search query cannot be empty")
        if top_k < 1:
            raise ValueError("top_k must be positive")

        query_embedding = self._embed(db, query)
        if not any(query_embedding):
            return []
        if db.get_bind().dialect.name == "postgresql":
            return self._postgres_search(
                db, query_embedding, top_k=top_k, min_score=min_score,
                source_type=source_type,
            )

        # Deterministic SQLite fallback for tests, never used by PostgreSQL.
        statement = select(KnowledgeChunk, KnowledgeDocument).join(
            KnowledgeDocument,
            KnowledgeDocument.id == KnowledgeChunk.document_id,
        )
        if source_type is not None:
            statement = statement.where(
                KnowledgeDocument.source_type == source_type
            )

        matches: list[RetrievedKnowledgeChunk] = []
        for chunk, document in db.execute(statement):
            stored_model = chunk.metadata_json.get("embedding_model") or document.metadata_json.get("embedding_model")
            if stored_model != self.embedding_model:
                continue
            if len(query_embedding) != len(chunk.embedding):
                continue
            score = cosine_similarity(query_embedding, chunk.embedding)
            if score >= min_score:
                matches.append(
                    RetrievedKnowledgeChunk(
                        document_id=document.id,
                        document_title=document.title,
                        source_type=document.source_type,
                        chunk_id=chunk.id,
                        chunk_index=chunk.chunk_index,
                        content=chunk.content,
                        score=score,
                        source_uri=document.source_uri,
                    )
                )

        matches.sort(key=lambda match: match.score, reverse=True)
        return matches[:top_k]

    def _postgres_search(
        self, db: Session, query_embedding: list[float], *, top_k: int,
        min_score: float, source_type: KnowledgeSourceType | None,
    ) -> list[RetrievedKnowledgeChunk]:
        distance = KnowledgeChunk.embedding.cosine_distance(query_embedding)
        nearest = (
            select(
                KnowledgeChunk.id.label("chunk_id"), KnowledgeChunk.document_id,
                KnowledgeChunk.chunk_index, KnowledgeChunk.content,
                distance.label("distance"),
            )
            .where(
                KnowledgeChunk.metadata_json["embedding_model"].as_string() == self.embedding_model,
                distance <= 1 - min_score,
            )
            # Order by distance directly so PostgreSQL can use vector_cosine_ops.
            .order_by(distance)
            .limit(top_k)
        )
        if source_type is not None:
            nearest = nearest.where(KnowledgeChunk.document_id.in_(
                select(KnowledgeDocument.id).where(KnowledgeDocument.source_type == source_type),
            ))
        nearest = nearest.subquery("nearest_chunks")
        # LIMIT in the subquery keeps the document join after nearest-neighbor
        # retrieval, and avoids fetching vector values into application memory.
        statement = (
            select(
                nearest.c.chunk_id, KnowledgeDocument.id.label("document_id"),
                KnowledgeDocument.title.label("document_title"),
                KnowledgeDocument.source_type, nearest.c.chunk_index,
                nearest.c.content, (1 - nearest.c.distance).label("score"),
                KnowledgeDocument.source_uri,
            )
            .join(KnowledgeDocument, KnowledgeDocument.id == nearest.c.document_id)
            .order_by(nearest.c.distance)
        )
        # Continue scanning after metadata filters, rather than returning too few hits.
        db.execute(text("SET LOCAL hnsw.iterative_scan = 'strict_order'"))
        return [
            RetrievedKnowledgeChunk(**row)
            for row in db.execute(statement).mappings()
        ]

    @staticmethod
    def list_documents(db: Session, source_type=KnowledgeSourceType.PREVIOUS_JOB_DESCRIPTION) -> list[KnowledgeDocument]:
        return list(
            db.scalars(
                select(KnowledgeDocument).where(KnowledgeDocument.source_type == source_type).order_by(
                    KnowledgeDocument.created_at.desc()
                )
            )
        )

    @staticmethod
    def delete_document(db: Session, document_id: int) -> None:
        document = db.get(KnowledgeDocument, document_id)
        if document is None:
            raise LookupError("Knowledge document not found")
        db.delete(document)
        db.commit()
