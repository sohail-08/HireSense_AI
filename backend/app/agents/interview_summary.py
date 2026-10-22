"""Deterministic summaries of validated judgments, with source-owned evidence.

Missing evidence is never converted into a demonstrated weakness. No extra model call.
"""
from app.agents.interview_analysis import DIMENSIONS, LABEL_VALUES, canonical_quote, digest


def evidence_summary(result, snapshot):
    summary = {key: [] for key in ("strengths", "weaknesses", "evidence_gaps", "verification")}
    segments = {s["id"]: s for s in snapshot.get("segments", [])}
    references = {r["id"]: r for r in snapshot.get("references", [])}

    def quotes(items, allowed):
        valid = {}
        for quote in items:
            try:
                source = segments.get(quote["segment_id"], {})
                if quote.get("revision", source.get("hash")) != source.get("hash"):
                    continue
                q = canonical_quote(quote, segments, allowed)
                if any(k in quote and quote[k] != q[k] for k in ("interview_id", "session_id", "speaker", "start_at", "end_at", "start_offset_ms", "end_offset_ms", "char_start", "char_end")):
                    continue
                valid[(q["segment_id"], q["char_start"], q["char_end"])] = q
            except (ValueError, KeyError):
                continue
        return list(valid.values())

    def add(category, text, rule, pair=None, citations=None, refs=None, source=None):
        summary[category].append({"id": digest([category, text, pair and pair["id"], source])[:24],
            "text": text, "rule": rule, "pair_id": pair["id"] if pair else None,
            "citations": citations or [], "references": refs or [], "source": source or {}})

    for index, pair in enumerate(result.get("pairs", []), 1):
        if pair.get("excluded") or pair.get("state") == "excluded":
            continue
        question_quotes = quotes([{"segment_id": i, "quote": segments[i]["text"]}
            for i in pair["question_ids"] if i in segments], set(pair["question_ids"]))
        anchor = {"kind": "exchange", "pair_id": pair["id"], "state": pair["state"],
                  "question_ids": pair["question_ids"], "answer_ids": pair["answer_ids"]}
        assessment = pair.get("assessment") or {}
        interpretation = assessment.get("interpretation") or {}
        usable_meaning = not interpretation or (interpretation.get("support_status") == "supported_by_check" and interpretation.get("status") != "uncertain")
        if interpretation:
            if not interpretation.get("citations") or len(quotes(interpretation["citations"], set(pair["answer_ids"]))) != len(interpretation["citations"]):
                usable_meaning = False
            allowed = set(pair["question_ids"] + pair["answer_ids"] + pair["context_ids"])
            for note in interpretation.get("notes", []):
                if not quotes([note["original"]], allowed) or not note.get("context") or len(quotes(note["context"], allowed)) != len(note["context"]):
                    usable_meaning = False
            if interpretation.get("status") == "context_supported" and not interpretation.get("notes"):
                usable_meaning = False
        grouped = {"strengths": [], "weaknesses": []}
        for name in DIMENSIONS:
            item = assessment.get(name, {})
            citations = quotes(item.get("citations", []), set(pair["answer_ids"]))
            refs = []
            for ref in item.get("references", []):
                source = references.get(ref.get("reference_id"))
                if source and ref.get("version") == source.get("version") and ref.get("quote", "").strip() and ref["quote"] in source["content"] and ("reference_ids" not in pair or ref["reference_id"] in pair["reference_ids"]):
                    refs.append({**ref, "title": source["title"], "kind": source["kind"]})
            valid = usable_meaning and item.get("support_status") == "supported_by_check" and bool(citations)
            if name == "accuracy": valid = valid and bool(refs)
            if name == "completeness": valid = valid and any(r["kind"] == "answer_guide" for r in refs)
            label = item.get("label")
            if valid and label not in {"unreadable", "unanswered", "ambiguous", "not_assessed", "unable_to_verify"}:
                category = "strengths" if LABEL_VALUES.get(label, 0) == 1 else "weaknesses"
                grouped[category].append((name, item, citations, refs))
        for category, findings in grouped.items():
            if not findings: continue
            # One concise finding per exchange and category, not repeated answer blocks.
            names = ", ".join(name for name, _, _, _ in findings)
            reasons = " ".join(dict.fromkeys(item["justification"] for _, item, _, _ in findings))
            text = f"Q{index} · {names.capitalize()}: {reasons}"
            add(category, text, "validated_dimension_labels", pair,
                quotes([q for _, _, qs, _ in findings for q in qs], set(pair["answer_ids"])),
                list({(r["reference_id"], r["quote"]): r for _, _, _, rs in findings for r in rs}.values()), anchor)
        if not pair.get("score"):
            reason = ("No answer was captured yet." if pair["state"] in {"awaiting_answer", "answer_in_progress"} else
                      pair.get("score_unavailable_reason") or "Evidence checks did not produce a complete score; retry analysis.")
            add("evidence_gaps", f"Q{index} · {reason}", "score_readiness", pair, question_quotes, source=anchor)
        if pair["state"] == "unanswered":
            add("evidence_gaps", f"Q{index} · No candidate answer was recorded. This is missing evidence, not proof of lacking the skill.", "unanswered_exchange", pair, question_quotes, source=anchor)
        if interpretation.get("status") == "context_supported" and interpretation.get("support_status") == "supported_by_check":
            add("verification", f"Q{index} · Context was used to interpret likely transcription errors. Confirm the wording if it affects your decision.",
                "contextual_transcription_interpretation", pair, quotes(interpretation.get("citations", []), set(pair["answer_ids"])), source=anchor)
        elif pair.get("state") == "needs_clarification":
            add("verification", f"Q{index} · Verify the unclear wording with the candidate or original recording before assigning a score.", "ambiguous_transcript", pair, question_quotes, source=anchor)
        elif "low_transcription_confidence" in pair.get("flags", []) or "overlapping_speech" in pair.get("flags", []):
            add("verification", f"Q{index} · Check low-confidence or overlapping speech; it was not treated as an incorrect answer.", "transcript_quality", pair, question_quotes, source=anchor)
    for coverage in result.get("coverage", []):
        if coverage.get("coverage_status") == "not_explored":
            add("evidence_gaps", f"Not explored: {coverage['name']}.", "requirement_not_explored", source={
                "kind": "requirement", "requirement_id": coverage["requirement_id"], "version": coverage["version"]})
    return summary
