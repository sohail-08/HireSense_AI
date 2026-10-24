"""Synthetic text only; no external LLM, Google, SMTP, media or provider calls."""
import copy
import importlib.util
from datetime import timedelta
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, inspect, create_engine
from sqlalchemy.orm import Session
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.assessments.workflow import ConsolidatedAssessmentGraph
from app.assessments.reports import render_html
from app.assessments.sources import resolve_sources
from app.models.assessment import AssessmentRun, AssessmentComparison, AssessmentReview, ReportArtifact
from app.models.scoring import CandidateScore
from app.models.transcription import TranscriptSegment
from app.schemas.assessment import GenerateAssessment, ExportReport, ReviewAssessment
from app.schemas.interview_analysis import StartAnalysis, ReferenceUpdate
from app.services.assessment_service import AssessmentService
from app.services.report_service import ReportService
from app.database import get_db
from app.security import create_access_token
from app.routes import assessments as routes
from assessment_fixtures import synthetic_source
from test_interview_analysis import saved, Model  # noqa: F401
from test_transcription import transcription  # noqa: F401
from test_interview_rooms import room_setup  # noqa: F401
from test_interviews import setup, records  # noqa: F401


class FailingModel:
    def generate_json(self, **kwargs): raise RuntimeError("PRIVATE provider failure")


def report(source=None, model=None):
    source = source or synthetic_source()
    return ConsolidatedAssessmentGraph(model=model).graph.invoke({"snapshot": source})["result"]


def test_actual_graph_nodes_and_edges():
    graph = ConsolidatedAssessmentGraph().graph.get_graph()
    stages = ["__start__", "resolve_source_versions", "validate_readiness", "build_requirement_matrix", "aggregate_components", "draft_summary", "validate_claims_citations", "persist_assessment", "__end__"]
    assert set(graph.nodes) == set(stages)
    assert {(e.source, e.target) for e in graph.edges} == set(zip(stages, stages[1:]))


def test_saved_scores_and_evidence_survive_without_combined_score():
    source = synthetic_source()
    result = report(source)
    assert result["cv"]["final_score"] == source["cv"]["final_score"]
    assert result["cv"]["categories"] == source["cv"]["categories"]
    assert result["matrix"][0]["interview_statuses"] == ["supporting_evidence"]
    assert result["matrix"][1]["interview_coverage"] == "not_explored"
    assert "combined_score" not in result
    for fact in result["facts"]: assert all(i in result["evidence"] for i in fact["evidence_ids"])
    source["cv"]["screening_document_sha256"] = "different-cv-revision"
    invalid = report(source)
    assert not any(e["kind"] == "cv" for e in invalid["evidence"].values())
    source["cv"]["screening_requirement_version"] = "different-requirement-version"
    assert report(source)["matrix"][0]["cv_status"] == "missing_processing"


def test_four_part_summary_is_deterministic_traceable_and_separates_missing_evidence():
    source = synthetic_source()
    before = copy.deepcopy(source)
    result = report(source)
    summary = result["evidence_summary"]
    assert set(summary) == {"strengths", "weaknesses", "evidence_gaps", "verification"}
    assert all(summary.values())
    for category, findings in summary.items():
        for finding in findings:
            assert finding["evidence_ids"] and all(e in result["evidence"] for e in finding["evidence_ids"])
            if category == "weaknesses":
                assert any(result["evidence"][e]["kind"] == "transcript" for e in finding["evidence_ids"])
                assert "Automated testing" not in finding["text"]  # Not explored, not a weakness.
    assert report(source)["evidence_summary"] == summary and source == before
    html = render_html({"kind": "individual", "reports": [{"id": 1, "result": result, "created_at": "2026-10-22T00:00:00Z"}]})
    for heading in ("Candidate performance", "Strengths", "Areas to improve", "Not yet assessed", "Needs checking"):
        assert heading in html
    assert "Source version" in html


