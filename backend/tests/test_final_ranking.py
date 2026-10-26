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
from assessment_fixtures import synthetic_source, practical_score
from test_assessments import consolidated, FailingModel  # noqa: F401
from test_interview_analysis import saved  # noqa: F401
from test_transcription import transcription  # noqa: F401
from test_interview_rooms import room_setup  # noqa: F401
from test_interviews import setup, records  # noqa: F401


def result(source):
    return ConsolidatedAssessmentGraph().graph.invoke({"snapshot": source})["result"]


def granular_source(marks=(87, 91, 84, 89), off_topic=False):
    from app.agents.interview_analysis import score_pair, RUBRIC_VERSION
    source = synthetic_source()
    analysis = source["interviews"][0]["analysis"]
    pair = analysis["result"]["pairs"][0]
    pair.pop("score")
    for name, mark in zip(("relevance", "accuracy", "completeness", "quality"), marks):
        pair["assessment"][name]["score"] = mark
    pair["assessment"]["interpretation"] = {"status": "faithful", "support_status": "supported_by_check", "citations": pair["assessment"]["relevance"]["citations"], "notes": []}
    if off_topic:
        pair["assessment"]["relevance"]["label"] = "tangent"
        for name in ("accuracy", "completeness", "quality"):
            pair["assessment"][name].update(support_status="insufficient_evidence", references=[], citations=[])
    analysis["rubric_version"] = RUBRIC_VERSION
    score_pair(pair)
    return source


def test_granular_marks_flow_exactly_to_interview_and_final_scores():
    source = granular_source()
    summary = result(source)["score_summary"]
    assert summary["ready"] and Fraction(summary["interview_score"]) == Fraction(351, 4)
    assert Fraction(summary["final_score"]) == Fraction(1703, 20)


def test_verified_off_topic_zero_survives_reporting_and_final_ranking():
    source = granular_source(off_topic=True)
    report = result(source)
    assert report["interviews"][0]["pairs"][0]["off_topic_zero_validated"]
    assert report["score_summary"]["ready"] and Fraction(report["score_summary"]["interview_score"]) == 0
    assert Fraction(report["score_summary"]["final_score"]) == Fraction(65, 2)


def test_off_topic_zero_cannot_bypass_relevance_evidence_provenance():
    source = granular_source(off_topic=True)
    source["interviews"][0]["analysis"]["result"]["pairs"][0]["assessment"]["relevance"]["citations"][0]["quote"] = "Fabricated words"
    assert not result(source)["score_summary"]["ready"]


def test_housekeeping_is_excluded_from_final_question_count_and_denominator():
    source = granular_source()
    interview = source["interviews"][0]
    analysis = interview["analysis"]
    q = {**copy.deepcopy(analysis["snapshot"]["segments"][0]), "id": "greeting-q", "text": "Hello Ashok. Can you hear me clearly?"}
    a = {**copy.deepcopy(analysis["snapshot"]["segments"][1]), "id": "greeting-a", "text": "Yes. I can hear you."}
    from app.agents.interview_analysis import digest
    for item in (q, a):
        item["hash"] = digest({k:v for k,v in item.items() if k != "hash"})
        interview["segments"][item["id"]] = item
        analysis["snapshot"]["segments"].append(item)
        analysis["snapshot"]["watermark"][item["id"]] = item["hash"]
    analysis["result"]["pairs"].insert(0, {"id": "greeting", "question_ids": [q["id"]], "answer_ids": [a["id"]], "context_ids": [], "state": "analysis_failed", "excluded": False, "analysis_error": "Old greeting analysis failed"})
    before = copy.deepcopy(source)
    report = result(source)
    assert report["score_summary"]["ready"] and report["score_summary"]["question_count"] == 1
    assert Fraction(report["score_summary"]["interview_score"]) == Fraction(351, 4)
    assert len(report["interviews"][0]["pairs"]) == 1 and source == before


def test_fixed_30_60_10_weights_and_question_average_are_exact():
    source = synthetic_source()
    summary = result(source)["score_summary"]
    assert summary["ready"]
    assert Fraction(summary["final_score"]) == Fraction(155, 2)
    assert Fraction(summary["interview_score"]) == 75
    assert (summary["cv_weight"], summary["interview_weight"], summary["practical_weight"]) == (30, 60, 10)
    analysis = source["interviews"][0]["analysis"]
    unanswered = copy.deepcopy(analysis["result"]["pairs"][0])
    unanswered.update(id="unanswered", state="unanswered", answer_ids=[], assessment=None, mappings=[])
    unanswered["score"].update(percentage=0, earned=0)
    for dimension in unanswered["score"]["breakdown"].values(): dimension["value"] = 0
    analysis["result"]["pairs"].append(unanswered)
    summary = result(source)["score_summary"]
    assert summary["ready"] and summary["question_count"] == 2 and summary["unanswered_count"] == 1
    assert Fraction(summary["interview_score"]) == Fraction(75, 2)
    assert Fraction(summary["final_score"]) == 55


