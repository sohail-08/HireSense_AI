"""Real PostgreSQL/pgvector integration tests on disposable databases.

Set PGVECTOR_TEST_SERVER_URL to a PostgreSQL server with the extension installed.
Each test creates and removes only its own randomly named test database.
"""

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeSourceType
from app.rag.service import KnowledgeBaseService


@pytest.fixture
def pg_database():
    url = os.environ.get("PGVECTOR_TEST_SERVER_URL")
    if not url:
        pytest.skip("Set PGVECTOR_TEST_SERVER_URL to run real pgvector tests")
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    name = f"hiresense_pgvector_test_{uuid4().hex}"
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(url).set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


def _config(url):
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.attributes["database_url"] = url
    return config


def _vector(first, second=0):
    return [first, second] + [0.0] * 766


def _legacy_chunk(connection, vector):
    document_id = connection.scalar(text("""
        INSERT INTO knowledge_documents
            (title, source_type, content_hash, metadata_json, created_at, updated_at)
        VALUES ('Legacy JD', 'previous_job_description', :hash,
            '{"embedding_model":"nomic-embed-text:latest"}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        RETURNING id
    """), {"hash": "a" * 64})
    connection.execute(text("""
        INSERT INTO knowledge_chunks (document_id, chunk_index, content, embedding, metadata_json, created_at)
        VALUES (:document_id, 0, 'Legacy job description', CAST(:embedding AS json),
            '{"embedding_model":"nomic-embed-text:latest"}', CURRENT_TIMESTAMP)
    """), {"document_id": document_id, "embedding": json.dumps(vector)})
    return document_id


def test_migration_preserves_existing_embeddings_and_downgrades(pg_database):
    config = _config(pg_database)
    command.upgrade(config, "0013_cv_screening_and_ranking")
    engine = create_engine(pg_database)
    original = _vector(0.123456789, 2.5)
    with engine.begin() as connection:
        document_id = _legacy_chunk(connection, original)
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))
        assert connection.scalar(text("SELECT format_type(atttypid, atttypmod) FROM pg_attribute WHERE attrelid = 'knowledge_chunks'::regclass AND attname = 'embedding'")) == "vector(768)"
        assert "vector_cosine_ops" in connection.scalar(text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_knowledge_chunks_embedding_hnsw'"))
    with Session(engine) as db:
        chunk = db.scalar(select(KnowledgeChunk))
        assert chunk.document_id == document_id
        assert list(chunk.embedding) == pytest.approx(original, abs=1e-7)
        assert chunk.content == "Legacy job description"
    command.downgrade(config, "0013_cv_screening_and_ranking")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT embedding FROM knowledge_chunks")) == pytest.approx(original, abs=1e-7)
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM knowledge_chunks")) == 1
    engine.dispose()


def test_wrong_dimension_migration_is_transactional(pg_database):
    config = _config(pg_database)
    command.upgrade(config, "0013_cv_screening_and_ranking")
    engine = create_engine(pg_database)
    with engine.begin() as connection:
        _legacy_chunk(connection, [1, 2, 3])
    with pytest.raises(RuntimeError, match="768 dimensions"):
        command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT embedding FROM knowledge_chunks")) == [1, 2, 3]
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0013_cv_screening_and_ranking"
    engine.dispose()


class StaticProvider:
    model = "pgvector-integration-test"
    dimension = 768

    def embed(self, content):
        return {"exact": _vector(2), "similar": _vector(4, 3), "other": _vector(0, 9), "query": _vector(3)}[content]


def test_database_cosine_search_filters_models_and_uses_hnsw(pg_database):
    command.upgrade(_config(pg_database), "head")
    engine = create_engine(pg_database)
    service = KnowledgeBaseService(StaticProvider())
    statements = []
    def capture(_connection, _cursor, statement, params, _context, _many):
        if "<=>" in statement and not statement.startswith("EXPLAIN"):
            statements.append((statement, params))
    event.listen(engine, "before_cursor_execute", capture)
    with Session(engine) as db:
        for content in ("exact", "similar", "other"):
            service.ingest_document(db, title=content, content=content, source_type=KnowledgeSourceType.PREVIOUS_JOB_DESCRIPTION)
        wrong_model = db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.title == "other"))
        wrong_model.chunks[0].embedding = _vector(2)
        wrong_model.chunks[0].metadata_json = {"embedding_model": "a-different-model"}
        db.commit()
        hits = service.search(db, "query", top_k=2)
        assert [hit.document_title for hit in hits] == ["exact", "similar"]
        assert [hit.score for hit in hits] == pytest.approx([1.0, 0.8], abs=1e-6)
        assert len(service.search(db, "query", min_score=0.9)) == 1
        assert service.search(db, "query", min_score=1.1) == []
        sql, params = statements[0]
        assert "ORDER BY" in sql and "LIMIT" in sql
        db.execute(text("SET LOCAL enable_seqscan = off"))
        plan = db.connection().exec_driver_sql("EXPLAIN " + sql, params).scalars().all()
        assert any("ix_knowledge_chunks_embedding_hnsw" in line for line in plan), "\n".join(plan)
    engine.dispose()


def test_ingestion_rejects_incompatible_vectors_before_inserting(pg_database):
    command.upgrade(_config(pg_database), "head")
    engine = create_engine(pg_database)
    class WrongDimensions:
        dimension = 3
        model = "wrong-model"
        def embed(self, _content):
            return [1, 2, 3]
    with Session(engine) as db:
        with pytest.raises(ValueError, match="require 768 dimensions"):
            KnowledgeBaseService(WrongDimensions()).ingest_document(db, title="JD", content="Backend Engineer", source_type=KnowledgeSourceType.PREVIOUS_JOB_DESCRIPTION)
        db.commit()
        assert db.query(KnowledgeDocument).count() == 0
    engine.dispose()
