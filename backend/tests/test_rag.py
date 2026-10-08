from sqlalchemy import create_engine
from sqlalchemy.orm import Session
import pytest

from app.database import Base
from app.models.knowledge import KnowledgeDocument, KnowledgeSourceType
from app.rag.chunking import chunk_text, normalize_text
from app.rag.embeddings import HashEmbeddingProvider, cosine_similarity
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
        previous_jd = service.ingest_document(
            session,
            title="Backend Engineer JD 2025",
            content=(
                "Backend candidates must demonstrate Python API experience. "
                "Candidates should explain testing and deployment decisions."
            ),
            source_type=KnowledgeSourceType.PREVIOUS_JOB_DESCRIPTION,
            source_uri="previous-jd://backend-engineer-2025",
        )
        duplicate = service.ingest_document(
            session,
            title="Same previous JD with another title",
            content=(
                "Backend candidates must demonstrate Python API experience. "
                "Candidates should explain testing and deployment decisions."
            ),
            source_type=KnowledgeSourceType.PREVIOUS_JOB_DESCRIPTION,
        )

        assert duplicate.id == previous_jd.id
        assert len(previous_jd.chunks) >= 1

        results = service.search(
            session,
            "Python API experience",
            source_type=KnowledgeSourceType.PREVIOUS_JOB_DESCRIPTION,
        )

        assert results
        assert results[0].document_id == previous_jd.id
        assert (
            results[0].source_type
            is KnowledgeSourceType.PREVIOUS_JOB_DESCRIPTION
        )
        assert "Python" in results[0].content


def test_cosine_similarity_handles_unnormalized_and_zero_vectors():
    assert cosine_similarity([2, 0], [4, 3]) == pytest.approx(0.8)
    assert cosine_similarity([0, 0], [1, 2]) == 0
    with pytest.raises(ValueError, match="same dimension"):
        cosine_similarity([1], [1, 2])


def test_search_excludes_embeddings_from_another_model(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'different-models.db'}")
    Base.metadata.create_all(engine)
    provider = HashEmbeddingProvider(dimension=64)
    provider.model = "old-model"
    service = KnowledgeBaseService(provider)
    with Session(engine) as db:
        service.ingest_document(db, title="Previous JD", content="Python APIs", source_type=KnowledgeSourceType.PREVIOUS_JOB_DESCRIPTION)
        provider.model = "new-model"
        assert service.search(db, "Python APIs") == []
        with pytest.raises(ValueError, match="different embedding model"):
            service.ingest_document(db, title="Same JD", content="Python APIs", source_type=KnowledgeSourceType.PREVIOUS_JOB_DESCRIPTION)


def test_failed_embedding_generation_leaves_no_partial_document(tmp_path):
    class FailingProvider:
        dimension = 768
        calls = 0

        def embed(self, _text):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("Embedding service unavailable")
            return [1.0] * self.dimension

    engine = create_engine(f"sqlite:///{tmp_path / 'failed-ingestion.db'}")
    Base.metadata.create_all(engine)
    service = KnowledgeBaseService(FailingProvider(), chunk_size=20, chunk_overlap=5)
    with Session(engine) as db:
        with pytest.raises(RuntimeError, match="unavailable"):
            service.ingest_document(db, title="Previous JD", content="Python APIs and PostgreSQL services with tests and deployment.", source_type=KnowledgeSourceType.PREVIOUS_JOB_DESCRIPTION)
        db.commit()
        assert db.query(KnowledgeDocument).count() == 0