def test_repaired_identity_gets_a_new_report_without_reanalysing_answers(consolidated):
    from app.models.candidate import Candidate, CandidateApplication
    from app.schemas.assessment import GenerateAssessment
    from scripts.repair_application_profiles import refresh_saved_reports
    t = consolidated
    old = t.assessments.enqueue(t.db, t.owner.id, t.row.application_id, GenerateAssessment())
    t.assessments.process(old.id); t.db.expire_all()
    previous_result = copy.deepcopy(t.db.get(AssessmentRun, old.id).result)
    app = t.db.get(CandidateApplication, t.row.application_id)
    t.db.get(Candidate, app.candidate_id).name = "Correct application name"
    app.response_data = {**app.response_data, "_identity_repair": {"version": "application-profile-v1"}}
    t.db.commit()
    calls = len(t.analysis.model.calls)
    new_ids = refresh_saved_reports(t.db, t.owner.id, [app.id], session_factory=t.assessments.factory)
    t.db.expire_all()
    assert len(new_ids) == 1 and new_ids[0] != old.id
    new = t.assessments.read(t.db, t.owner.id, new_ids[0])
    assert new["result"]["identification"]["candidate_name"] == "Correct application name"
    assert not new["stale"] and new["status"] == "completed"
    assert t.assessments.read(t.db, t.owner.id, old.id)["stale"]
    assert t.db.get(AssessmentRun, old.id).result == previous_result
    assert len(t.analysis.model.calls) == calls


@pytest.mark.parametrize("cv,expected", [("80", Fraction(79)), ("0", Fraction(55)), ("100", Fraction(85)), ("2.675", Fraction(22321, 400))])
def test_asymmetric_scores_use_exact_30_cv_60_interview_10_practical_arithmetic(cv, expected):
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


@pytest.mark.parametrize("case", ["missing", "pending", "legacy", "wrong_hash", "wrong_exercise", "wrong_interview", "forged_score", "missing_reviewer", "duplicate"])
def test_practical_requires_one_traceable_verified_and_approved_llm_score(case):
    source = synthetic_source()
    entry = source["practical_assessments"][0]
    if case == "missing": source["practical_assessments"] = []
    elif case == "pending": entry["assessment"] = None
    elif case == "legacy": entry["assessment"]["policy"] = "old-ai-review"
    elif case == "wrong_hash": entry["assessment"]["submission_hash"] = "b" * 64
    elif case == "wrong_exercise": entry["assessment"]["exercise_id"] = 999
    elif case == "wrong_interview": entry["interview_id"] = 999
    elif case == "forged_score": entry["assessment"]["score"] = 99
    elif case == "missing_reviewer": entry["assessment"]["approved_by"] = None
    elif case == "duplicate": source["practical_assessments"].append(copy.deepcopy(entry))
    summary = result(source)["score_summary"]
    assert not summary["ready"] and summary["final_score"] is None
    assert summary["practical_score"] is None and summary["interview_score"] == "75"


def test_approved_zero_is_not_pending_and_full_credit_adds_exactly_ten_points():
    source = synthetic_source()
    approved = result(source)["score_summary"]
    source["practical_assessments"][0]["assessment"] = practical_score(0)
    rejected = result(source)["score_summary"]
    assert rejected["ready"] and rejected["practical_score"] == "0"
    assert Fraction(approved["final_score"]) - Fraction(rejected["final_score"]) == 10


def test_partial_practical_credit_uses_the_exact_approved_llm_score():
    source = synthetic_source()
    source["practical_assessments"][0]["assessment"] = practical_score(83)
    summary = result(source)["score_summary"]
    assert summary["ready"] and summary["practical_score"] == "83"
    assert Fraction(summary["final_score"]) == Fraction(379, 5)


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
    source["practical_assessments"][0]["assessment"] = practical_score(0)
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


def test_durable_job_ranking_reuses_sources_and_detects_new_transcript(consolidated, monkeypatch):
    t = consolidated
    service = FinalRankingService(session_factory=t.assessments.factory)
    before = len(t.analysis.model.calls)
    monkeypatch.setattr(InterviewAnalysisService, "enqueue", lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("Fresh analysis must be reused")))
    ranking = service.start(t.db, t.owner.id, t.row.job_posting_id)
    assert ranking["status"] == "completed"
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


