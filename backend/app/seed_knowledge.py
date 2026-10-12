import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.knowledge import KnowledgeDocument
from app.models.user import User, UserRole
from app.rag.chunking import normalize_text
from app.rag.embeddings import EmbeddingProvider, OllamaEmbeddingProvider
from app.rag.service import KnowledgeBaseService
from app.schemas.knowledge import KnowledgeDocumentCreate


DATASET_PATH = Path(__file__).parent / "data" / "synthetic_knowledge.json"
LEGACY_SYNTHETIC_SOURCE_URIS = (
    "synthetic://policy/engineering-hiring-2025",
    "synthetic://policy/engineering-interview-rubric-2025",
)


@dataclass(frozen=True)
class SeedKnowledgeSummary:
    added: int
    existing: int
    document_ids: list[int]


def load_synthetic_knowledge(
    path: Path = DATASET_PATH,
) -> list[KnowledgeDocumentCreate]:
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("Synthetic knowledge dataset must be a JSON array")
    return [KnowledgeDocumentCreate.model_validate(record) for record in records]


def seed_synthetic_knowledge(
    db: Session,
    embedding_provider: EmbeddingProvider | None = None,
) -> SeedKnowledgeSummary:
    service = KnowledgeBaseService(
        embedding_provider or OllamaEmbeddingProvider()
    )
    legacy_documents = list(
        db.scalars(
            select(KnowledgeDocument).where(
                KnowledgeDocument.source_uri.in_(
                    LEGACY_SYNTHETIC_SOURCE_URIS
                )
            )
        )
    )
    for document in legacy_documents:
        db.delete(document)
    if legacy_documents:
        db.commit()

    interviewer_id = db.scalar(
        select(User.id).where(User.role == UserRole.INTERVIEWER)
    )
    added = 0
    existing = 0
    document_ids: list[int] = []

    for record in load_synthetic_knowledge():
        normalized = normalize_text(record.content)
        content_hash = sha256(normalized.encode("utf-8")).hexdigest()
        already_exists = db.scalar(
            select(KnowledgeDocument.id).where(
                KnowledgeDocument.content_hash == content_hash
            )
        )
        document = service.ingest_document(
            db,
            title=record.title,
            content=record.content,
            source_type=record.source_type,
            source_uri=record.source_uri,
            metadata=record.metadata,
            created_by_user_id=interviewer_id,
        )
        document_ids.append(document.id)
        if already_exists is None:
            added += 1
        else:
            existing += 1

    return SeedKnowledgeSummary(
        added=added,
        existing=existing,
        document_ids=document_ids,
    )


def main() -> None:
    with SessionLocal() as db:
        summary = seed_synthetic_knowledge(db)
    print(
        "Synthetic knowledge seed complete: "
        f"{summary.added} added, {summary.existing} already present."
    )


if __name__ == "__main__":
    main()
