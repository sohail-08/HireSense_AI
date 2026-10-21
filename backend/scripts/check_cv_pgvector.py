"""Opt-in rollback-only probe using synthetic text, local embeddings and PostgreSQL.

Uses two existing CV IDs only to satisfy foreign keys. Never reads their text,
changes CV records, or calls Gemini. All synthetic passage inserts are rolled back.
"""
import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Allow rollback-only PostgreSQL/local Ollama probe.")
    if not parser.parse_args().run:
        parser.error("Explicit --run is required")
    from sqlalchemy import select, func, text
    from app.config import get_settings
    from app.database import SessionLocal
    from app.models import CVDocument, CVPassage
    from app.screening.retrieval import CVSemanticRetriever, digest
    marker = digest("HireSense rollback-only synthetic pgvector probe v1")
    with SessionLocal() as db:
        if db.get_bind().dialect.name != "postgresql":
            raise RuntimeError("This probe requires PostgreSQL")
        ids = list(db.scalars(select(CVDocument.id).order_by(CVDocument.id).limit(2)))
        if len(ids) < 2:
            raise RuntimeError("This probe requires two existing CV IDs; no business data will be created")
        before = db.scalar(select(func.count()).select_from(CVPassage).where(CVPassage.cv_sha256 == marker))
        try:
            retriever = CVSemanticRetriever(get_settings())
            requirement = {"key": "required_skill:0", "category": "required_skill", "name": "Python web development", "details": None, "weight": 1}
            sources = [
                [{"id": "synthetic-python", "locator": "Synthetic probe", "text": "Built production REST services using Django."}],
                [{"id": "synthetic-other", "locator": "Synthetic probe", "text": "Built React user interfaces."}],
            ]
            for identifier, blocks in zip(ids, sources, strict=True):
                retriever.prepare(db, SimpleNamespace(id=identifier, sha256=marker), blocks, [requirement])
            _, matches, _ = retriever.prepare(db, SimpleNamespace(id=ids[0], sha256=marker), sources[0], [requirement])
            assert matches[0]["evidence_passage_ids"] == ["synthetic-python"]
            vector = db.scalar(select(CVPassage.embedding).where(CVPassage.document_id == ids[0], CVPassage.cv_sha256 == marker))
            assert len(vector) == 768
            column_type = db.scalar(text("SELECT format_type(atttypid,atttypmod) FROM pg_attribute WHERE attrelid='cv_passages'::regclass AND attname='embedding'"))
            assert column_type == "vector(768)"
        finally:
            db.rollback()
        after = db.scalar(select(func.count()).select_from(CVPassage).where(CVPassage.cv_sha256 == marker))
        assert after == before
        print(json.dumps({"pgvector": column_type, "isolated_retrieval": True, "synthetic_inserts_rolled_back": True}))


if __name__ == "__main__":
    main()
