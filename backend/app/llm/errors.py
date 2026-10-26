"""Safe provider/scoring failure categories. Never expose exception payloads."""
from pydantic import ValidationError


class ProviderError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class ScoringError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


MESSAGES = {
    "authentication": "The AI service credentials need attention. Ask the administrator to check the configured API key.",
    "quota": "The AI service quota is exhausted or rate-limited. Wait for the quota to recover before retrying.",
    "timeout": "The AI service timed out. Your saved work is unchanged; retry scoring.",
    "unavailable": "The AI service is temporarily unavailable. Your saved work is unchanged; retry scoring.",
    "request_rejected": "The AI service rejected the scoring request. Ask the administrator to check the model and request configuration.",
    "invalid_output": "The AI returned an incomplete or invalid scoring response. Your saved work is unchanged; retry scoring.",
    "evidence_mismatch": "The AI's evidence could not be matched to the saved work. No score was assigned; retry scoring.",
    "incomplete_checks": "The AI did not return all required evidence checks. No score was assigned; retry analysis.",
    "context_limit": "The scoring input is too large for one analysis. Reduce the reference material before retrying.",
    "unknown": "The AI review could not be completed. Your saved work is unchanged; retry scoring.",
}


def failure_detail(error):
    code = error.code if isinstance(error, (ProviderError, ScoringError)) else "invalid_output" if isinstance(error, ValidationError) else "unknown"
    if code not in MESSAGES:
        code = "unknown"
    return {"code": code, "message": MESSAGES[code]}


def validation_hint(error):
    """Bounded schema-only feedback. Never include values, quotes or exception text."""
    if isinstance(error, ValidationError):
        return "; ".join(dict.fromkeys(item["type"] for item in error.errors(include_input=False, include_context=False)[:8]))
    return failure_detail(error)["code"]
