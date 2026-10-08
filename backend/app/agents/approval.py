import re


def is_explicit_approval(message: str) -> bool:
    """Accept confirmation/approval commands, not an LLM's rewritten intent."""
    text = " ".join(message.casefold().replace("’", "'").split()).strip(".! ")
    if re.search(r"\b(?:not|don't|dont|never|without|reject|cancel|unapprove)\b", text):
        return False
    if text in {
        "yes", "yes please", "approve", "approved", "confirm", "confirmed",
        "go ahead", "looks good", "ok", "okay",
    }:
        return True
    return bool(re.match(
        r"^(?:(?:yes|ok(?:ay)?)[,!]?\s+|go ahead and\s+)?"
        r"(?:(?:can|could|would) you\s+)?(?:please\s+)?"
        r"(?:approve|confirm|publish)\b",
        text,
    ))