def test_uncertain_transcription_cannot_become_a_report_weakness_or_final_score():
    source = synthetic_source()
    pair = source["interviews"][0]["analysis"]["result"]["pairs"][0]
    pair["state"] = "needs_clarification"
    pair.pop("score")
    pair["assessment"]["interpretation"] = {"status": "uncertain", "meaning": "Unclear negation.",
        "citations": copy.deepcopy(pair["assessment"]["relevance"]["citations"]), "notes": [], "support_status": "supported_by_check"}
    result = report(source)
    assert not result["score_summary"]["ready"] and result["score_summary"]["final_score"] is None
    assert not result["evidence_summary"]["weaknesses"]
    assert not any(f.get("interview_id") for f in result["evidence_summary"]["strengths"])
    assert result["evidence_summary"]["verification"]
    assert result["matrix"][0]["interview_statuses"] == ["insufficient_evidence"]


def test_summary_does_not_repair_tampered_provenance_into_a_supported_conclusion():
    source = synthetic_source()
    pair = source["interviews"][0]["analysis"]["result"]["pairs"][0]
    for dim in pair["assessment"].values():
        dim["citations"][0]["start_offset_ms"] += 1
    result = report(source)
    assert not any(f.get("interview_id") for f in result["evidence_summary"]["strengths"])
    assert not result["evidence_summary"]["weaknesses"]
    assert not result["score_summary"]["ready"]
    assert result["interviews"][0]["pairs"][0]["score"] is None


@pytest.mark.parametrize("field", ["revision", "speaker", "quote", "start_offset_ms", "session_id"])
def test_tampered_transcript_citations_are_excluded(field):
    source = synthetic_source()
    pair = source["interviews"][0]["analysis"]["result"]["pairs"][0]
    pair["mappings"][0]["citations"][0][field] = "tampered"
    result = report(source)
    assert result["matrix"][0]["interview_statuses"] == ["insufficient_evidence"]
    assert result["flags"] and result["completeness"] == "partial"


def test_unanswered_not_explored_conflicts_and_unverified_are_distinct():
    source = synthetic_source()
    pair = source["interviews"][0]["analysis"]["result"]["pairs"][0]
    pair["state"], pair["answer_ids"], pair["assessment"], pair["mappings"] = "unanswered", [], None, []
    result = report(source)
    assert result["matrix"][0]["interview_coverage"] == "asked_unanswered"
    assert result["matrix"][1]["interview_coverage"] == "not_explored"
    assert result["matrix"][0]["interview_statuses"] == ["not_assessed"]
    pair["state"], pair["answer_ids"] = "analysis_failed", ["a1"]
    assert report(source)["matrix"][0]["interview_coverage"] == "asked_answer_pending"
    source = synthetic_source()
    pair = source["interviews"][0]["analysis"]["result"]["pairs"][0]
    pair["mappings"][0]["status"] = "contradictory_evidence"
    pair["assessment"]["accuracy"]["label"] = "unable_to_verify"
    result = report(source)
    assert result["matrix"][0]["conflict"]
    assert any("Unable to verify" in f["text"] for f in result["facts"])


def test_logical_support_failure_and_bounded_llm_fallback():
    source = synthetic_source()
    pair = source["interviews"][0]["analysis"]["result"]["pairs"][0]
    pair["mappings"][0]["support_status"] = "unsupported"
    result = report(source, FailingModel())
    assert result["matrix"][0]["interview_statuses"] == ["insufficient_evidence"]
    assert result["summary"]["basis"].startswith("Deterministic")


def test_html_autoescaping_no_remote_assets_or_executable_candidate_content():
    result = report()
    result["identification"]["candidate_name"] = '<script src="https://bad.invalid/x">secret</script>'
    run = {"id": 1, "version": 1, "result": result, "notes": [], "created_at": "2026-10-22T02:00:00Z", "review_status": "not_reviewed"}
    html = render_html({"kind": "individual", "reports": [run]})
    assert "<script" not in html and "&lt;script" in html
    assert "default-src 'none'" in html
    assert "22 Oct 2026 at 8:00 AM (Dhaka time)" in html
    assert "2026-10-22T02:00:00Z" not in html


