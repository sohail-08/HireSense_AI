"""Opt-in provider check on two labelled, synthetic English exchanges. No database/media access."""
import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from app.config import get_settings
from app.llm.gemini import GeminiStructuredClient
from app.agents.interview_analysis import InterviewAnalysisGraph, digest, normalize_support_checks, PROMPT_VERSION, PAIRING_VERSION, RUBRIC_VERSION
from app.schemas.interview_analysis import Detection, Assessment, Mappings, SupportCheck, FollowUps


class ProbeClient(GeminiStructuredClient):
    def __init__(self):
        super().__init__(timeout_seconds=45)
        self.failure = None
        self.calls = 0

    def generate_json(self, **kwargs):
        self.calls += 1
        try:
            value = super().generate_json(**kwargs)
        except RuntimeError as exc:
            message = str(exc)
            allowed = ["Gemini API request timed out", "Gemini API is unavailable", "Gemini returned an invalid structured response",
                       "Gemini API quota was exceeded; retry after the quota resets", "Gemini API authentication failed; check GEMINI_API_KEY"]
            self.failure = message if message in allowed else "Provider request failed"
            if message.startswith("Gemini API request failed with status ") and message.rsplit(" ", 1)[-1].isdigit():
                self.failure = message
                response = getattr(exc.__cause__, "response", None)
                if response is not None:
                    try:
                        detail = response.json().get("error", {}).get("message", "").casefold()
                        categories = [name for name in ("api key", "expired", "invalid", "schema", "model", "not supported", "too many", "constraint", "maximum", "complex") if name in detail]
                        self.failure += " (" + ", ".join(categories) + ")"
                    except Exception:
                        pass
            raise
        schema = {s.__name__: s for s in (Detection, Assessment, Mappings, SupportCheck, FollowUps)}[kwargs["schema"]["title"]]
        try:
            schema.model_validate(normalize_support_checks(value, json.loads(kwargs["prompt"])["targets"])
                                  if schema is SupportCheck else value)
        except Exception:
            self.failure = "Structured output failed schema validation"
            raise
        return value


def run():
    settings = get_settings()
    if not settings.gemini_api_key or not settings.gemini_api_key.get_secret_value().strip():
        return {"status": "not_run", "reason": "Gemini key unavailable"}
    cases = [
        ("approved_reference", "Explain transaction atomicity and give an example.",
         "Atomicity means all changes in a transaction commit or none do. If transferring money between two accounts fails after the debit, I roll back the debit as well.",
         [{"id": "atomicity-guide", "title": "Transaction atomicity answer guide", "kind": "answer_guide",
           "content": "Atomicity means that a transaction commits all of its changes or none of them. A failed transfer must not leave only one account updated.",
           "requirement_ids": ["required_skill:0"], "version": "synthetic-v1"}]),
        ("unverified_project_claim", "Describe how you used transactions in a project.",
         "In a training project I wrapped the order insert and stock update in one transaction, and rolled back when either operation failed.", []),
    ]
    results = []
    for name, question, answer, references in cases:
        base = datetime(2026, 10, 19, tzinfo=timezone.utc)
        segments = []
        for i, (role, text) in enumerate([("INTERVIEWER", question), ("CANDIDATE", answer)], 1):
            source = {"id": f"{i:064x}", "interview_id": 1, "session_id": "synthetic", "participant_identity": role,
                "speaker": role, "text": text, "start_at": (base + timedelta(seconds=i * 3)).isoformat(),
                "end_at": (base + timedelta(seconds=i * 3 + 2)).isoformat(), "start_offset_ms": i * 3000,
                "end_offset_ms": i * 3000 + 2000, "confidence": .99, "sequence": i}
            source["hash"] = digest(source)
            segments.append(source)
        snapshot = {"segments": segments, "complete": True, "finalize_last": False, "references": references,
            "requirements": {"requirements": [{"key": "required_skill:0", "name": "Database transactions"}]},
            "requirement_version": "synthetic-v1", "model": settings.gemini_chat_model, "prompt_version": PROMPT_VERSION,
            "pairing_version": PAIRING_VERSION, "rubric_version": RUBRIC_VERSION, "gaps": [], "watermark": {s["id"]: s["hash"] for s in segments}}
        started = time.perf_counter()
        client = ProbeClient()
        try:
            result = InterviewAnalysisGraph(client).graph.invoke({"snapshot": snapshot})["result"]
            pair = result["pairs"][0] if result["pairs"] else {}
            assessment = pair.get("assessment", {})
            results.append({"case": name, "elapsed_seconds": round(time.perf_counter() - started, 2),
                "pairing_matches_label": len(result["pairs"]) == 1 and pair.get("question_ids") == [segments[0]["id"]] and pair.get("answer_ids") == [segments[1]["id"]],
                "assessment_available": bool(assessment), "labels": {k: assessment.get(k, {}).get("label") for k in ("relevance", "accuracy", "completeness", "quality")},
                "support_checks_passed": sum(c["supported"] for c in pair.get("validation", [])),
                "support_checks_total": len(pair.get("validation", [])), "follow_ups": len(pair.get("suggestions", [])),
                "answer_score_percent": pair.get("score", {}).get("percentage"), "partial_error": bool(pair.get("analysis_error"))})
        except Exception:
            results.append({"case": name, "elapsed_seconds": round(time.perf_counter() - started, 2), "status": "failed", "failure": client.failure or "Workflow validation failed", "provider_calls": client.calls})
        print(json.dumps(results[-1]), flush=True)
    return {"provider": "gemini", "model": settings.gemini_chat_model, "cases": len(cases),
            "limitations": "Two synthetic exchanges only; not a human-rated quality, accent or live-media benchmark."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", required=True, action="store_true", help="Use configured provider credentials; may incur usage charges")
    parser.parse_args()
    print(json.dumps(run()), flush=True)
