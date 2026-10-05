from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.knowledge import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSourceType,
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
            return existing

        document = KnowledgeDocument(
            title=title.strip(),
            source_type=source_type,
            source_uri=source_uri,
            content_hash=content_hash,
            metadata_json={
                **(metadata or {}),
                "embedding_model": getattr(
                    self.embedding_provider,
                    "model",
                    self.embedding_provider.__class__.__name__,
                ),
            },
            created_by_user_id=created_by_user_id,
        )
        db.add(document)
        db.flush()

        chunks = chunk_text(
            normalized,
            max_chars=self.chunk_size,
            overlap_chars=self.chunk_overlap,
        )
        for index, chunk in enumerate(chunks):
            db.add(
                KnowledgeChunk(
                    document_id=document.id,
                    chunk_index=index,
                    content=chunk,
                    embedding=self.embedding_provider.embed(chunk),
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
        source_type: KnowledgeSourceType | None = None,
    ) -> list[RetrievedKnowledgeChunk]:
        if not query.strip():
            raise ValueError("Knowledge search query cannot be empty")
        if top_k < 1:
            raise ValueError("top_k must be positive")

        statement = select(KnowledgeChunk, KnowledgeDocument).join(
            KnowledgeDocument,
            KnowledgeDocument.id == KnowledgeChunk.document_id,
        )
        if source_type is not None:
            statement = statement.where(
                KnowledgeDocument.source_type == source_type
            )

        query_embedding = self.embedding_provider.embed(query)
        if not any(query_embedding):
            return []
        matches: list[RetrievedKnowledgeChunk] = []
        for chunk, document in db.execute(statement):
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

    @staticmethod
    def list_documents(db: Session) -> list[KnowledgeDocument]:
        return list(
            db.scalars(
                select(KnowledgeDocument).order_by(
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
