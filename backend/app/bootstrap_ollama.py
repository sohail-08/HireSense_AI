"""One-shot, credential-free Ollama setup for Docker Compose.

No application settings, database or candidate data are imported. A successful
exit means the pinned model can produce a valid 768-dimensional embedding.
"""
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

DEFAULT_MODEL = "nomic-embed-text:latest"
DEFAULT_DIGEST = "0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f"
EMBEDDING_DIMENSIONS = 768
PROBE = "search_query: HireSense embedding service readiness check."


class SetupError(RuntimeError):
    pass


def request_json(base_url, path, payload=None, *, timeout=60):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(base_url + path, data=data,
        headers={"Content-Type": "application/json"} if data is not None else {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        raise SetupError(f"Ollama {path} returned HTTP {error.code}; retry the setup service.") from None
    except (OSError, ValueError):
        raise SetupError(f"Ollama {path} is unavailable or returned invalid JSON; check the ollama service and retry.") from None
    if not isinstance(result, dict) or result.get("error"):
        raise SetupError(f"Ollama {path} did not complete successfully; check model availability and retry.")
    return result


def model_revision(tags, model):
    models = tags.get("models")
    if not isinstance(models, list):
        raise SetupError("Ollama returned an invalid model inventory.")
    found = [item for item in models if isinstance(item, dict) and (item.get("name") == model or item.get("model") == model)]
    if not found:
        return None
    digest = str(found[0].get("digest", "")).removeprefix("sha256:")
    if len(found) != 1 or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise SetupError("Ollama returned an invalid or ambiguous embedding model identity.")
    return digest


def ensure_model(base_url="http://ollama:11434", model=DEFAULT_MODEL, expected_digest=DEFAULT_DIGEST, *, request=request_json):
    base_url = base_url.rstrip("/")
    try:
        parsed = urlsplit(base_url)
    except ValueError:
        raise SetupError("Provide a valid HTTP(S) Ollama base URL.") from None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SetupError("Provide an HTTP(S) Ollama base URL without credentials, query parameters or fragments.")
    if not re.fullmatch(r"[a-zA-Z0-9_./:-]+", model) or len(model) > 200:
        raise SetupError("Provide a valid embedding model name.")
    if ":" not in model.rsplit("/", 1)[-1]:
        model += ":latest"
    expected_digest = expected_digest.removeprefix("sha256:")
    if not re.fullmatch(r"[a-f0-9]{64}", expected_digest):
        raise SetupError("A valid pinned embedding model digest is required.")
    revision = model_revision(request(base_url, "/api/tags", timeout=15), model)
    reused_cache = revision is not None
    if revision is None:
        print(f"Downloading {model} into the persistent Ollama volume (first setup may take several minutes).", flush=True)
        result = request(base_url, "/api/pull", {"model": model, "stream": False}, timeout=1800)
        if result.get("status") != "success":
            raise SetupError("Embedding model download did not finish; check internet access and retry ollama-init.")
        revision = model_revision(request(base_url, "/api/tags", timeout=15), model)
    if revision != expected_digest:
        raise SetupError("Embedding model digest differs from the pinned revision. Setup stopped to protect saved vectors; do not mix model revisions.")
    response = request(base_url, "/api/embed", {"model": model, "input": PROBE, "truncate": False}, timeout=120)
    vectors = response.get("embeddings")
    vector = vectors[0] if isinstance(vectors, list) and len(vectors) == 1 else None
    if not isinstance(vector, list) or len(vector) != EMBEDDING_DIMENSIONS or not all(
        isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) for value in vector
    ) or not any(vector):
        raise SetupError("Embedding readiness check must return one finite, nonzero 768-dimensional vector.")
    if model_revision(request(base_url, "/api/tags", timeout=15), model) != expected_digest:
        raise SetupError("Embedding model changed during setup. Retry with a stable pinned revision.")
    return {"status": "ready", "model": model, "digest": revision, "dimensions": EMBEDDING_DIMENSIONS, "reused_cache": reused_cache}


def main():
    try:
        result = ensure_model(os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"),
            os.getenv("OLLAMA_EMBEDDING_MODEL", DEFAULT_MODEL), os.getenv("OLLAMA_MODEL_DIGEST", DEFAULT_DIGEST))
    except SetupError as error:
        print(f"Ollama setup failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
