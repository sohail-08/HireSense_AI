import re


def normalize_text(text: str) -> str:
    """Normalize user-provided knowledge text without changing its meaning."""
    if not isinstance(text, str):
        raise TypeError("Knowledge content must be text")

    normalized_lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    paragraphs = [line for line in normalized_lines if line]
    return "\n\n".join(paragraphs)


def chunk_text(text: str, max_chars: int = 1200, overlap_chars: int = 150) -> list[str]:
    """Split normalized text into deterministic, word-boundary chunks."""
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be between 0 and max_chars")

    normalized = normalize_text(text)
    if not normalized:
        return []
    if len(normalized) <= max_chars:
        return [normalized]

    words = normalized.split()
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0

    for word in words:
        additional_length = len(word) + (1 if current else 0)
        if current and current_length + additional_length > max_chars:
            chunk = " ".join(current)
            chunks.append(chunk)

            overlap: list[str] = []
            overlap_length = 0
            for previous_word in reversed(current):
                word_length = len(previous_word) + (1 if overlap else 0)
                if overlap_length + word_length > overlap_chars:
                    break
                overlap.insert(0, previous_word)
                overlap_length += word_length
            current = overlap
            current_length = len(" ".join(current))

        current.append(word)
        current_length += additional_length

    if current:
        chunks.append(" ".join(current))
    return chunks