@pytest.fixture
def consolidated(saved, monkeypatch, tmp_path):
    t = saved
    t.analysis.references(t.db, t.owner.id, t.row.id, ReferenceUpdate(revision=0, approved=True, references=[{
        "id": "guide", "title": "Database transactions", "kind": "answer_guide", "content": "Transactions are atomic."}]))
    run = t.analysis.enqueue(t.db, t.owner.id, t.row.id, StartAnalysis())
    t.analysis.process(run.id)
    t.db.expire_all()
    t.row.status, t.row.room_status = "completed", "ended"
    t.db.commit()
    from app.models.work_sample import WorkSampleExercise, WorkSampleAttempt, WorkSampleAssessment
    from app.agents.practical_scoring import POLICY, PROMPT_VERSION, LIMITATION
    from app.agents.interview_analysis import digest
    from datetime import datetime, timezone
    task = {"title": "Synthetic short task", "instructions": "Provide a short synthetic response to this task.", "materials": "Synthetic materials",
        "deliverables": "A short response", "duration_minutes": 10, "response_type": "text", "tools_policy": "Supplied materials only"}
    practical = WorkSampleExercise(interview_id=t.row.id, application_id=t.row.application_id, owner_id=t.owner.id,
        task=task, task_hash=digest(task), status="submitted", expires_at=datetime.now(timezone.utc) + timedelta(days=30))
    t.db.add(practical); t.db.flush()
    submission = WorkSampleAttempt(exercise_id=practical.id, number=1, status="submitted", content="Synthetic response", explanation="",
        remaining_seconds=0, revision=1, submission_hash=digest({"task_hash": practical.task_hash, "attempt": 1,
            "content": "Synthetic response", "explanation": "", "status": "submitted"}))
    t.db.add(submission); t.db.flush()
    evaluation = {"score": 100, "summary": "Synthetic approved correctness review.", "verified": True,
        "evidence": [{"line_start": 1, "line_end": 1, "quote": "Synthetic response"}],
        "verification_reason": "Synthetic independent support check.", "limitation": LIMITATION}
    t.db.add(WorkSampleAssessment(attempt_id=submission.id, status="approved", result=evaluation, approved_result=copy.deepcopy(evaluation),
        snapshot={"policy": POLICY, "exercise_id": practical.id, "task_hash": practical.task_hash, "submission_hash": submission.submission_hash,
            "task": copy.deepcopy(task), "content": submission.content, "status": submission.status,
            "model": "synthetic", "prompt_version": PROMPT_VERSION}, approved_by=t.owner.id, approved_at=datetime.now(timezone.utc)))
    t.db.commit()
    t.assessments = AssessmentService(model=FailingModel(), session_factory=lambda: Session(t.db.get_bind(), expire_on_commit=False))
    t.reports = ReportService(session_factory=t.assessments.factory)
    for module in ("app.services.report_service", "app.services.assessment_service"):
        monkeypatch.setattr(module + ".private_storage_path", lambda key: tmp_path / key)
    t.assessment_id = t.assessments.enqueue(t.db, t.owner.id, t.row.application_id, GenerateAssessment()).id
    t.assessments.process(t.assessment_id)
    t.db.expire_all()
    assert t.db.get(AssessmentRun, t.assessment_id).status == "completed"
    return t


