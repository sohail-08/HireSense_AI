"""Synthetic-only exact scoring and durable ranking integration checks."""
import copy
from fractions import Fraction
import pytest
from sqlalchemy import select
from fastapi import FastAPI
from fastapi.testclient import TestClient
from types import SimpleNamespace
from app.assessments.final_scoring import rank_reports
from app.assessments.workflow import ConsolidatedAssessmentGraph
from app.models.assessment import AssessmentRun, AssessmentComparison
from app.models.interview_analysis import InterviewAnalysisRun
from app.models.transcription import TranscriptSegment
from app.routes import assessments as routes
from app.database import get_db
from app.security import require_interviewer
from app.services.final_ranking_service import FinalRankingService
from app.services.assessment_service import AssessmentService
from app.services.interview_analysis import InterviewAnalysisService
from assessment_fixtures import synthetic_source
from test_assessments import consolidated, FailingModel  # noqa: F401
from test_interview_analysis import saved  # noqa: F401
from test_transcription import transcription  # noqa: F401
from test_interview_rooms import room_setup  # noqa: F401
from test_interviews import setup, records  # noqa: F401


def result(source):
    return ConsolidatedAssessmentGraph().graph.invoke({"snapshot": source})["result"]


def test_fixed_40_60_weights_and_question_average_are_exact():
    source = synthetic_source()
    summary = result(source)["score_summary"]
    assert summary["ready"]
    assert Fraction(summary["final_score"]) == 75
    assert Fraction(summary["interview_score"]) == 75
    assert (summary["cv_weight"], summary["interview_weight"]) == (40, 60)
    analysis = source["interviews"][0]["analysis"]
    unanswered = copy.deepcopy(analysis["result"]["pairs"][0])
    unanswered.update(id="unanswered", state="unanswered", answer_ids=[], assessment=None, mappings=[])
    unanswered["score"].update(percentage=0, earned=0)
    for dimension in unanswered["score"]["breakdown"].values(): dimension["value"] = 0
    analysis["result"]["pairs"].append(unanswered)
    summary = result(source)["score_summary"]
    assert summary["ready"] and summary["question_count"] == 2 and summary["unanswered_count"] == 1
    assert Fraction(summary["interview_score"]) == Fraction(75, 2)
    assert Fraction(summary["final_score"]) == Fraction(105, 2)


@pytest.mark.parametrize("cv,expected", [("80", Fraction(77)), ("0", Fraction(45)), ("100", Fraction(85)), ("2.675", Fraction(4607, 100))])
def test_asymmetric_scores_use_exact_40_cv_60_interview_arithmetic(cv, expected):
    source = synthetic_source()
    source["cv"]["final_score"] = cv
    value = Fraction(cv)
    source["cv"]["breakdown"]["exact_final_score"] = {"numerator": value.numerator, "denominator": value.denominator}
    summary = result(source)["score_summary"]
    assert summary["ready"] and Fraction(summary["interview_score"]) == 75
    assert Fraction(summary["final_score"]) == expected
    assert Fraction(int(summary["exact_final_score"]["numerator"]), int(summary["exact_final_score"]["denominator"])) == expected


def test_rankings_cannot_mix_saved_final_weighting_policies():
    reports = [{"id": i, "application_id": i, "result": result(synthetic_source(i)), "stale": False} for i in (1, 2)]
    reports[0]["result"]["score_summary"].update(formula_version="cv50-interview50-v1", cv_weight=50, interview_weight=50)
    ordered, issue = rank_reports(reports)
    assert issue and all(r.get("final_rank") is None for r in ordered)


@pytest.mark.parametrize("mutation", ["no_cv", "no_interview", "open_transcript", "failed_analysis", "no_score", "outdated_transcript", "old_requirements", "unsupported", "forged_score", "missing_guide"])
def test_missing_or_invalid_processing_never_becomes_zero(mutation):
    source = synthetic_source()
    interview = source["interviews"][0]
    analysis = interview["analysis"]
    pair = analysis["result"]["pairs"][0]
    if mutation == "no_cv": source["cv"] = None
    elif mutation == "no_interview": source["interviews"] = []
    elif mutation == "open_transcript": interview["finalized"] = False
    elif mutation == "failed_analysis": analysis["status"] = "failed"
    elif mutation == "no_score": pair.pop("score")
    elif mutation == "outdated_transcript": analysis["snapshot"]["watermark"] = {}
    elif mutation == "old_requirements": analysis["requirement_version"] = "old"
    elif mutation == "unsupported": pair["assessment"]["relevance"]["support_status"] = "unsupported"
    elif mutation == "forged_score": pair["score"]["percentage"] = 99
    elif mutation == "missing_guide": analysis["snapshot"]["references"] = []
    summary = result(source)["score_summary"]
    assert not summary["ready"] and summary["final_score"] is None
    assert summary["interview_score"] is None and summary["reason"]


