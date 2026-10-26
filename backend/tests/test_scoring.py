from copy import deepcopy
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models.scoring import CandidateScore, ScoringConfiguration, ScoringRun
from app.models.screening import RequirementMatch, RequirementMatchStatus, ScreeningRun, ScreeningRunStatus
from app.routes.scoring import router
from app.schemas.scoring import ScoreRunRequest, ScoringApproval
from app.security import create_access_token
from app.services.candidate_application_service import CandidateApplicationService
from app.services.scoring_calculation import assign_ranks, category_scores, display_score, justification, weighted_score
from app.services.scoring_service import ScoringConflict, ScoringService
from app.services.screening_service import ScreeningService
from test_screening import FakeScreeningAI, _application_with_docx, _records, _settings
from test_pgvector import pg_database, _config


def saved_fixture():
    configuration = {"requirement_version": "fixed-v1", "category_weights": {"technical": "50", "experience": "30", "qualification": "20"}, "requirements": []}
    application = {"screening_status": "completed", "source_blocks": [{"id": "page-1", "locator": "PDF page 1", "text": "Built APIs. Worked 2020-2024. Degree in computing."}], "matches": []}
    for key, category, weight, status, classification in [
        ("skill:0", "technical", "3", "met", "required"),
        ("skill:1", "technical", "2", "partially_met", "preferred"),
        ("experience:0", "experience", "1", "partially_met", "required"),
        ("qualification:0", "qualification", "1", "met", "required"),
    ]:
        configuration["requirements"].append({"requirement_id": key, "name": key, "evaluation_criterion": key,
                                            "category": category, "classification": classification, "weight": weight, "requirement_version": "fixed-v1"})
        application["matches"].append({"requirement_key": key, "status": status, "evidence": [{"block_id": "page-1", "quote": "Built APIs."}]})
    return configuration, application


def calculate(configuration, application):
    return weighted_score(configuration, category_scores(configuration, application))


def test_exact_scores_and_approved_weights():
    configuration, application = saved_fixture()
    result = calculate(configuration, application)
    assert {key: Decimal(value["score"]) for key, value in result["categories"].items()} == {
        "technical": Decimal(80), "experience": Decimal(50), "qualification": Decimal(100)}
    assert Decimal(result["final_score"]) == 75
    assert result["requirements"][1]["weighted_contribution"] == "1"
    assert result["counts"] == {"met": 2, "partially_met": 2, "unmet": 0}
    assert result["required_gaps"] == ["experience:0"]
    assert result["review_state"] == "ranked"
    assert calculate(configuration, application) == result


@pytest.mark.parametrize("status", ["met", "partially_met", "unmet", "unable_to_determine"])
def test_evidence_only_criteria_never_change_numeric_scores(status):
    configuration, application = saved_fixture()
    before = calculate(configuration, application)
    configuration["requirements"].append({"requirement_id": "selection_criterion:0", "name": "Delivery evidence",
        "evaluation_criterion": "Delivery evidence", "category": None, "classification": "required", "weight": "1000", "requirement_version": "fixed-v1"})
    application["matches"].append({"requirement_key": "selection_criterion:0", "status": status,
        "evidence": [{"block_id": "page-1", "quote": "Built APIs."}]})
    after = calculate(configuration, application)
    assert after["final_score"] == before["final_score"]
    assert after["categories"] == before["categories"]
    evidence_only = after["requirements"][-1]
    assert evidence_only["weighted_contribution"] == "0"
    assert evidence_only["score_included"] is False
    assert evidence_only["evidence"][0]["quote"] == "Built APIs."
    assert "Evidence-only selection criteria" in justification(after)


@pytest.mark.parametrize("status,value", [("met", "1"), ("partially_met", "0.5"), ("unmet", "0"), ("unable_to_determine", "0")])
def test_fixed_status_values(status, value):
    configuration, application = saved_fixture()
    application["matches"][0]["status"] = status
    result = calculate(configuration, application)
    assert result["requirements"][0]["match_value"] == value
    assert result["requirements"][0]["weighted_contribution"] == str(Decimal(value) * 3)
    if status == "unable_to_determine":
        assert result["requirements"][0]["status"] == "unmet"
        assert result["review_state"] == "ranked"
        assert set(result["counts"]) == {"met", "partially_met", "unmet"}