def test_idempotency_source_specific_staleness_notes_and_versions(consolidated):
    t = consolidated
    first = t.assessments.read(t.db, t.owner.id, t.assessment_id)
    assert not first["stale"]
    assert t.assessments.enqueue(t.db, t.owner.id, t.row.application_id, GenerateAssessment()).id == t.assessment_id
    second = t.assessments.enqueue(t.db, t.owner.id, t.row.application_id, GenerateAssessment(new_version=True))
    assert second.version == first["version"] + 1
    t.assessments.review(t.db, t.owner.id, t.assessment_id, ReviewAssessment(note="Synthetic interviewer note", reviewed=True))
    assert not t.assessments.read(t.db, t.owner.id, t.assessment_id)["stale"]
    t.db.get(TranscriptSegment, t.answer["id"]).text = "Updated synthetic transcript revision"
    t.db.commit()
    assert t.assessments.read(t.db, t.owner.id, t.assessment_id)["stale"]
    assert first["result"] == t.db.get(AssessmentRun, t.assessment_id).result


def test_old_formula_report_stays_immutable_and_new_request_uses_current_weights(consolidated):
    t = consolidated
    row = t.db.get(AssessmentRun, t.assessment_id)
    saved = copy.deepcopy(row.result)
    saved["score_summary"].update(formula_version="cv50-interview50-v1", cv_weight=50, interview_weight=50)
    row.result = saved
    row.snapshot = {**copy.deepcopy(row.snapshot), "prompt_version": "consolidation-old-50-50"}
    row.fingerprint = "synthetic-historical-weighted-report"
    t.db.commit()
    historical = t.assessments.read(t.db, t.owner.id, row.id)
    assert historical["stale"] and historical["result"]["score_summary"]["cv_weight"] == 50
    before = len(t.analysis.model.calls)
    new = t.assessments.enqueue(t.db, t.owner.id, t.row.application_id, GenerateAssessment())
    assert new.id != row.id
    t.assessments.process(new.id)
    t.db.expire_all()
    current = t.assessments.read(t.db, t.owner.id, new.id)
    assert not current["stale"]
    assert current["result"]["score_summary"]["cv_weight"] == 30
    assert current["result"]["score_summary"]["interview_weight"] == 60
    assert current["result"]["score_summary"]["practical_weight"] == 10
    assert t.db.get(AssessmentRun, row.id).result == saved
    assert len(t.analysis.model.calls) == before


@pytest.mark.parametrize("cv_weight,interview_weight", [(40, 60), (50, 50)])
def test_export_formula_uses_saved_weights(cv_weight, interview_weight):
    value = report()
    value["score_summary"].update(ready=True, cv_weight=cv_weight, interview_weight=interview_weight)
    html = render_html({"kind": "individual", "reports": [{"id": 1, "result": value, "created_at": "2026-10-22T00:00:00Z"}]})
    assert f"CV {cv_weight}% + interview {interview_weight}%" in html


def test_source_ownership_and_explicit_selection(consolidated):
    t = consolidated
    with pytest.raises(LookupError): t.assessments.read(t.db, t.other.id, t.assessment_id)
    with pytest.raises(LookupError): resolve_sources(t.db, t.owner.id, t.row.application_id, GenerateAssessment(interview_ids=[9999]))
    cv_only = resolve_sources(t.db, t.owner.id, t.row.application_id, GenerateAssessment(interview_ids=[]))
    assert cv_only["cv"] and cv_only["interviews"] == [] and cv_only["missing"]
    score = t.db.scalar(select(CandidateScore).where(CandidateScore.application_id == t.row.application_id))
    t.db.delete(score); t.db.commit()
    unscored = resolve_sources(t.db, t.owner.id, t.row.application_id, GenerateAssessment())
    assert unscored["cv"]["matches"] and unscored["cv"]["final_score"] is None


