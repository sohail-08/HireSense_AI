from hashlib import sha256
import math
import re
from typing import Protocol


class EmbeddingProvider(Protocol):
    dimension: int

    def embed(self, text: str) -> list[float]:
        ...


class HashEmbeddingProvider:
    """Deterministic, dependency-free embedding provider for local development.

    This is deliberately an offline baseline, not a replacement for a semantic
    model. The provider interface allows an LLM or sentence-transformer
    embedding provider to be introduced without changing the knowledge schema.
    """

    def __init__(self, dimension: int = 128):
        if dimension < 8:
            raise ValueError("Embedding dimension must be at least 8")
        self.dimension = dimension

    def embed(self, text: str) -> list[float]:
        tokens = re.findall(r"[a-z0-9][a-z0-9+#.-]*", text.lower())
        vector = [0.0] * self.dimension
        for token in tokens:
            digest = sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 else -1.0
            vector[index] += sign

        magnitude = math.sqrt(sum(value * value for value in vector))
        if magnitude == 0:
            return vector
        return [value / magnitude for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("Embedding vectors must have the same dimension")
    return sum(a * b for a, b in zip(left, right, strict=True))
