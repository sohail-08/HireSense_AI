from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import (
    KnowledgeDocument,
    KnowledgeSourceType,
    User,
    UserRole,
)
from app.rag.embeddings import HashEmbeddingProvider
from app.rag.service import KnowledgeBaseService
from app.seed_knowledge import load_synthetic_knowledge, seed_synthetic_knowledge


def test_synthetic_dataset_is_valid_and_clearly_labelled():
    records = load_synthetic_knowledge()

    assert len(records) == 6
    assert all(record.metadata["synthetic"] is True for record in records)
    assert all(record.source_uri.startswith("synthetic://") for record in records)
    assert all(
        record.source_type.value == "previous_job_description"
        for record in records
    )
    assert any("Backend Engineer" in record.title for record in records)
    assert any("DevOps Engineer" in record.title for record in records)


def test_synthetic_knowledge_seed_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'knowledge-seed.db'}")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        interviewer = User(
            name="Interviewer",
            email="knowledge-seed@example.com",
            password_hash="hashed-password",
            role=UserRole.INTERVIEWER,
        )
        db.add(interviewer)
        db.commit()

        KnowledgeBaseService(HashEmbeddingProvider()).ingest_document(
            db,
            title="Legacy synthetic policy",
            content="Legacy synthetic content that should be removed.",
            source_type=KnowledgeSourceType.PREVIOUS_JOB_DESCRIPTION,
            source_uri="synthetic://policy/engineering-hiring-2025",
        )

        first = seed_synthetic_knowledge(db, HashEmbeddingProvider())
        second = seed_synthetic_knowledge(db, HashEmbeddingProvider())
        document_count = db.scalar(
            select(func.count(KnowledgeDocument.id))
        )

    assert first.added == 6
    assert first.existing == 0
    assert second.added == 0
    assert second.existing == 6
    assert first.document_ids == second.document_ids
    assert document_count == 6