def test_missing_category_and_zero_weight_handling():
    configuration, application = saved_fixture()
    configuration["requirements"] = configuration["requirements"][:2]
    with pytest.raises(ValueError, match="zero category weight"):
        calculate(configuration, application)
    configuration["category_weights"] = {"technical": "100", "experience": "0", "qualification": "0"}
    result = calculate(configuration, application)
    assert result["categories"]["qualification"]["score"] is None
    assert Decimal(result["final_score"]) == 80
    configuration["requirements"][0]["weight"] = "0"
    assert Decimal(calculate(configuration, application)["final_score"]) == 50
    configuration["requirements"][1]["weight"] = "0"
    with pytest.raises(ValueError):
        calculate(configuration, application)


def test_precision_rounding_and_exact_ranks():
    assert display_score("82.345") == "82.35"
    assert display_score("82.344999999999999999999999") == "82.34"
    configuration, application = saved_fixture()
    configuration["requirements"][0]["weight"] = "1"
    application["matches"][1]["status"] = "unmet"
    result = calculate(configuration, application)
    assert len(result["categories"]["technical"]["score"].replace(".", "")) == 28
    assert "numerator" in result["exact_final_score"]
    inputs = []
    for app_id, score, review in [(4, 70, False), (3, 82, False), (1, 88, False), (2, 82, False), (5, 99, True)]:
        inputs.append({"application_id": app_id, "breakdown": {"exact_final_score": {"numerator": str(score), "denominator": "1"}, "review_state": "review_required" if review else "ranked"}})
    ordered = assign_ranks(inputs)
    assert [(item["application_id"], item["rank"]) for item in ordered] == [(5, 1), (1, 2), (2, 3), (3, 3), (4, 5)]


def test_justification_is_grounded_and_unsupported_claims_rejected():
    configuration, application = saved_fixture()
    application["matches"][0]["explanation"] = "Candidate won a Nobel Prize."
    result = calculate(configuration, application)
    text = justification(result)
    assert "Nobel" not in text
    assert "[page-1]" in text and "Built APIs." in text
    assert text == justification(deepcopy(result))
    application["matches"][0]["evidence"][0]["quote"] = "Candidate won a Nobel Prize."
    result = calculate(configuration, application)
    assert result["requirements"][0]["status"] == "unmet"
    assert result["review_state"] == "ranked"
    assert "Nobel" not in justification(result)


@pytest.fixture
def records(tmp_path):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        owner, other, posting = _records(db)
        application, document = _application_with_docx(db, tmp_path, posting, 1)
        db.commit()
        screening = ScreeningService(_settings(tmp_path), ai=FakeScreeningAI())
        batch = screening.create_batch(db, interviewer_user_id=owner.id, job_posting_id=posting.id, application_ids=None)
        screening.process_batch(db, batch_id=batch.id)
        yield db, owner, other, posting, application, document, tmp_path
    engine.dispose()


def approval(db, owner, posting, **overrides):
    proposal = ScoringService.proposal(db, user_id=owner.id, job_id=posting.id)
    data = {"confirmed": True, "requirement_version": proposal["requirement_version"],
            "category_weights": {"technical": 100, "experience": 0, "qualification": 0},
            "requirements": [{key: item[key] for key in ("requirement_id", "category", "classification", "weight")} for item in proposal["requirements"]]}
    data.update(overrides)
    return ScoringApproval.model_validate(data)


