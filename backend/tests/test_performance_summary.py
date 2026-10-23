"""Presentation-only summaries never change scores, judgments or source citations."""
import copy
from app.assessments.performance_summary import performance_summary, report_performance_summary
from app.assessments.workflow import ConsolidatedAssessmentGraph
from assessment_fixtures import synthetic_source


def test_plain_highlights_keep_original_explanations_and_provenance():
    result = ConsolidatedAssessmentGraph().graph.invoke({"snapshot": synthetic_source()})["result"]
    before = copy.deepcopy(result)
    projected = report_performance_summary(result)
    assert projected["strengths"] and projected["weaknesses"]
    assert all(len(f["summary_text"]) <= 150 for values in projected.values() for f in values)
    positive = next(f for f in projected["strengths"] if f.get("pair_id"))
    assert positive["summary_text"] == "Relevant answers with clear reasoning."
    negative = projected["weaknesses"][0]
    assert "technical" in negative["summary_text"].lower() and "requested points" in negative["summary_text"]
    for key in projected:
        for old, new in zip(result["evidence_summary"][key], projected[key]):
            assert new["text"] == old["text"] and new["evidence_ids"] == old["evidence_ids"]
    assert result == before
    assert result["score_summary"]["cv_weight"] == 40 and result["score_summary"]["interview_weight"] == 60


def test_uncertainty_stays_a_check_not_a_performance_weakness():
    summary = {"strengths": [], "weaknesses": [], "evidence_gaps": [{"text": "Not explored: Automated testing.", "rule": "requirement_not_explored"}],
               "verification": [{"text": "A very long transcription warning.", "rule": "ambiguous_transcript"}]}
    projected = performance_summary(summary)
    assert not projected["weaknesses"]
    assert projected["evidence_gaps"][0]["summary_text"] == "Automated testing — not discussed."
    assert projected["verification"][0]["summary_text"] == "Clarify unclear wording before scoring."
    assert "summary_text" not in summary["verification"][0]


def test_unvalidated_labels_cannot_create_new_positive_highlights():
    summary = {"strengths": [{"text": "The explanation could not be verified.", "pair_id": "p", "rule": "validated_dimension_labels"}]}
    result = performance_summary(summary, [{"id": "p", "assessment": {"accuracy": {"label": "supported", "support_status": "insufficient_evidence"}}}])
    assert result["strengths"][0]["summary_text"] == summary["strengths"][0]["text"]


def test_projection_is_idempotent_and_word_bounds_do_not_discard_original_findings():
    original = "Candidate statement " * 40 + "but the claim remains unverified."
    summary = {"verification": [{"text": original, "evidence_ids": ["source"]}]}
    first = performance_summary(summary)
    assert len(first["verification"][0]["summary_text"]) <= 150
    assert first["verification"][0]["text"] == original
    assert performance_summary(first) == first
