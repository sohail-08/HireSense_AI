"""Idempotently index explicitly synthetic, job-related interview questions."""
import json
from pathlib import Path
from sqlalchemy import select
from app.database import SessionLocal
from app.models.knowledge import KnowledgeDocument, KnowledgeSourceType
from app.rag.embeddings import OllamaEmbeddingProvider
from app.rag.service import KnowledgeBaseService

DATASET_PATH = Path(__file__).parent / "data" / "interview_questions.json"


def seed_interview_questions(db, embedding_provider=None):
    service = KnowledgeBaseService(embedding_provider or OllamaEmbeddingProvider())
    added = 0
    for item in json.loads(DATASET_PATH.read_text(encoding="utf-8")):
        title = f"{item['role']} · {item['topic']}"
        uri = "synthetic://interview-questions/" + item["topic"].lower().replace(" ", "-")
        existing = db.scalar(select(KnowledgeDocument.id).where(KnowledgeDocument.source_uri == uri))
        service.ingest_document(db, title=title,
            content=f"Synthetic interview question\nRole: {item['role']}\nCompetency: {item['topic']}\nQuestion: {item['question']}\nDiscussion focus: {item['focus']}",
            source_type=KnowledgeSourceType.INTERVIEW_QUESTION, source_uri=uri,
            metadata={"synthetic": True, "dataset": "interview-questions-v1", "role": item["role"]})
        added += existing is None
    return added


if __name__ == "__main__":
    with SessionLocal() as db:
        added = seed_interview_questions(db)
    print(f"Interview question bank ready: {added} documents added.")