def test_ties_preserve_original_cohort_and_incompatible_comparison(consolidated):
    t = consolidated
    original = t.db.get(AssessmentRun, t.assessment_id)
    other_app = next(i for i in t.db.scalars(select(__import__("app.models.candidate", fromlist=["CandidateApplication"]).CandidateApplication)) if i.id != original.application_id)
    result = copy.deepcopy(original.result)
    result["identification"]["application_id"] = other_app.id
    snapshot = copy.deepcopy(original.snapshot)
    snapshot["identification"]["application_id"] = other_app.id
    # Explicit immutable test reports isolate comparison arithmetic from source selection.
    second = AssessmentRun(application_id=other_app.id, job_posting_id=original.job_posting_id, version=1, fingerprint="synthetic-comparison", snapshot=snapshot, result=result, status="completed", stage="completed", completeness="partial", created_by=t.owner.id)
    t.db.add(second); t.db.commit()
    real_read = t.assessments.read
    t.assessments.read = lambda db, uid, rid: {**real_read(db, uid, rid), "stale": False}
    compared = t.assessments.compare(t.db, t.owner.id, [original.id, second.id])["snapshot"]
    assert compared["cv_order_compatible"] and compared["combined_ranking_available"]
    assert [r["final_rank"] for r in compared["assessments"]] == [1, 1]
    assert all(r["result"]["cv"]["original_cohort"] == original.result["cv"]["original_cohort"] for r in compared["assessments"])
    second.result = {**second.result, "cv": {**second.result["cv"], "formula_version": "incompatible-formula"}}
    t.db.commit()
    assert not t.assessments.compare(t.db, t.owner.id, [original.id, second.id])["snapshot"]["cv_order_compatible"]


def test_exports_persist_hash_pdf_failure_and_delete_cascade(consolidated):
    t = consolidated
    html = t.reports.request(t.db, t.owner.id, ExportReport(format="html"), assessment_id=t.assessment_id)
    assert t.reports.request(t.db, t.owner.id, ExportReport(format="html"), assessment_id=t.assessment_id)["id"] == html["id"]
    t.reports.process(html["id"]); t.db.expire_all()
    path, _ = t.reports.download(t.db, t.owner.id, html["id"])
    assert path.is_file() and t.reports.read(t.db, t.owner.id, html["id"])["sha256"]
    pdf = t.reports.request(t.db, t.owner.id, ExportReport(format="pdf"), assessment_id=t.assessment_id)
    t.reports.pdf_renderer = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("PRIVATE failure"))
    t.reports.process(pdf["id"]); t.db.expire_all()
    assert t.reports.read(t.db, t.owner.id, pdf["id"])["status"] == "failed"
    assert t.assessments.read(t.db, t.owner.id, t.assessment_id)["status"] == "completed"
    t.assessments.delete_sources(t.db, application_ids=[t.row.application_id]); t.db.commit()
    assert not path.exists() and t.db.get(AssessmentRun, t.assessment_id) is None
    assert t.db.get(ReportArtifact, html["id"]) is None


def test_api_owner_candidate_denial_and_private_exports(consolidated):
    t = consolidated
    app = FastAPI(); app.include_router(routes.router)
    app.dependency_overrides[get_db] = lambda: t.db
    with TestClient(app) as client:
        path = f"/api/assessments/runs/{t.assessment_id}"
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"Authorization": f"Bearer {create_access_token(t.other.id)}"}).status_code == 403
        response = client.get(path, headers={"Authorization": f"Bearer {create_access_token(t.owner.id)}"})
        assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
        assert "storage_key" not in response.text and "meeting_url" not in response.text