def test_snapshot_reuse_idempotency_and_changed_inputs(records):
    db, owner, other, posting, app, document, _ = records
    service = ScoringService()
    configuration = service.approve(db, user_id=owner.id, job_id=posting.id, data=approval(db, owner, posting))
    request = ScoreRunRequest(configuration_id=configuration["id"], idempotency_key="first")
    first = service.run(db, user_id=owner.id, job_id=posting.id, data=request)
    assert first["results"][0]["rank"] == 1
    assert first["results"][0]["display_score"] == "66.67"
    assert service.run(db, user_id=owner.id, job_id=posting.id, data=request) == first
    assert service.run(db, user_id=owner.id, job_id=posting.id, data=ScoreRunRequest(configuration_id=configuration["id"], idempotency_key="alias"))["id"] == first["id"]
    assert db.scalar(select(func.count(ScoringRun.id))) == 1
    match = db.scalar(select(RequirementMatch).where(RequirementMatch.name == "Docker"))
    match.status = RequirementMatchStatus.PARTIALLY_MET
    match.evidence = [{"block_id": "docx-paragraph-2", "quote": "Built Python APIs with FastAPI."}]
    db.commit()
    next_run = service.run(db, user_id=owner.id, job_id=posting.id, data=ScoreRunRequest(configuration_id=configuration["id"]))
    assert next_run["id"] != first["id"]
    assert next_run["results"][0]["display_score"] == "83.33"
    assert service.detail(db, user_id=owner.id, run_id=first["id"]) == first
    assert service.run(db, user_id=owner.id, job_id=posting.id, data=request) == first
    db.expire_all()  # Re-read saved values, not in-memory calculation results.
    assert service.detail(db, user_id=owner.id, run_id=first["id"]) == first
    with pytest.raises(LookupError):
        service.detail(db, user_id=other.id, run_id=first["id"])


def test_evidence_presentation_enriches_existing_results_without_rescoring(records):
    db, owner, _, posting, _, _, _ = records
    service = ScoringService()
    configuration = service.approve(db, user_id=owner.id, job_id=posting.id, data=approval(db, owner, posting))
    first = service.run(db, user_id=owner.id, job_id=posting.id, data=ScoreRunRequest(configuration_id=configuration["id"]))
    stored = db.scalar(select(CandidateScore).where(CandidateScore.scoring_run_id == first["id"]))
    original_breakdown = deepcopy(stored.breakdown)
    original_snapshot = deepcopy(db.get(ScoringRun, first["id"]).snapshot)
    count = db.scalar(select(func.count(ScoringRun.id)))
    detail = service.detail(db, user_id=owner.id, run_id=first["id"])
    assert detail["results"][0]["final_score"] == first["results"][0]["final_score"]
    for item in detail["results"][0]["breakdown"]["requirements"]:
        assert item["reason"] and len(item["evidence_preview"]) <= 4
        for preview in item["evidence_preview"]:
            assert preview["quote"] in item["evidence"][preview["source_index"]]["quote"]
    db.expire_all()
    assert db.get(CandidateScore, stored.id).breakdown == original_breakdown
    assert db.get(ScoringRun, first["id"]).snapshot == original_snapshot
    assert db.scalar(select(func.count(ScoringRun.id))) == count


def test_contacts_are_only_added_for_explicit_interviewer_presentation(records):
    db, owner, other, posting, application, _, _ = records
    from app.models.candidate import Candidate
    candidate = db.get(Candidate, application.candidate_id)
    candidate.email = "candidate@example.com"
    db.commit()
    service = ScoringService()
    configuration = service.approve(db, user_id=owner.id, job_id=posting.id, data=approval(db, owner, posting))
    saved = service.run(db, user_id=owner.id, job_id=posting.id, data=ScoreRunRequest(configuration_id=configuration["id"]))
    assert "candidate_email" not in saved["results"][0]
    shown = service.detail(db, user_id=owner.id, run_id=saved["id"], include_contacts=True)
    assert shown["results"][0]["candidate_email"] == "candidate@example.com"
    with pytest.raises(LookupError):
        service.detail(db, user_id=other.id, run_id=saved["id"], include_contacts=True)