def test_zero_is_a_real_score_excluded_questions_are_not_in_average():
    source = synthetic_source()
    source["cv"]["final_score"] = "0E-60"
    source["cv"]["breakdown"]["exact_final_score"] = {"numerator": 0, "denominator": 1}
    pair = source["interviews"][0]["analysis"]["result"]["pairs"][0]
    pair.update(state="unanswered", answer_ids=[], assessment=None, mappings=[])
    pair["score"].update(percentage=0, earned=0)
    for item in pair["score"]["breakdown"].values(): item["value"] = 0
    excluded = copy.deepcopy(pair); excluded.update(id="excluded", state="excluded", excluded=True); excluded.pop("score")
    source["interviews"][0]["analysis"]["result"]["pairs"].append(excluded)
    summary = result(source)["score_summary"]
    assert summary["ready"] and Fraction(summary["final_score"]) == 0 and summary["question_count"] == 1


def test_supported_negative_labels_are_zero_but_failed_reference_checks_are_unscored():
    source = synthetic_source()
    pair = source["interviews"][0]["analysis"]["result"]["pairs"][0]
    for name, label in zip(("relevance", "accuracy", "completeness", "quality"), ("tangent", "contradicted", "incomplete", "limited")):
        pair["assessment"][name]["label"] = label
        pair["score"]["breakdown"][name]["value"] = 0
    pair["score"].update(percentage=0, earned=0)
    assert result(source)["score_summary"]["interview_score"] == "0"
    pair["assessment"]["accuracy"]["references"][0]["quote"] = "Nonexistent reference quote"
    checked = result(source)
    assert not checked["score_summary"]["ready"] and checked["score_summary"]["final_score"] is None


def test_exact_ties_and_final_score_order_not_cv_order():
    reports = []
    for app, cv, final in [(1, 90, Fraction(60)), (2, 70, Fraction(85)), (3, 70, Fraction(85)), (4, 90, Fraction(60) + Fraction(1, 10**40))]:
        source = synthetic_source(app)
        r = result(source)
        r["cv"]["final_score"] = str(cv)
        r["score_summary"]["exact_final_score"] = {"numerator": str(final.numerator), "denominator": str(final.denominator)}
        reports.append({"id": app, "application_id": app, "result": r, "stale": False})
    ordered, issue = rank_reports(reports)
    assert issue is None
    assert [r["application_id"] for r in ordered] == [2, 3, 4, 1]
    assert [r["final_rank"] for r in ordered] == [1, 1, 3, 4]
    reports[0]["result"]["cv"]["formula_version"] = "different"
    ordered, issue = rank_reports(reports)
    assert issue
    # Calling the calculator must not retain old ranks on an incompatible cohort.
    assert all(r.get("final_rank") is None for r in ordered)


def finish(t, service, row_id):
    service.advance(row_id)
    t.db.expire_all()
    for analysis in list(t.db.scalars(select(InterviewAnalysisRun).where(InterviewAnalysisRun.status == "queued"))):
        t.analysis.process(analysis.id)
    service.advance(row_id)
    t.db.expire_all()
    for report in list(t.db.scalars(select(AssessmentRun).where(AssessmentRun.status == "queued"))):
        t.assessments.process(report.id)
    service.advance(row_id)
    t.db.expire_all()


def test_durable_job_ranking_reuses_sources_and_detects_new_transcript(consolidated, monkeypatch):
    t = consolidated
    service = FinalRankingService(session_factory=t.assessments.factory)
    before = len(t.analysis.model.calls)
    monkeypatch.setattr(InterviewAnalysisService, "enqueue", lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("Fresh analysis must be reused")))
    ranking = service.start(t.db, t.owner.id, t.row.job_posting_id)
    assert ranking["status"] == "processing"
    assert service.start(t.db, t.owner.id, t.row.job_posting_id)["id"] == ranking["id"]
    finish(t, service, ranking["id"])
    current = service.read(t.db, t.owner.id, t.row.job_posting_id)
    assert current["status"] == "completed" and not current["stale"]
    own = next(r for r in current["candidates"] if r["application_id"] == t.row.application_id)
    assert own["final_rank"] is not None and own["final_score"] is not None
    assert len(t.analysis.model.calls) == before
    # A repeated completed request is idempotent and GET never enqueues analysis.
    assert service.start(t.db, t.owner.id, t.row.job_posting_id)["id"] == current["id"]
    t.db.get(TranscriptSegment, t.answer["id"]).text = "A synthetic changed answer"
    t.db.commit()
    assert service.read(t.db, t.owner.id, t.row.job_posting_id)["stale"]


