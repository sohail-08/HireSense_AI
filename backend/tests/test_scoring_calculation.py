"""Increment-one tests: independent of scoring API/database/workflow services."""

from decimal import Decimal

import pytest

from app.services.scoring_calculation import assign_ranks, category_scores, display_score, justification, weighted_score


def inputs():
    requirements = [{"requirement_id": category, "name": category, "category": category,
                     "classification": "required", "weight": "1", "evaluation_criterion": category}
                    for category in ("technical", "experience", "qualification")]
    configuration = {"requirements": requirements, "requirement_version": "approved-v1",
                     "category_weights": {"technical": "50", "experience": "30", "qualification": "20"}}
    application = {"screening_status": "completed", "source_blocks": [{"id": "page-1", "locator": "PDF page 1", "text": "Fixed saved evidence."}],
                   "matches": [{"requirement_key": item["requirement_id"], "status": "met", "evidence": [{"block_id": "page-1", "quote": "Fixed saved evidence."}]} for item in requirements]}
    return configuration, application


def test_core_category_and_weighted_coverage():
    configuration, application = inputs()
    application["matches"][0]["status"] = "partially_met"
    result = weighted_score(configuration, category_scores(configuration, application))
    assert Decimal(result["categories"]["technical"]["score"]) == 50
    assert Decimal(result["final_score"]) == 75
    assert result["required_gaps"] == ["technical"]


@pytest.mark.parametrize("status", ["unmet", "unable_to_determine"])
def test_no_credit_for_unmet_or_uncertain(status):
    configuration, application = inputs()
    application["matches"][0]["status"] = status
    result = weighted_score(configuration, category_scores(configuration, application))
    assert Decimal(result["final_score"]) == 50
    assert result["requirements"][0]["status"] == "unmet"
    assert result["review_state"] == "ranked"
    assert "interviewer verification" not in justification(result)


def test_uncertain_matches_count_as_unmet_and_remain_rankable():
    configuration, application = inputs()
    for match in application["matches"]:
        match["status"] = "unable_to_determine"
        match["evidence"] = []
    result = weighted_score(configuration, category_scores(configuration, application))
    assert result["counts"]["unmet"] == 3
    assert set(result["counts"]) == {"met", "partially_met", "unmet"}
    assert Decimal(result["final_score"]) == 0
    assert result["review_flags"] == []
    assert assign_ranks([{"application_id": 1, "breakdown": result}])[0]["rank"] == 1


def test_missing_matches_are_unmet_without_manual_confirmation():
    configuration, application = inputs()
    application["matches"] = []
    result = weighted_score(configuration, category_scores(configuration, application))
    assert all(item["status"] == "unmet" for item in result["requirements"])
    assert result["review_state"] == "ranked"
    assert result["final_score"] == "0"


@pytest.mark.parametrize("failure", ["missing_blocks", "incomplete_screening", "document_warning", "unsupported_quote"])
def test_unmet_policy_does_not_hide_document_or_evidence_failures(failure):
    configuration, application = inputs()
    if failure == "missing_blocks":
        application["source_blocks"] = []
    elif failure == "incomplete_screening":
        application["screening_status"] = "failed"
        application["error_message"] = "The document could not be read."
    elif failure == "document_warning":
        application["review_flags"] = ["No text extracted from PDF page 2"]
    else:
        application["matches"][0]["evidence"][0]["quote"] = "Fabricated evidence"
    result = weighted_score(configuration, category_scores(configuration, application))
    assert result["review_state"] == "ranked"
    assert result["review_flags"]
    assert assign_ranks([{"application_id": 1, "breakdown": result}])[0]["rank"] == 1
    if failure in {"missing_blocks", "incomplete_screening"}:
        assert result["final_score"] == "0"


@pytest.mark.parametrize("flag", ["missing_evidence_validation", "evidence_does_not_support_conclusion", "unsupported_positive_assessment"])
def test_rejected_evidence_zeroes_only_the_affected_requirement(flag):
    configuration, application = inputs()
    application["matches"][0]["review_flags"] = [flag]
    application["review_flags"] = ["technical: " + flag]
    result = weighted_score(configuration, category_scores(configuration, application))
    assert result["requirements"][0]["status"] == "unmet"
    assert result["requirements"][1]["status"] == "met"
    assert result["final_score"] == "50"
    assert result["review_state"] == "ranked"


def test_duplicate_outcomes_cannot_earn_credit_but_do_not_block_ranking():
    configuration, application = inputs()
    application["matches"].append(dict(application["matches"][0]))
    result = weighted_score(configuration, category_scores(configuration, application))
    assert result["requirements"][0]["status"] == "unmet"
    assert result["final_score"] == "50"
    assert result["review_state"] == "ranked"


def test_negative_weights_rejected_in_pure_service():
    configuration, application = inputs()
    configuration["requirements"][0]["weight"] = "-1"
    with pytest.raises(ValueError):
        category_scores(configuration, application)


def test_display_rounding_does_not_mutate_saved_value():
    value = "66.66666666666666666666666667"
    assert display_score(value) == "66.67"
    assert value == "66.66666666666666666666666667"