def test_ocr_origin_is_exposed_from_saved_screening_trace_without_rescoring(records):
    db, owner, _, posting, _, _, _ = records
    service = ScoringService()
    configuration = service.approve(db, user_id=owner.id, job_id=posting.id, data=approval(db, owner, posting))
    saved = service.run(db, user_id=owner.id, job_id=posting.id, data=ScoreRunRequest(configuration_id=configuration["id"]))
    screening = db.get(ScreeningRun, saved["results"][0]["screening_run_id"])
    screening.processing_metadata = {**screening.processing_metadata, "evidence": {"ocr": {"pages": [{"page": 1}, {"page": 2, "blank": True}]}}}
    db.commit()
    shown = service.detail(db, user_id=owner.id, run_id=saved["id"])
    assert shown["results"][0]["source_extraction"] == {"method": "ocr", "pages": [1]}
    assert shown["results"][0]["final_score"] == saved["results"][0]["final_score"]


def test_legacy_ambiguous_match_is_persisted_as_unmet_without_changing_history(records):
    db, owner, _, posting, _, _, _ = records
    service = ScoringService()
    configuration = service.approve(db, user_id=owner.id, job_id=posting.id, data=approval(db, owner, posting))
    request = ScoreRunRequest(configuration_id=configuration["id"])
    previous = service.run(db, user_id=owner.id, job_id=posting.id, data=request)
    match = db.scalar(select(RequirementMatch).where(RequirementMatch.name == "Python"))
    match.status = RequirementMatchStatus.UNABLE_TO_DETERMINE
    match.evidence = []
    db.commit()
    current = service.run(db, user_id=owner.id, job_id=posting.id, data=request)
    result = current["results"][0]
    outcome = next(item for item in result["breakdown"]["requirements"] if item["name"] == "Python")
    assert outcome["status"] == "unmet"
    assert outcome["match_value"] == "0"
    assert result["rank"] == 1
    assert current["formula_version"] == "category-weighted-coverage-v5"
    assert current["id"] != previous["id"]
    db.expire_all()
    assert service.detail(db, user_id=owner.id, run_id=current["id"]) == current
    assert service.detail(db, user_id=owner.id, run_id=previous["id"]) == previous


def test_configuration_validation_and_new_versions(records):
    db, owner, _, posting, _, _, _ = records
    service = ScoringService()
    with pytest.raises(ValueError, match="total exactly 100"):
        service.approve(db, user_id=owner.id, job_id=posting.id, data=approval(db, owner, posting, category_weights={"technical": 90, "experience": 0, "qualification": 0}))
    with pytest.raises(ValueError, match="no positive requirement"):
        service.approve(db, user_id=owner.id, job_id=posting.id, data=approval(db, owner, posting, category_weights={"technical": 50, "experience": 30, "qualification": 20}))
    initial = approval(db, owner, posting)
    first = service.approve(db, user_id=owner.id, job_id=posting.id, data=initial)
    run = service.run(db, user_id=owner.id, job_id=posting.id, data=ScoreRunRequest(configuration_id=first["id"]))
    updated = initial.model_copy(deep=True)
    updated.requirements[0].weight = Decimal(1)
    second = service.approve(db, user_id=owner.id, job_id=posting.id, data=updated)
    assert second["id"] != first["id"]
    assert service.run(db, user_id=owner.id, job_id=posting.id, data=ScoreRunRequest(configuration_id=second["id"]))["id"] != run["id"]
    from app.models.job import RequirementProfile
    profile = db.get(RequirementProfile, run["configuration"]["requirement_profile_id"])
    profile.required_skills = [{"name": "Python", "weight": 4}]
    db.commit()
    with pytest.raises(ScoringConflict):
        service.run(db, user_id=owner.id, job_id=posting.id, data=ScoreRunRequest(configuration_id=first["id"]))
    assert service.detail(db, user_id=owner.id, run_id=run["id"]) == run


