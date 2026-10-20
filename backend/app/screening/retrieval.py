"""Scoped exact vector retrieval. Similarity never becomes a candidate score."""
import hashlib
import json
import math
import re
import httpx
from sqlalchemy import select
from app.models.cv_evidence import CVPassage
from app.rag.embeddings import cosine_similarity

PASSAGE_VERSION = "cv-passages-900-overlap120-v1"
RETRIEVAL_VERSION = "cv-hybrid-rrf-neighbours-v1"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def passages(blocks):
    result = []
    for block in blocks:
        start, text = 0, block["text"]
        while start < len(text):
            end = min(start + 900, len(text))
            if end < len(text):
                boundary = max(text.rfind("\n", start + 450, end), text.rfind(". ", start + 450, end))
                if boundary >= 0: end = boundary + 1
            key = block["id"] if start == 0 and end == len(text) else f"{block['id']}~{start}-{end}"
            result.append({"id": key, "text": text[start:end], "locator": block["locator"],
                "source_block_id": block["id"], "char_start": start, "char_end": end})
            if end == len(text): break
            start = end - 120
    return result


class PinnedCVEncoder:
    def __init__(self, settings):
        self.settings, self.pinned = settings, None

    def revision(self):
        try:
            response = httpx.get(self.settings.ollama_base_url.rstrip("/") + "/api/tags", timeout=5)
            response.raise_for_status()
            name = self.settings.ollama_embedding_model
            name = name if ":" in name else name + ":latest"
            found = next((m for m in response.json()["models"] if m.get("name") == name or m.get("model") == name), None)
            if not found or not re.fullmatch(r"(?:sha256:)?[a-f0-9]{64}", found.get("digest", "")):
                raise ValueError()
            return {"model": name, "digest": found["digest"], "prefix": "nomic-search-v1" if name.startswith("nomic-embed-text") else "plain-v1"}
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            raise RuntimeError("The CV embedding model is unavailable. Start Ollama and retry screening; no zero score has been assigned.") from None

    def identity(self):
        if self.pinned is None: self.pinned = self.revision()
        return self.pinned

    def embed_many(self, texts, *, query=False):
        identity = self.identity()
        if identity != self.revision(): raise RuntimeError("The embedding model changed during screening. Retry with a stable model.")
        prefix = ("search_query: " if query else "search_document: ") if identity["prefix"] == "nomic-search-v1" else ""
        vectors = []
        try:
            for start in range(0, len(texts), 16):
                batch = texts[start:start + 16]
                response = httpx.post(self.settings.ollama_base_url.rstrip("/") + "/api/embed",
                    json={"model": identity["model"], "input": [prefix + t for t in batch], "truncate": False},
                    timeout=self.settings.ollama_timeout_seconds)
                response.raise_for_status()
                part = response.json()["embeddings"]
                if len(part) != len(batch): raise ValueError()
                vectors.extend(part)
            if identity != self.revision(): raise ValueError()
            return vectors
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            raise RuntimeError("CV evidence embeddings could not finish. Retry screening; no zero score has been assigned.") from None


def tokens(text):
    text = text.lower().replace("react.js", "react").replace("node.js", "nodejs").replace("postgresql", "postgres")
    values = set(re.findall(r"[a-z0-9][a-z0-9+#]*", text))
    for short, long in (("js", "javascript"), ("ts", "typescript")):
        if short in values: values.add(long)
    return values - {"a", "an", "the", "and", "or", "of", "in", "with", "for", "required", "experience", "skills"}


