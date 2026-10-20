"""Synthetic source snapshots, never copied from candidate data."""
import copy
from app.agents.interview_analysis import canonical_quote, digest


def synthetic_source(application_id=101, name="Synthetic Candidate Alpha", long=False):
    version = "synthetic-approved-requirements-v1"
    q = {"id": "q1", "interview_id": 201, "session_id": "synthetic-session", "speaker": "INTERVIEWER",
        "text": "How do you test database transaction rollback?", "start_offset_ms": 0, "end_offset_ms": 2000,
        "start_at": "2026-10-20T04:00:00+00:00", "end_at": "2026-10-20T04:00:02+00:00", "sequence": 1, "confidence": .99}
    a = {**q, "id": "a1", "speaker": "CANDIDATE", "text": "I use integration tests to verify atomic commits and rollbacks.",
        "start_offset_ms": 3000, "end_offset_ms": 7000, "start_at": "2026-10-20T04:00:03+00:00", "end_at": "2026-10-20T04:00:07+00:00", "sequence": 2}
    for s in (q, a): s["hash"] = digest(s)
    citation = canonical_quote({"segment_id": a["id"], "quote": a["text"]}, {a["id"]: a}, {a["id"]})
    requirements = [{"key": "required_skill:0", "name": "Database transactions", "classification": "required", "category": "technical", "weight": "1", "requirement_version": version},
        {"key": "required_skill:1", "name": "Automated testing", "classification": "required", "category": "technical", "weight": "1", "requirement_version": version}]
    if long:
        requirements += [{**requirements[1], "key": f"preferred_skill:{i}", "name": f"Synthetic integration requirement {i}: maintain clear, repeatable system verification with representative edge cases", "classification": "preferred"} for i in range(12)]
    dim = {"label": "direct", "justification": "The candidate describes an integration test for transaction rollback.", "citations": [citation], "references": [], "support_status": "supported_by_check", "evidence_gaps": []}
    guide = {"id": "synthetic-guide", "title": "Transaction testing answer guide", "kind": "answer_guide", "version": "synthetic-guide-v1",
        "content": "Use integration tests to check that commits persist changes and rollbacks restore the original state."}
    assessment = {k: copy.deepcopy(dim) for k in ("relevance", "accuracy", "completeness", "quality")}
    assessment["quality"]["label"] = "clear"
    for key in ("accuracy", "completeness"):
        assessment[key]["label"] = "partially_supported" if key == "accuracy" else "partial"
        assessment[key]["references"] = [{"reference_id": guide["id"], "version": guide["version"], "kind": "answer_guide", "quote": guide["content"]}]
    values = {"relevance": 1, "accuracy": .5, "completeness": .5, "quality": 1}
    pair = {"id": "pair-synthetic-1", "question_ids": [q["id"]], "answer_ids": [a["id"]], "context_ids": [], "state": "analyzed", "flags": [],
        "question_requirement_ids": ["required_skill:0"], "assessment": assessment,
        "mappings": [{"requirement_id": "required_skill:0", "requirement_version": version, "status": "supporting_evidence", "support_status": "supported_by_check", "citations": [citation], "explanation": "A concrete rollback testing example supports this requirement."}],
        "score": {"percentage": 75, "earned": 3, "possible": 4, "rubric_version": "answer-coverage-equal-dimensions-v2",
            "breakdown": {k: {"value": v, "weight": 25, "status": "met" if v == 1 else "partially_met", "reason": "Synthetic saved rating"} for k,v in values.items()}}}
    cv = {"scoring_run_id": 301, "score_id": 401, "configuration_id": 501, "formula_version": "weighted-requirement-coverage-v1", "requirement_version": version,
        "configuration": {"category_weights": {"technical": "50", "experience": "30", "qualification": "20"}},
        "final_score": "75.000000", "categories": {"technical": "80.000000", "experience": "50.000000", "qualification": "100.000000"},
        "breakdown": {"counts": {"met": 2, "partially_met": 1, "unmet": 1}, "requirements": [], "exact_final_score": {"numerator": 75, "denominator": 1}},
        "original_cv_rank": 2, "original_cohort": [101, 102, 103, 104], "written_justification": "Synthetic saved result: 80% technical, 50% experience, 100% qualifications with approved 50/30/20 weights.",
        "document_id": 601, "document_sha256": "synthetic-cv-hash", "screening_run_id": 701, "screening_status": "completed", "compatible": True,
        "screening_document_sha256": "synthetic-cv-hash", "screening_requirement_version": version,
        "source_blocks": [{"id": "block-1", "text": "Built database transactions and tested rollbacks.", "locator": "Synthetic PDF page 1"}],
        "matches": [{"id": 801, "requirement_id": "required_skill:0", "status": "met", "evidence": [{"block_id": "block-1", "quote": "Built database transactions and tested rollbacks."}]}], "extraction_warnings": []}
    return {"identification": {"application_id": application_id, "job_posting_id": 1, "candidate_name": name, "job_title": "Synthetic Backend Engineer", "requirement_version": version},
        "cv": cv, "requirements": requirements, "flags": [], "missing": [], "source_key": "synthetic-source-v1", "model": "mock",
        "interviews": [{"id": 201, "date": "2026-10-20T04:00:00+00:00", "finalized": True, "segments": {s["id"]: s for s in (q, a)}, "reviews": [],
            "analysis": {"id": 901, "version": 1, "requirement_version": version, "rubric_version": "answer-coverage-equal-dimensions-v2", "snapshot": {"segments": [q, a], "watermark": {s["id"]: s["hash"] for s in (q,a)}, "references": [guide]}, "result": {"pairs": [pair], "gaps": [], "reconciled": True}}}]}