def test_simple_category_approval_keeps_unmapped_criteria_outside_percentage(records):
    from app.models.job import RequirementProfile
    db, owner, _, posting, _, _, _ = records
    service = ScoringService()
    old_configuration = service.approve(db, user_id=owner.id, job_id=posting.id, data=approval(db, owner, posting))
    historical = service.run(db, user_id=owner.id, job_id=posting.id, data=ScoreRunRequest(configuration_id=old_configuration["id"]))
    profile = db.get(RequirementProfile, historical["configuration"]["requirement_profile_id"])
    profile.selection_criteria = [{"name": "Delivery evidence", "weight": 1000}]
    db.flush()
    snapshot, version = ScreeningService._requirement_snapshot(profile)
    screened = db.scalar(select(ScreeningRun))
    screened.requirement_snapshot = snapshot
    screened.requirement_snapshot_hash = version
    db.add(RequirementMatch(screening_run_id=screened.id, requirement_key="selection_criterion:0", category="selection_criterion",
        name="Delivery evidence", weight=1000, status=RequirementMatchStatus.UNMET, explanation="Not evidenced", evidence=[], evidence_gaps=[], review_flags=[]))
    db.commit()
    configuration = service.approve(db, user_id=owner.id, job_id=posting.id, data=approval(db, owner, posting))
    criteria = next(item for item in configuration["snapshot"]["requirements"] if item["requirement_id"] == "selection_criterion:0")
    assert criteria["category"] is None and criteria["score_included"] is False
    current = service.run(db, user_id=owner.id, job_id=posting.id, data=ScoreRunRequest(configuration_id=configuration["id"]))
    assert current["results"][0]["display_score"] == historical["results"][0]["display_score"] == "66.67"
    assert service.detail(db, user_id=owner.id, run_id=historical["id"]) == historical


def test_approved_scoring_runs_after_screening_and_review_isolation(records):
    db, owner, _, posting, app, document, storage = records
    service = ScoringService()
    configuration = service.approve(db, user_id=owner.id, job_id=posting.id, data=approval(db, owner, posting))
    screening = ScreeningService(_settings(storage), ai=FakeScreeningAI())
    batch = screening.create_batch(db, interviewer_user_id=owner.id, job_posting_id=posting.id, application_ids=[app.id])
    screening.process_batch(db, batch_id=batch.id)
    assert db.scalar(select(func.count(ScoringRun.id))) == 1
    assert db.scalar(select(ScoringRun)).configuration_id == configuration["id"]
    document.extraction_warnings = ["No text extracted from PDF page 2"]
    db.commit()
    result = service.run(db, user_id=owner.id, job_id=posting.id, data=ScoreRunRequest(configuration_id=configuration["id"]))
    assert result["results"][0]["rank"] == 1
    assert result["status"] == "completed"
    assert result["results"][0]["breakdown"]["review_flags"]
    assert "excluded from" not in result["results"][0]["written_justification"].lower()


def test_failed_cv_processing_is_not_ranked_as_zero(records):
    db, owner, _, posting, app, document, _ = records
    screening = db.scalar(select(ScreeningRun).where(ScreeningRun.application_id == app.id))
    screening.status = ScreeningRunStatus.FAILED
    screening.error_message = "The CV could not be parsed."
    db.commit()
    service = ScoringService()
    configuration = service.approve(db, user_id=owner.id, job_id=posting.id, data=approval(db, owner, posting))
    with pytest.raises(ValueError, match="No completed CV screenings"):
        service.run(db, user_id=owner.id, job_id=posting.id, data=ScoreRunRequest(configuration_id=configuration["id"]))
    with pytest.raises(ScoringConflict, match="not finished screening"):
        service.run(db, user_id=owner.id, job_id=posting.id, data=ScoreRunRequest(configuration_id=configuration["id"], application_ids=[app.id]))


def test_stale_idempotency_request_and_equivalent_numeric_weights(records):
    db, owner, _, posting, _, _, _ = records
    service = ScoringService()
    initial = approval(db, owner, posting)
    first = service.approve(db, user_id=owner.id, job_id=posting.id, data=initial)
    initial.category_weights["technical"] = Decimal("100.000")
    initial.requirements[0].weight = Decimal("2.000")
    assert service.approve(db, user_id=owner.id, job_id=posting.id, data=initial)["id"] == first["id"]
    service.run(db, user_id=owner.id, job_id=posting.id, data=ScoreRunRequest(configuration_id=first["id"], idempotency_key="fixed"))
    with pytest.raises(ScoringConflict, match="different scoring request"):
        service.run(db, user_id=owner.id, job_id=posting.id, data=ScoreRunRequest(configuration_id=first["id"], application_ids=[999], idempotency_key="fixed"))