class CVSemanticRetriever:
    def __init__(self, settings, encoder=None):
        self.encoder = encoder or PinnedCVEncoder(settings)
        self.top_k = settings.screening_evidence_top_k
        self.query_cache = {}

    def identity(self):
        return {"encoder": self.encoder.identity(), "passages": PASSAGE_VERSION, "retrieval": RETRIEVAL_VERSION, "top_k": self.top_k}

    @staticmethod
    def validate_vectors(db, vectors, expected_count):
        if len(vectors) != expected_count: raise ValueError("Incomplete CV embeddings")
        dimensions = {len(v) for v in vectors}
        if len(dimensions) != 1 or not next(iter(dimensions), 0): raise ValueError("Inconsistent CV embedding dimensions")
        if db.get_bind().dialect.name == "postgresql" and dimensions != {768}:
            raise ValueError("CV evidence requires a 768-dimensional embedding model")
        if any(not all(math.isfinite(float(x)) for x in v) or not any(float(x) for x in v) for v in vectors):
            raise ValueError("CV embedding returned an invalid vector")

    def prepare(self, db, document, blocks, requirements):
        encoder = digest({"encoder": self.encoder.identity(), "passages": PASSAGE_VERSION,
            "file": document.sha256, "source": digest(blocks)})
        split = passages(blocks)
        if not split or len(split) > 512 or len(requirements) > 60:
            raise ValueError("The CV or requirement profile exceeds the bounded screening complexity limit; no candidate score was assigned")
        saved = list(db.scalars(select(CVPassage).where(CVPassage.document_id == document.id,
            CVPassage.encoder == encoder, CVPassage.cv_sha256 == document.sha256).order_by(CVPassage.id)))
        if saved and [(r.passage_id, r.content) for r in saved] != [(p["id"], p["text"]) for p in split]:
            raise ValueError("Stored CV passages do not match the source CV")
        if not saved:
            vectors = self.encoder.embed_many([p["text"] for p in split])
            self.validate_vectors(db, vectors, len(split))
            saved = [CVPassage(document_id=document.id, cv_sha256=document.sha256, encoder=encoder,
                passage_id=p["id"], source_block_id=p["source_block_id"], char_start=p["char_start"], char_end=p["char_end"],
                locator=p["locator"], content=p["text"], embedding=v) for p,v in zip(split, vectors, strict=True)]
            db.add_all(saved)
            db.flush()
        self.validate_vectors(db, [r.embedding for r in saved], len(split))
        queries = [r["name"] + ". " + (r.get("details") or "") for r in requirements]
        missing = list(dict.fromkeys(q for q in queries if q not in self.query_cache))
        if missing:
            vectors = self.encoder.embed_many(missing, query=True)
            self.validate_vectors(db, vectors, len(missing))
            self.query_cache.update(zip(missing, vectors, strict=True))
        output = []
        for requirement, query in zip(requirements, queries, strict=True):
            vector = self.query_cache[query]
            if len(vector) != len(saved[0].embedding): raise ValueError("Query and CV embedding dimensions differ")
            if db.get_bind().dialect.name == "postgresql":
                semantic = list(db.scalars(select(CVPassage).where(CVPassage.document_id == document.id,
                    CVPassage.encoder == encoder, CVPassage.cv_sha256 == document.sha256)
                    .order_by(CVPassage.embedding.cosine_distance(vector), CVPassage.passage_id).limit(self.top_k)))
            else:
                semantic = sorted(saved, key=lambda p: (-cosine_similarity(p.embedding, vector), p.passage_id))[:self.top_k]
            terms = tokens(query)
            lexical = sorted(saved, key=lambda p: (-len(tokens(p.content) & terms), p.passage_id))
            lexical = [p for p in lexical if tokens(p.content) & terms][:self.top_k]
            ranks = {}
            for hits in (semantic, lexical):
                for rank, hit in enumerate(hits, 1): ranks[hit.passage_id] = ranks.get(hit.passage_id, 0) + 1 / (60 + rank)
            keys = sorted(ranks, key=lambda key: (-ranks[key], key))[:self.top_k]
            # Adjacent text retains dates/headings needed to understand a retrieved statement.
            positions = {p["id"]: i for i,p in enumerate(split)}
            indices = {positions[key] for key in keys}
            for key in keys:
                i = positions[key]
                indices.update(j for j in (i - 1, i + 1) if 0 <= j < len(split))
            evidence = [split[i] for i in sorted(indices)]
            output.append({**requirement, "evidence_passage_ids": [p["id"] for p in evidence]})
        return split, output, {"identity": self.identity(), "passage_count": len(split),
            "retrieved_passages": {r["key"]: r["evidence_passage_ids"] for r in output}}
