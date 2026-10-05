from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models.knowledge import KnowledgeSourceType
from app.rag.chunking import chunk_text, normalize_text
from app.rag.embeddings import HashEmbeddingProvider
from app.rag.service import KnowledgeBaseService


def test_chunking_normalizes_and_preserves_overlap():
    text = "  Python   backend  \n\n  Build reliable APIs. "

    assert normalize_text(text) == "Python backend\n\nBuild reliable APIs."
    chunks = chunk_text("one two three four five six", max_chars=13, overlap_chars=5)

    assert chunks == ["one two three", "three four", "four five six"]


def test_hash_embeddings_are_deterministic_and_normalized():
    provider = HashEmbeddingProvider(dimension=32)
    first = provider.embed("Python backend APIs")
    second = provider.embed("Python backend APIs")

    assert first == second
    assert len(first) == 32
    assert round(sum(value * value for value in first), 6) == 1.0


def test_knowledge_ingestion_deduplicates_and_retrieves_source(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'rag.db'}")
    Base.metadata.create_all(engine)
    service = KnowledgeBaseService(
        embedding_provider=HashEmbeddingProvider(dimension=64),
        chunk_size=90,
        chunk_overlap=15,
    )

    with Session(engine) as session:
        policy = service.ingest_document(
            session,
            title="Engineering Hiring Policy",
            content=(
                "Backend candidates must demonstrate Python API experience. "
                "Candidates should explain testing and deployment decisions."
            ),
            source_type=KnowledgeSourceType.COMPANY_POLICY,
            source_uri="policy://engineering-hiring",
        )
        duplicate = service.ingest_document(
            session,
            title="Same policy with another title",
            content=(
                "Backend candidates must demonstrate Python API experience. "
                "Candidates should explain testing and deployment decisions."
            ),
            source_type=KnowledgeSourceType.COMPANY_POLICY,
        )

        assert duplicate.id == policy.id
        assert len(policy.chunks) >= 1

        results = service.search(
            session,
            "Python API experience",
            source_type=KnowledgeSourceType.COMPANY_POLICY,
        )

        assert results
        assert results[0].document_id == policy.id
        assert results[0].source_type is KnowledgeSourceType.COMPANY_POLICY
        assert "Python" in results[0].content