def test_additive_migration_creates_and_drops_only_empty_new_tables(tmp_path):
    spec = importlib.util.spec_from_file_location("assessment_migration", Path(__file__).parents[1] / "alembic/versions/0022_consolidated_assessment.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        assert {"assessment_runs", "assessment_reviews", "assessment_comparisons", "report_artifacts"}.issubset(inspect(connection).get_table_names())
        module.downgrade()
        assert "assessment_runs" not in inspect(connection).get_table_names()


def test_read_export_and_review_do_not_rerun_upstream_ai(consolidated):
    t = consolidated
    calls = len(t.analysis.model.calls)
    for _ in range(3):
        t.assessments.read(t.db, t.owner.id, t.assessment_id)
        t.assessments.list_application(t.db, t.owner.id, t.row.application_id)
    artifact = t.reports.request(t.db, t.owner.id, ExportReport(format="html"), assessment_id=t.assessment_id)
    t.reports.process(artifact["id"])
    assert len(t.analysis.model.calls) == calls


def test_nonfinalized_failed_or_missing_sources_cannot_be_complete(consolidated):
    from app.models.transcription import TranscriptionSession
    from app.models.interview_analysis import InterviewAnalysisRun
    t = consolidated
    session = t.db.get(TranscriptionSession, t.sid)
    session.status = "running"
    t.db.commit()
    source = resolve_sources(t.db, t.owner.id, t.row.application_id, GenerateAssessment())
    source["model"] = "mock"
    assert any("Finalized transcript" in m for m in source["missing"])
    assert report(source)["completeness"] == "partial"
    session.status = "failed"
    analysis = t.db.scalar(select(InterviewAnalysisRun))
    analysis.status = "failed"
    t.db.commit()
    source = resolve_sources(t.db, t.owner.id, t.row.application_id, GenerateAssessment())
    assert source["flags"] and source["interviews"][0]["analysis"] is None


def test_restart_recovery_preserves_saved_results_and_requeues_interrupted_work(consolidated):
    t = consolidated
    before = copy.deepcopy(t.db.get(AssessmentRun, t.assessment_id).result)
    second = t.assessments.enqueue(t.db, t.owner.id, t.row.application_id, GenerateAssessment(new_version=True))
    second.status = "processing"
    artifact = t.reports.request(t.db, t.owner.id, ExportReport(format="html"), assessment_id=t.assessment_id)
    t.db.get(ReportArtifact, artifact["id"]).status = "processing"
    t.db.commit()
    t.assessments.recover(t.db)
    t.db.expire_all()
    assert t.db.get(AssessmentRun, second.id).status == "queued"
    assert t.db.get(ReportArtifact, artifact["id"]).status == "queued"
    assert t.db.get(AssessmentRun, t.assessment_id).result == before


def test_expired_reports_are_denied_and_physical_exports_removed(consolidated):
    from app.services.assessment_service import now
    t = consolidated
    artifact = t.reports.request(t.db, t.owner.id, ExportReport(format="html"), assessment_id=t.assessment_id)
    t.reports.process(artifact["id"]); t.db.expire_all()
    path, _ = t.reports.download(t.db, t.owner.id, artifact["id"])
    t.db.get(AssessmentRun, t.assessment_id).expires_at = now() - timedelta(seconds=1)
    t.db.commit()
    with pytest.raises(LookupError): t.reports.download(t.db, t.owner.id, artifact["id"])
    t.assessments.delete_sources(t.db, expired=True); t.db.commit()
    assert not path.exists()


def test_corrupt_export_can_be_rebuilt_and_rollback_retains_file(consolidated):
    t = consolidated
    artifact = t.reports.request(t.db, t.owner.id, ExportReport(format="html"), assessment_id=t.assessment_id)
    t.reports.process(artifact["id"]); t.db.expire_all()
    path, _ = t.reports.download(t.db, t.owner.id, artifact["id"])
    path.write_bytes(b"tampered synthetic file")
    with pytest.raises(ValueError): t.reports.download(t.db, t.owner.id, artifact["id"])
    assert t.reports.request(t.db, t.owner.id, ExportReport(format="html", retry=True), assessment_id=t.assessment_id)["status"] == "queued"
    t.reports.process(artifact["id"]); t.db.expire_all()
    path, _ = t.reports.download(t.db, t.owner.id, artifact["id"])
    t.assessments.delete_sources(t.db, application_ids=[t.row.application_id]); t.db.rollback()
    assert path.is_file() and t.db.get(AssessmentRun, t.assessment_id)


def test_other_interviewer_cannot_download_private_report(consolidated):
    from types import SimpleNamespace
    from app.security import require_interviewer
    t = consolidated
    artifact = t.reports.request(t.db, t.owner.id, ExportReport(format="html"), assessment_id=t.assessment_id)
    app = FastAPI(); app.include_router(routes.router)
    app.dependency_overrides[get_db] = lambda: t.db
    # The product permits one stored interviewer. Exercise a future authorized
    # principal without violating that existing unique-role database policy.
    app.dependency_overrides[require_interviewer] = lambda: SimpleNamespace(id=t.other.id)
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer " + create_access_token(t.other.id)}
        assert client.get(f"/api/assessments/runs/{t.assessment_id}", headers=headers).status_code == 404
        assert client.get(f"/api/assessments/exports/{artifact['id']}/download", headers=headers).status_code == 404


def test_renderer_uses_offline_context_disables_javascript_and_bounds_pdf(monkeypatch):
    import playwright.sync_api
    calls = {}
    class Page:
        def set_default_timeout(self, timeout): calls["timeout"] = timeout
        def set_content(self, content, **kwargs): calls["content"] = kwargs
        def pdf(self, **kwargs): calls["pdf"] = kwargs; return b"%PDF-synthetic"
    class Context:
        def route(self, route, handler): calls["route"] = route
        def new_page(self): return Page()
    class Browser:
        def new_context(self, **kwargs): calls["context"] = kwargs; return Context()
        def close(self): calls["closed"] = True
    class Chromium:
        def launch(self, **kwargs): calls["launch"] = kwargs; return Browser()
    class Playwright:
        chromium = Chromium()
        def __enter__(self): return self
        def __exit__(self, *_): pass
    from app.assessments import pdf_worker
    monkeypatch.setattr(pdf_worker, "sync_playwright", lambda: Playwright())
    assert pdf_worker.render("<p>synthetic</p>") == b"%PDF-synthetic"
    assert calls["context"] == {"java_script_enabled": False, "service_workers": "block", "offline": True}
    assert calls["route"] == "**/*" and calls["content"]["timeout"] == 15000 and calls["closed"]


def test_pdf_process_has_a_hard_deadline(monkeypatch):
    from app.assessments import reports
    calls = {}
    class Process:
        returncode = 0
        def communicate(self, data, timeout): calls["timeout"] = timeout; return b"%PDF-synthetic", b""
    monkeypatch.setattr(reports.subprocess, "Popen", lambda *_args, **_kwargs: Process())
    assert reports.render_pdf("<p>Synthetic</p>") == b"%PDF-synthetic"
    assert calls["timeout"] == 55


def test_native_supervisor_report_tool_uses_selected_authorized_saved_results(consolidated):
    from types import SimpleNamespace
    from app.agents.supervisor_tools import SupervisorToolCallbacks, build_supervisor_tools, AssessmentToolRequest
    from app.agents.supervisor import HireSenseSupervisorGraph
    from app.services.supervisor_service import SupervisorService
    from supervisor_fakes import QueueToolModel
    t = consolidated
    supervisor = SimpleNamespace(state_json={"selected_application_ids": [t.row.application_id], "selected_screening_job_posting_id": t.row.job_posting_id})
    instance = object.__new__(SupervisorService)
    def callback(message, request): return instance._assessments_tool(t.db, supervisor, t.owner.id, request)
    def unsupported(*_): raise AssertionError("No upstream workflow may run")
    callbacks = SupervisorToolCallbacks(generate_job_description=unsupported,
        edit_job_description=unsupported, approve_job_description=unsupported, job_posting=unsupported,
        help=unsupported, sync_responses=unsupported, screen_candidates=unsupported, assessments=callback)
    model = QueueToolModel(["candidate_assessments"])
    tools = build_supervisor_tools(callbacks, user_message="Show the consolidated assessment")
    output = HireSenseSupervisorGraph(model, tools).invoke(message="Show the consolidated assessment", context={})
    assert output["tool_name"] == "candidate_assessments"
    assert output["tool_result"]["assessment_links"][0]["path"].endswith(f"run={t.assessment_id}")
    assert "bind" not in output["tool_result"]
    with pytest.raises(LookupError):
        instance._assessments_tool(t.db, supervisor, t.other.id, AssessmentToolRequest())