def test_old_final_weighting_is_stale_and_recalculation_reuses_answer_analysis(consolidated):
    t = consolidated
    service = FinalRankingService(session_factory=t.assessments.factory)
    first = service.start(t.db, t.owner.id, t.row.job_posting_id)
    finish(t, service, first["id"])
    row = t.db.get(AssessmentComparison, first["id"])
    row.snapshot = {**copy.deepcopy(row.snapshot), "formula_version": "cv50-interview50-v1"}
    row.fingerprint = "synthetic-historical-50-50-ranking"
    t.db.commit()
    assert service.read(t.db, t.owner.id, t.row.job_posting_id)["stale"]
    before = len(t.analysis.model.calls)
    second = service.start(t.db, t.owner.id, t.row.job_posting_id)
    assert second["id"] != first["id"]
    finish(t, service, second["id"])
    current = service.read(t.db, t.owner.id, t.row.job_posting_id)
    assert current["status"] == "completed" and not current["stale"]
    assert len(t.analysis.model.calls) == before


def test_missing_analysis_is_queued_once_then_joins_final_ranking(consolidated):
    t = consolidated
    # Expire the old source without removing immutable existing reports.
    analysis = t.analysis.latest(t.db, t.row.id)
    analysis.status = "failed"
    t.db.commit()
    service = FinalRankingService(session_factory=t.assessments.factory)
    ranking = service.start(t.db, t.owner.id, t.row.job_posting_id)
    service.advance(ranking["id"]); t.db.expire_all()
    assert t.analysis.latest(t.db, t.row.id).status == "queued"
    count = len(list(t.db.scalars(select(InterviewAnalysisRun))))
    service.advance(ranking["id"]); t.db.expire_all()
    assert len(list(t.db.scalars(select(InterviewAnalysisRun)))) == count
    finish(t, service, ranking["id"])
    value = service.read(t.db, t.owner.id, t.row.job_posting_id)
    assert value["status"] == "completed"
    assert next(c for c in value["candidates"] if c["application_id"] == t.row.application_id)["final_rank"] is not None


def test_legacy_display_only_scores_do_not_prevent_persisted_rescoring(consolidated):
    t = consolidated
    analysis = t.analysis.latest(t.db, t.row.id)
    original = copy.deepcopy(analysis.result)
    for pair in original["pairs"]: pair.pop("score", None)
    analysis.result = original
    t.db.commit()
    service = FinalRankingService(session_factory=t.assessments.factory)
    value = service.start(t.db, t.owner.id, t.row.job_posting_id)
    service.advance(value["id"]); t.db.expire_all()
    assert t.analysis.latest(t.db, t.row.id).id != analysis.id
    assert t.analysis.latest(t.db, t.row.id).status == "queued"


def test_central_assistant_can_start_fixed_weight_job_ranking(consolidated):
    from app.services.supervisor_service import SupervisorService
    from app.agents.supervisor_tools import AssessmentToolRequest
    t = consolidated
    supervisor = SimpleNamespace(state_json={"selected_screening_job_posting_id": t.row.job_posting_id})
    instance = object.__new__(SupervisorService)
    result = instance._assessments_tool(t.db, supervisor, t.owner.id, AssessmentToolRequest(operation="rank"))
    assert result["refresh_required"] and "CV 40% + interview 60%" in result["assistant_message"]
    assert result["assessment_links"][0]["path"].endswith(f"job={t.row.job_posting_id}")
    with pytest.raises(LookupError):
        instance._assessments_tool(t.db, supervisor, t.other.id, AssessmentToolRequest(operation="rank"))


def test_pending_rankings_are_private_and_deleted_with_sources(consolidated):
    t = consolidated
    service = FinalRankingService(session_factory=t.assessments.factory)
    value = service.start(t.db, t.owner.id, t.row.job_posting_id)
    with pytest.raises(LookupError): service.read(t.db, t.other.id, t.row.job_posting_id)
    with pytest.raises(LookupError): t.assessments.read_comparison(t.db, t.other.id, value["id"])
    from app.schemas.assessment import ExportReport
    with pytest.raises(ValueError): t.reports.request(t.db, t.owner.id, ExportReport(format="html"), comparison_id=value["id"])
    AssessmentService.delete_sources(t.db, interview_ids=[t.row.id]); t.db.commit()
    assert t.db.get(AssessmentComparison, value["id"]) is None


def test_api_requires_interviewer_ownership_and_explicit_calculation(consolidated):
    t = consolidated
    app = FastAPI(); app.include_router(routes.router)
    app.dependency_overrides[get_db] = lambda: t.db
    app.dependency_overrides[require_interviewer] = lambda: SimpleNamespace(id=t.owner.id)
    with TestClient(app) as client:
        url = f"/api/assessments/jobs/{t.row.job_posting_id}/ranking"
        response = client.get(url)
        assert response.status_code == 200 and response.json()["status"] == "not_started"
        assert "no-store" in response.headers["cache-control"]
        assert not list(t.db.scalars(select(AssessmentComparison)))
        assert client.post(url, json={"confirmed": False}).status_code == 422
        assert client.post(url, json={"confirmed": True}).status_code == 202
        app.dependency_overrides[require_interviewer] = lambda: SimpleNamespace(id=t.other.id)
        assert client.get(url).status_code == 404
        assert client.post(url, json={"confirmed": True}).status_code == 404
