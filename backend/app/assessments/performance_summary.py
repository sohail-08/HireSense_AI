"""Read-only, plain-language presentation of existing validated findings.

No model calls or new judgments. Original explanations and provenance are retained.
"""
import copy
import re


POSITIVE = {"relevance": "direct", "accuracy": "supported", "completeness": "complete", "quality": "clear"}
NEGATIVE = {
    "relevance": {"partial": "Only partly addresses the question", "tangent": "Does not address the question"},
    "accuracy": {"partially_supported": "Some technical details are incorrect", "contradicted": "Technical explanation conflicts with the guide"},
    "completeness": {"partial": "Misses some requested points", "incomplete": "Misses the requested points"},
    "quality": {"mixed": "Some reasoning needs clarification", "limited": "Reasoning needs more explanation"},
}


def concise(text, limit=150):
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[:limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"


def performance_summary(summary, pairs=(), matrix=()):
    """Add short presentation text without changing saved claims or score inputs."""
    result = copy.deepcopy(summary)
    by_pair = {(p.get("interview_id"), p["id"]): p for p in pairs}
    for category, findings in result.items():
        if not isinstance(findings, list): continue
        for finding in findings:
            original = finding.get("text", "")
            text = re.sub(r"^Q\d+\s*[·:]\s*", "", original).strip()
            rule = finding.get("rule")
            pair = by_pair.get((finding.get("interview_id"), finding.get("pair_id")), {})
            dims = pair.get("assessment") or pair.get("dimensions") or {}
            if rule == "validated_dimension_labels":
                valid = {key: item for key, item in dims.items() if isinstance(item, dict) and (
                    item.get("support_status") == "supported_by_check" or item.get("support_validated") is True)}
                if category == "strengths":
                    names = [key for key, label in POSITIVE.items() if valid.get(key, {}).get("label") == label]
                    adjectives = [word for key, word in (("relevance", "relevant"), ("accuracy", "technically correct"), ("completeness", "complete")) if key in names]
                    if adjectives:
                        description = adjectives[0] if len(adjectives) == 1 else ", ".join(adjectives[:-1]) + " and " + adjectives[-1]
                        text = description.capitalize() + " answers" + (" with clear reasoning." if "quality" in names else ".")
                    elif "quality" in names:
                        text = "Explains the reasoning clearly."
                elif category == "weaknesses":
                    text = "; ".join(NEGATIVE[key][valid[key]["label"]] for key in NEGATIVE
                        if valid.get(key, {}).get("label") in NEGATIVE[key]) or text
            elif rule == "unanswered_exchange":
                text = "No answer recorded for this question."
            elif rule == "score_readiness":
                state = (finding.get("source") or {}).get("state") or pair.get("state")
                text = {"awaiting_answer": "Waiting for an answer.", "answer_in_progress": "An answer is still in progress.",
                        "needs_clarification": "An answer needs clarification before scoring."}.get(state, "An answer could not be scored yet.")
            elif rule == "contextual_transcription_interpretation":
                text = "Confirm wording interpreted from transcript context."
            elif rule == "ambiguous_transcript":
                text = "Clarify unclear wording before scoring."
            elif rule == "transcript_quality":
                text = "Check unclear or overlapping speech."
            elif rule == "requirement_not_explored":
                text = re.sub(r"^Not explored:\s*", "", text).rstrip(".") + " — not discussed."
            elif category == "strengths" and text.startswith("CV evidence supports "):
                text = text.replace("CV evidence supports ", "CV supports ", 1)
            elif category == "verification" and text.startswith("Ask for a concrete, job-related example demonstrating "):
                text = text.replace("Ask for a concrete, job-related example demonstrating ", "Ask for an example of ", 1)
            elif category == "evidence_gaps":
                row = next((r for r in matrix if text.startswith(r["name"] + ": ")), None)
                if row:
                    points = []
                    if row.get("conflict"): points.append("evidence conflicts")
                    if row.get("cv_status") == "unmet": points.append("not shown in the CV")
                    if row.get("interview_coverage") == "not_explored": points.append("not discussed")
                    elif row.get("interview_coverage") in {"asked_answer_pending", "asked_unanswered"}: points.append("no assessed answer")
                    if "insufficient_evidence" in row.get("interview_statuses", []): points.append("not enough interview evidence")
                    if points: text = row["name"] + " — " + "; ".join(points) + "."
                elif text.startswith("Saved CV screening outcome for requirement "):
                    text = "CV screening is incomplete."
                elif text.startswith("Completed assessment for question "):
                    text = "An answer analysis is incomplete."
            finding["summary_text"] = concise(text)
    return result


def report_performance_summary(report):
    pairs = [{**p, "interview_id": interview["id"]} for interview in report.get("interviews", []) for p in interview.get("pairs", [])]
    return performance_summary(report.get("evidence_summary", {}), pairs, report.get("matrix", []))