def test_missing_analysis_does_not_start_ai_or_block_final_ranking(consolidated, monkeypatch):
    t = consolidated
    # Expire the old source without removing immutable existing reports.
    analysis = t.analysis.latest(t.db, t.row.id)
    analysis.status = "failed"
    t.db.commit()
    service = FinalRankingService(session_factory=t.assessments.factory)
    before = len(t.analysis.model.calls)
    saved_score = t.analysis.latest(t.db, t.row.id).result["score_summary"]
    assert saved_score["ready"] and saved_score["percentage"] is not None
    monkeypatch.setattr(InterviewAnalysisService, "enqueue", lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("Ranking must never start AI analysis")))
    ranking = service.start(t.db, t.owner.id, t.row.job_posting_id)
    service.advance(ranking["id"]); t.db.expire_all()
    assert t.analysis.latest(t.db, t.row.id).status == "failed"
    count = len(list(t.db.scalars(select(InterviewAnalysisRun))))
    service.advance(ranking["id"]); t.db.expire_all()
    assert len(list(t.db.scalars(select(InterviewAnalysisRun)))) == count
    finish(t, service, ranking["id"])
    value = service.read(t.db, t.owner.id, t.row.job_posting_id)
    assert value["status"] == "completed"
    candidate = next(c for c in value["candidates"] if c["application_id"] == t.row.application_id)
    assert candidate["final_rank"] is None and candidate["interview_score"] is None and candidate["final_score"] is None
    assert "Analyze answers" in candidate["reason"]
    assert len(t.analysis.model.calls) == before


def test_legacy_display_only_scores_require_explicit_analyze_answers(consolidated):
    t = consolidated
    analysis = t.analysis.latest(t.db, t.row.id)
    original = copy.deepcopy(analysis.result)
    for pair in original["pairs"]: pair.pop("score", None)
    analysis.result = original
    t.db.commit()
    service = FinalRankingService(session_factory=t.assessments.factory)
    value = service.start(t.db, t.owner.id, t.row.job_posting_id)
    service.advance(value["id"]); t.db.expire_all()
    assert t.analysis.latest(t.db, t.row.id).id == analysis.id
    assert t.analysis.latest(t.db, t.row.id).status == "completed"
    candidate = next(c for c in value["candidates"] if c["application_id"] == t.row.application_id)
    assert candidate["final_score"] is None and "Analyze answers" in candidate["reason"]
    # Explicit Analyze answers can persist deterministic scores from validated,
    # unchanged judgments without asking the model to grade them again.
    from app.schemas.interview_analysis import StartAnalysis
    calls = len(t.analysis.model.calls)
    run = t.analysis.enqueue(t.db, t.owner.id, t.row.id, StartAnalysis(automatic=False))
    if run.status == "queued": t.analysis.process(run.id)
    t.db.expire_all()
    saved = t.analysis.latest(t.db, t.row.id)
    assert saved.result["score_summary"]["ready"]
    assert len(t.analysis.model.calls) == calls
    current = service.start(t.db, t.owner.id, t.row.job_posting_id)
    assert next(c for c in current["candidates"] if c["application_id"] == t.row.application_id)["final_rank"] is not None


def test_stale_transcript_is_not_rescored_by_final_ranking(consolidated, monkeypatch):
    t = consolidated
    t.db.get(TranscriptSegment, t.answer["id"]).text = "Changed saved answer"
    t.db.commit()
    count = len(list(t.db.scalars(select(InterviewAnalysisRun))))
    monkeypatch.setattr(InterviewAnalysisService, "enqueue", lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("No AI work during ranking")))
    value = FinalRankingService(session_factory=t.assessments.factory).start(t.db, t.owner.id, t.row.job_posting_id)
    assert value["status"] == "completed"
    candidate = next(c for c in value["candidates"] if c["application_id"] == t.row.application_id)
    assert candidate["interview_score"] is None and candidate["final_score"] is None
    assert "Analyze answers" in candidate["reason"]
    assert len(list(t.db.scalars(select(InterviewAnalysisRun)))) == count


def test_interview_summary_uses_saved_scores_and_never_counts_failures_as_zero(consolidated):
    from app.agents.interview_analysis import interview_score_summary, score_pair
    pair = copy.deepcopy(consolidated.analysis.latest(consolidated.db, consolidated.row.id).result["pairs"][0])
    unanswered = {"id": "unanswered", "state": "unanswered"}
    score_pair(unanswered)
    result = {"pairs": [pair, unanswered, {"id": "excluded", "state": "excluded"}], "reconciled": True}
    summary = interview_score_summary(result)
    assert summary["ready"] and summary["question_count"] == 2 and summary["unanswered_count"] == 1
    assert summary["percentage"] == pair["score"]["percentage"] / 2
    result["pairs"].append({"id": "failed", "state": "analysis_failed"})
    summary = interview_score_summary(result)
    assert not summary["ready"] and summary["percentage"] is None and summary["scored_count"] == 2


def test_central_assistant_can_start_fixed_weight_job_ranking(consolidated):
    from app.services.supervisor_service import SupervisorService
    from app.agents.supervisor_tools import AssessmentToolRequest
    t = consolidated
    supervisor = SimpleNamespace(state_json={"selected_screening_job_posting_id": t.row.job_posting_id})
    instance = object.__new__(SupervisorService)
    result = instance._assessments_tool(t.db, supervisor, t.owner.id, AssessmentToolRequest(operation="rank"))
    assert result["refresh_required"] and "interview 60% + CV 30% + practical task 10%" in result["assistant_message"]
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
    with pytest.raises(LookupError): t.reports.request(t.db, t.other.id, ExportReport(format="html"), comparison_id=value["id"])
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