def test_postgresql_scoring_precision_and_restart_persistence(pg_database, tmp_path):
    from alembic import command
    from sqlalchemy import inspect, text
    engine, config = create_engine(pg_database), _config(pg_database)
    command.upgrade(config, "head")
    assert {"scoring_runs", "candidate_scores"}.issubset(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT format_type(atttypid, atttypmod) FROM pg_attribute WHERE attrelid='candidate_scores'::regclass AND attname='final_score'")) == "numeric(80,60)"
        assert connection.scalar(text("SELECT format_type(atttypid, atttypmod) FROM pg_attribute WHERE attrelid='scoring_runs'::regclass AND attname='snapshot'")) == "jsonb"
    with Session(engine, expire_on_commit=False) as db:
        owner, _, posting = _records(db)
        app, _ = _application_with_docx(db, tmp_path, posting, 1)
        db.commit()
        screening = ScreeningService(_settings(tmp_path), ai=FakeScreeningAI())
        batch = screening.create_batch(db, interviewer_user_id=owner.id, job_posting_id=posting.id, application_ids=None)
        screening.process_batch(db, batch_id=batch.id)
        configuration = ScoringService().approve(db, user_id=owner.id, job_id=posting.id, data=approval(db, owner, posting))
        first = ScoringService().run(db, user_id=owner.id, job_id=posting.id, data=ScoreRunRequest(configuration_id=configuration["id"]))
        owner_id = owner.id
    with Session(engine) as db:
        stored = db.scalar(select(CandidateScore))
        assert stored.final_score == Decimal(first["results"][0]["final_score"])
        assert ScoringService().detail(db, user_id=owner_id, run_id=first["id"]) == first
        data = approval(db, db.get(type(owner), owner_id), posting)
        data.requirements[0].weight = Decimal("0.000001")
        data.requirements[1].weight = Decimal("10000")
        configuration = ScoringService().approve(db, user_id=owner_id, job_id=posting.id, data=data)
        small = ScoringService().run(db, user_id=owner_id, job_id=posting.id, data=ScoreRunRequest(configuration_id=configuration["id"]))
        stored = db.scalar(select(CandidateScore).where(CandidateScore.scoring_run_id == small["id"]))
        assert stored.final_score == Decimal(small["results"][0]["final_score"])
        assert "E" not in small["results"][0]["final_score"]
        assert small["results"][0]["display_score"] == "0.00"
    engine.dispose()


def test_api_authorization_and_deletion(records):
    db, owner, other, posting, app, _, storage = records
    api = FastAPI()
    api.include_router(router)
    api.dependency_overrides[get_db] = lambda: db
    service = ScoringService()
    configuration = service.approve(db, user_id=owner.id, job_id=posting.id, data=approval(db, owner, posting))
    body = {"configuration_id": configuration["id"], "idempotency_key": "api"}
    with TestClient(api) as client:
        assert client.get(f"/api/scoring/jobs/{posting.id}/configuration").status_code == 401
        candidate_headers = {"Authorization": f"Bearer {create_access_token(other.id)}"}
        assert client.get(f"/api/scoring/jobs/{posting.id}/configuration", headers=candidate_headers).status_code == 403
        assert client.post(f"/api/scoring/jobs/{posting.id}/runs", headers=candidate_headers, json=body).status_code == 403
        owner_headers = {"Authorization": f"Bearer {create_access_token(owner.id)}"}
        response = client.post(f"/api/scoring/jobs/{posting.id}/runs", headers=owner_headers, json=body)
        assert response.status_code == 200, response.text
        run_id = response.json()["id"]
        assert client.get(f"/api/scoring/runs/{run_id}", headers=candidate_headers).status_code == 403
        assert client.get(f"/api/scoring/runs/{run_id}", headers=owner_headers).json()["results"] == response.json()["results"]
    CandidateApplicationService(_settings(storage)).delete(db, application_id=app.id, interviewer_user_id=owner.id)
    assert db.scalar(select(func.count(ScoringRun.id))) == 0
    assert db.scalar(select(func.count(CandidateScore.id))) == 0
    assert db.scalar(select(func.count(ScoringConfiguration.id))) == 1
