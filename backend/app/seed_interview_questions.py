"""Idempotently index explicitly synthetic, job-related interview questions."""
import json
from pathlib import Path
from hashlib import sha256
from sqlalchemy import select, delete
from app.database import SessionLocal
from app.models.knowledge import KnowledgeDocument, KnowledgeChunk, KnowledgeSourceType
from app.rag.embeddings import OllamaEmbeddingProvider
from app.rag.service import KnowledgeBaseService
from app.rag.chunking import chunk_text, normalize_text

DATASET_PATH = Path(__file__).parent / "data" / "interview_questions.json"


def seed_interview_questions(db, embedding_provider=None):
    service = KnowledgeBaseService(embedding_provider or OllamaEmbeddingProvider(), chunk_size=3200)
    added = 0
    for item in json.loads(DATASET_PATH.read_text(encoding="utf-8")):
        title = f"{item['role']} · {item['topic']}"
        uri = "synthetic://interview-questions/" + item["topic"].lower().replace(" ", "-")
        existing = db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.source_uri == uri))
        content = normalize_text(f"Synthetic interview question and answer guide\nRole: {item['role']}\nCompetency: {item['topic']}\n"
            f"Question: {item['question']}\nDiscussion focus: {item['focus']}\nAnswer guide: {item['answer_guide']}\n"
            f"Expected elements for the example question only: {'; '.join(item['expected_elements'])}\n"
            "For a different spoken question, assess only its requested subparts using the applicable guide passages.\n"
            + (f"Sources: {' '.join(item['sources'])}\n" if item.get('sources') else "") +
            "Scoring: Credit equivalent correct explanations and relevant examples. Partial coverage receives partial credit. "
            "Do not require identical wording or assess speech style.")
        metadata = {"synthetic": True, "dataset": "interview-questions-v2", "role": item["role"],
                    "question": item["question"], "answer_guide": item["answer_guide"], "expected_elements": item["expected_elements"],
                    "sources": item.get("sources", [])}
        if existing:
            if existing.metadata_json.get("synthetic") is not True or existing.metadata_json.get("dataset") not in {"interview-questions-v1", "interview-questions-v2"}:
                raise ValueError("Refusing to replace a question-bank source not owned by the synthetic dataset")
            content_hash = sha256(content.encode()).hexdigest()
            if existing.content_hash == content_hash:
                continue
            if existing.metadata_json.get("embedding_model") != service.embedding_model:
                raise ValueError("Re-index the existing question bank before changing its embedding model")
            chunks = chunk_text(content, max_chars=service.chunk_size, overlap_chars=service.chunk_overlap)
            # Complete embeddings before touching the old document or its chunks.
            embeddings = [service._embed(db, chunk) for chunk in chunks]
            db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == existing.id))
            existing.title, existing.content_hash = title, content_hash
            existing.metadata_json = {**metadata, "embedding_model": service.embedding_model}
            for index, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                db.add(KnowledgeChunk(document_id=existing.id, chunk_index=index, content=chunk, embedding=embedding,
                    metadata_json={"title": title, "embedding_model": service.embedding_model}))
            db.commit()
            db.expire(existing, ["chunks"])
            continue
        service.ingest_document(db, title=title,
            content=content,
            source_type=KnowledgeSourceType.INTERVIEW_QUESTION, source_uri=uri,
            metadata=metadata)
        added += existing is None
    return added


if __name__ == "__main__":
    with SessionLocal() as db:
        added = seed_interview_questions(db)
    print(f"Interview question bank ready: {added} documents added.")
