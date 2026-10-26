from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from copy import deepcopy
from types import SimpleNamespace
import asyncio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from icalendar import Calendar
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Candidate, CandidateApplication, CandidateScore, ScoringRun, ScreeningRun, UserRole
from app.models.candidate import ApplicationStatus
from app.models.interview import InterviewBatch, InterviewSchedule, InterviewDelivery
from app.models.job import JobPosting
from app.schemas.interview import SelectionRequest, PrepareInvites, ConfirmInvites, RescheduleRequest
from app.services.interview_service import InterviewService, InterviewConflict
from app.services.interview_content import allocate_slots, SMTPInvitationSender
from app.services.scoring_service import ScoringService
from app.schemas.scoring import ScoreRunRequest
from app.services.screening_service import ScreeningService
from app.security import create_access_token
from app.routes import interviews as api_routes
from test_scoring import records, approval
from test_screening import _settings, _application_with_docx, FakeScreeningAI


class FakeSender:
    def __init__(self, statuses=None):
        self.statuses = list(statuses or [])
        self.calls = []
    def send(self, delivery):
        self.calls.append((delivery.id, delivery.recipient_email, delivery.body, delivery.calendar_text))
        status = self.statuses.pop(0) if self.statuses else "sent"
        return {"status": status, "provider_message_id": "fake-message" if status == "sent" else None,
            "error_category": None if status == "sent" else "mock_" + status}


@pytest.fixture
def setup(records):
    db, owner, other, posting, app, doc, root = records
    apps = [app]
    for index in range(2, 5):
        item, _ = _application_with_docx(db, root, posting, index)
        apps.append(item)
    db.commit()
    screening = ScreeningService(_settings(root), ai=FakeScreeningAI())
    batch = screening.create_batch(db, interviewer_user_id=owner.id, job_posting_id=posting.id, application_ids=None)
    screening.process_batch(db, batch_id=batch.id)
    scoring = ScoringService()
    config = scoring.approve(db, user_id=owner.id, job_id=posting.id, data=approval(db, owner, posting))
    run = scoring.run(db, user_id=owner.id, job_id=posting.id, data=ScoreRunRequest(configuration_id=config["id"]))
    sender = FakeSender()
    service = InterviewService(_settings(root), sender=sender, session_factory=lambda: Session(db.get_bind(), expire_on_commit=False))
    return db, owner, other, posting, apps, run, service, sender


def select_preview(setup, **values):
    db, owner, _, posting, _, run, service, _ = setup
    return service.preview_selection(db, owner.id, SelectionRequest(job_posting_id=posting.id, ranking_run_id=run["id"], **values))


def schedule_data(token, **values):
    return PrepareInvites.model_validate({"selection_token": token, "date": (date.today() + timedelta(days=20)).isoformat(),
        "start_time": "10:00", "timezone": "Asia/Dhaka", "duration_minutes": 30, "buffer_minutes": 10, "mode": "sequential", **values})


def prepared(setup, count=2):
    db, owner, _, _, _, _, service, _ = setup
    selection = select_preview(setup, mode="top_n", top_n=count)
    return service.prepare(db, owner.id, schedule_data(selection["selection_token"]))


def confirm_data(preview, key="test-request"):
    return ConfirmInvites(confirmed=True, confirmation_token=preview["confirmation_token"], idempotency_key=key)


def test_top_n_ties_and_manual_order(setup):
    db, owner, _, _, apps, _, service, sender = setup
    preview = select_preview(setup, mode="top_n", top_n=2)
    assert [item["application_id"] for item in preview["selected"]] == [apps[0].id, apps[1].id]
    assert preview["tie_at_boundary"] is True
    assert preview["recipient_count"] == 2
    assert all("***@" in item["masked_email"] for item in preview["selected"])
    assert [item["email"] for item in preview["selected"]] == [db.get(Candidate, app.candidate_id).email for app in apps[:2]]
    manual = select_preview(setup, mode="manual", application_ids=[apps[2].id, apps[0].id])
    assert [item["application_id"] for item in manual["selected"]] == [apps[0].id, apps[2].id]
    assert sender.calls == []
    assert db.scalar(select(func.count(InterviewBatch.id))) == 0
    with pytest.raises(LookupError):
        select_preview(setup, mode="manual", application_ids=[99999])


def test_threshold_operator_uses_unrounded_persisted_score(setup):
    db, _, _, _, apps, run, _, _ = setup
    scores = list(db.scalars(select(CandidateScore).where(CandidateScore.scoring_run_id == run["id"]).order_by(CandidateScore.application_id)))
    for score, value in zip(scores, ["70", "70.000001", "69.999999", "80"]):
        score.final_score = Decimal(value)
    db.commit()
    gt = select_preview(setup, mode="threshold", threshold="70", operator="gt")
    gte = select_preview(setup, mode="threshold", threshold="70", operator="gte")
    assert [item["application_id"] for item in gt["selected"]] == [apps[1].id, apps[3].id]
    assert [item["application_id"] for item in gte["selected"]] == [apps[0].id, apps[1].id, apps[3].id]


def test_invalid_email_withdrawal_and_existing_interview_are_visible(setup):
    db, owner, _, _, apps, _, service, _ = setup
    db.get(Candidate, apps[0].candidate_id).email = "invalid"
    apps[1].status = ApplicationStatus.WITHDRAWN
    db.commit()
    selection = select_preview(setup, mode="top_n", top_n=2)
    assert len(selection["excluded"]) == 2
    assert selection["selected"] == []
    assert any("not replaced" in warning for warning in selection["warnings"])
    selection = select_preview(setup, mode="manual", application_ids=[apps[2].id, apps[3].id])
    preview = service.prepare(db, owner.id, schedule_data(selection["selection_token"]))
    service.confirm(db, owner.id, preview["id"], confirm_data(preview))
    later = select_preview(setup, mode="manual", application_ids=[apps[2].id, apps[3].id])
    assert later["recipient_count"] == 0
    assert any("active interview" in reason for item in later["excluded"] for reason in item["reasons"])


def test_top_three_does_not_backfill_rank_six_when_higher_candidates_have_interviews(setup):
    db, owner, _, _, apps, run, service, sender = setup
    scores = list(db.scalars(select(CandidateScore).where(CandidateScore.scoring_run_id == run["id"]).order_by(CandidateScore.application_id)))
    for score, rank in zip(scores, [1, 2, 3, 6]):
        score.rank = rank
    db.commit()
    # Candidates in the original first and third places already have interviews.
    selection = select_preview(setup, mode="manual", application_ids=[apps[0].id, apps[2].id])
    preview = service.prepare(db, owner.id, schedule_data(selection["selection_token"]))
    service.confirm(db, owner.id, preview["id"], confirm_data(preview))
    top_three = select_preview(setup, mode="top_n", top_n=3)
    assert [(item["application_id"], item["rank"]) for item in top_three["selected"]] == [(apps[1].id, 2)]
    assert {item["application_id"] for item in top_three["excluded"]} == {apps[0].id, apps[2].id}
    assert apps[3].id not in {item["application_id"] for item in top_three["selected"]}
    assert top_three["recipient_count"] == 1 and any("not replaced" in warning for warning in top_three["warnings"])
    assert not sender.calls


def test_preview_then_confirm_is_atomic_and_idempotent(setup):
    db, owner, _, _, _, _, service, sender = setup
    preview = prepared(setup)
    assert not sender.calls
    assert db.scalar(select(func.count(InterviewSchedule.id))) == 0
    data = confirm_data(preview)
    result = service.confirm(db, owner.id, preview["id"], data)
    assert result["pending"] == 2
    assert not sender.calls
    service.confirm(db, owner.id, preview["id"], data)
    assert db.scalar(select(func.count(InterviewSchedule.id))) == 2
    service.deliver_pending(db, result["id"])
    service.deliver_pending(db, result["id"])
    assert len(sender.calls) == 2
    assert service.batch(db, owner.id, result["id"])["sent"] == 2
    db.expire_all()
    assert service.schedules(db, owner.id)[0]["status"] == "scheduled"
    assert all(item.meeting_url is None for item in db.scalars(select(InterviewSchedule)))
    assert all("meeting link" not in call[2] for call in sender.calls)


def test_legacy_previews_show_email_without_rewriting_signed_snapshots(setup):
    db, owner, _, _, apps, _, service, _ = setup
    preview = prepared(setup, count=1)
    batch = db.get(InterviewBatch, preview["id"])
    legacy = deepcopy(batch.snapshot)
    for item in legacy["recipients"]:
        item.pop("email", None)
    batch.snapshot = legacy
    db.commit()
    snapshot, seal = deepcopy(batch.snapshot), batch.confirmation_hash
    result = service.batch(db, owner.id, batch.id)
    assert result["recipients"][0]["email"] == db.get(Candidate, apps[0].candidate_id).email
    assert batch.snapshot == snapshot and batch.confirmation_hash == seal


def test_confirmed_preview_uses_actual_delivery_email_after_profile_changes(setup):
    db, owner, _, _, apps, _, service, _ = setup
    preview = prepared(setup, count=1)
    original = db.get(Candidate, apps[0].candidate_id).email
    assert preview["recipients"][0]["email"] == original
    service.confirm(db, owner.id, preview["id"], confirm_data(preview))
    db.get(Candidate, apps[0].candidate_id).email = "changed@example.com"
    db.commit()
    result = service.batch(db, owner.id, preview["id"])
    assert result["recipients"][0]["email"] == original
    assert result["deliveries"][0]["email"] == original


def test_stale_ranking_recipient_and_draft_are_rejected(setup):
    db, owner, _, _, apps, _, service, _ = setup
    preview = prepared(setup)
    db.get(Candidate, apps[0].candidate_id).email = "changed@example.com"
    db.commit()
    with pytest.raises(InterviewConflict, match="Recipients"):
        service.confirm(db, owner.id, preview["id"], confirm_data(preview))
    db.rollback()
    preview = prepared(setup)
    saved = db.get(InterviewBatch, preview["id"])
    saved.snapshot = {**saved.snapshot, "sender": {"from_email": "changed@example.com"}}
    db.commit()
    with pytest.raises(InterviewConflict, match="Draft changed"):
        service.confirm(db, owner.id, preview["id"], confirm_data(preview))


def test_partial_failure_uncertain_and_safe_retry(setup):
    db, owner, _, _, _, _, service, sender = setup
    sender.statuses = ["sent", "failed", "uncertain"]
    preview = prepared(setup, count=3)
    result = service.confirm(db, owner.id, preview["id"], confirm_data(preview))
    service.deliver_pending(db, result["id"])
    result = service.batch(db, owner.id, result["id"])
    assert (result["sent"], result["failed"], result["uncertain"]) == (1, 1, 1)
    for item in result["deliveries"]:
        if item["status"] != "failed":
            with pytest.raises(InterviewConflict):
                service.retry(db, owner.id, item["id"], item["attempts"])
            db.rollback()
    failed = next(item for item in result["deliveries"] if item["status"] == "failed")
    service.retry(db, owner.id, failed["id"], failed["attempts"])
    service.deliver_pending(db, result["id"])
    assert len(sender.calls) == 4
    assert service.batch(db, owner.id, result["id"])["uncertain"] == 1


def test_reschedule_keeps_uid_increases_sequence_preserves_history_and_failed_notification(setup):
    db, owner, _, _, _, _, service, sender = setup
    preview = prepared(setup, count=1)
    result = service.confirm(db, owner.id, preview["id"], confirm_data(preview))
    service.deliver_pending(db, result["id"])
    schedule = db.scalar(select(InterviewSchedule))
    uid, old_local = schedule.calendar_uid, schedule.local_start
    request = RescheduleRequest.model_validate({**schedule_data("placeholder-token").model_dump(exclude={"selection_token"}),
        "schedule_ids": [schedule.id], "date": date.today() + timedelta(days=21), "reason": "Availability changed"})
    preview = service.preview_reschedule(db, owner.id, request)
    assert preview["recipients"][0]["email"] == db.get(Candidate, db.get(CandidateApplication, schedule.application_id).candidate_id).email
    assert schedule.local_start == old_local
    sender.statuses = ["failed"]
    updated = service.confirm_reschedule(db, owner.id, confirm_data(preview, "reschedule"))
    service.confirm_reschedule(db, owner.id, confirm_data(preview, "reschedule"))
    service.deliver_pending(db, updated["id"])
    db.refresh(schedule)
    assert schedule.calendar_uid == uid and schedule.sequence == 1 and schedule.version == 2
    assert schedule.status == "rescheduled" and schedule.history[0]["local_start"] == old_local
    assert service.batch(db, owner.id, updated["id"])["failed"] == 1
    delivery = db.scalar(select(InterviewDelivery).where(InterviewDelivery.sequence == 1))
    calendar = Calendar.from_ical(delivery.calendar_text)
    event = calendar.walk("VEVENT")[0]
    assert str(event["uid"]) == uid and int(event["sequence"]) == 1
    assert str(calendar["method"]) == "REQUEST"
    assert event["dtend"].dt > event["dtstart"].dt
    assert "Previous schedule" in delivery.body and "New schedule" in delivery.body
    with pytest.raises(ValueError, match="future"):
        service.preview_reschedule(db, owner.id, request.model_copy(update={"date": date.today() - timedelta(days=1)}))


def test_sequential_time_conversion_and_invalid_times():
    data = schedule_data("placeholder-token")
    slots = allocate_slots(data, 3)
    assert [item["local_start"][11:16] for item in slots] == ["10:00", "10:40", "11:20"]
    assert slots[0]["start_utc"][11:16] == "04:00"
    with pytest.raises(ValueError, match="sequential individual"):
        allocate_slots(data.model_copy(update={"mode": "shared"}), 3)
    with pytest.raises(ValueError, match="future"):
        allocate_slots(data.model_copy(update={"date": date.today() - timedelta(days=1)}), 1)
    with pytest.raises(ValueError, match="IANA"):
        allocate_slots(data.model_copy(update={"timezone": "Not/AZone"}), 1)
    for day, local in [(date(2030, 3, 10), "02:30"), (date(2030, 11, 3), "01:30")]:
        from datetime import time
        with pytest.raises(ValueError):
            allocate_slots(data.model_copy(update={"date": day, "start_time": time.fromisoformat(local), "timezone": "America/New_York"}), 1)


def test_hidden_schedule_defaults_and_rejection_of_group_requests():
    from app.schemas.interview import ScheduleRequest
    defaults = {"date": (date.today() + timedelta(days=20)).isoformat(), "start_time": "10:00", "duration_minutes": 30}
    data = ScheduleRequest.model_validate(defaults)
    assert data.timezone == "Asia/Dhaka" and data.mode == "sequential"
    with pytest.raises(ValueError):
        ScheduleRequest.model_validate({**defaults, "mode": "shared"})


def test_conflicts_and_stale_schedule_version(setup):
    db, owner, _, _, _, _, service, _ = setup
    first, second = prepared(setup, 1), prepared(setup, 2)
    service.confirm(db, owner.id, first["id"], confirm_data(first))
    with pytest.raises(InterviewConflict):
        service.confirm(db, owner.id, second["id"], confirm_data(second, "second"))
    db.rollback()
    schedule = db.scalar(select(InterviewSchedule))
    data = RescheduleRequest.model_validate({**schedule_data("placeholder-token", date=date.today() + timedelta(days=21)).model_dump(exclude={"selection_token"}), "schedule_ids": [schedule.id]})
    preview = service.preview_reschedule(db, owner.id, data)
    schedule.version += 1
    db.commit()
    with pytest.raises(InterviewConflict, match="changed"):
        service.confirm_reschedule(db, owner.id, confirm_data(preview, "stale"))


def test_api_authorization_confirmation_and_mocked_background_delivery(setup, monkeypatch):
    db, owner, other, posting, _, _, service, sender = setup
    api = FastAPI()
    api.include_router(api_routes.router)
    api.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(api_routes, "InterviewService", lambda: service)
    with TestClient(api) as client:
        assert client.get("/api/interviews/schedules").status_code == 401
        denied = {"Authorization": "Bearer " + create_access_token(other.id)}
        assert client.get("/api/interviews/schedules", headers=denied).status_code == 403
        assert client.post("/api/interviews/selection/preview", headers=denied, json={"job_posting_id": posting.id, "mode": "top_n", "top_n": 1}).status_code == 403
        headers = {"Authorization": "Bearer " + create_access_token(owner.id)}
        selection = client.post("/api/interviews/selection/preview", headers=headers, json={"job_posting_id": posting.id, "mode": "top_n", "top_n": 1}).json()
        assert selection["selected"][0]["email"] and "***" not in selection["selected"][0]["email"]
        data = schedule_data(selection["selection_token"])
        rejected = client.post("/api/interviews/invitations/prepare", headers=headers, json={**data.model_dump(mode="json"), "mode": "shared"})
        assert rejected.status_code == 422 and not sender.calls
        preview = client.post("/api/interviews/invitations/prepare", headers=headers, json=data.model_dump(mode="json")).json()
        assert preview["recipients"][0]["email"] == selection["selected"][0]["email"]
        assert client.get(f"/api/interviews/batches/{preview['id']}", headers=denied).status_code == 403
        assert sender.calls == []
        response = client.post(f"/api/interviews/batches/{preview['id']}/confirm", headers=headers, json={"confirmed": False, "confirmation_token": preview["confirmation_token"], "idempotency_key": "api"})
        assert response.status_code == 422
        response = client.post(f"/api/interviews/batches/{preview['id']}/confirm", headers=headers, json=confirm_data(preview, "api").model_dump(mode="json"))
        assert response.status_code == 200, response.text
        assert len(sender.calls) == 1
        assert client.get(f"/api/interviews/batches/{preview['id']}", headers=headers).json()["sent"] == 1


def test_schedule_status_query_filters_by_owned_job_without_mutating_records(setup, monkeypatch):
    db, owner, other, posting, _, _, service, sender = setup
    preview = prepared(setup, count=1)
    service.confirm(db, owner.id, preview["id"], confirm_data(preview))
    empty_posting = JobPosting(job_description_id=posting.job_description_id, platform="manual")
    db.add(empty_posting)
    db.commit()
    api = FastAPI()
    api.include_router(api_routes.router)
    api.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(api_routes, "InterviewService", lambda: service)
    with TestClient(api) as client:
        headers = {"Authorization": "Bearer " + create_access_token(owner.id)}
        result = client.get(f"/api/interviews/schedules?job_posting_id={posting.id}", headers=headers)
        assert result.status_code == 200
        assert len(result.json()) == 1 and result.json()[0]["status"] == "scheduled"
        assert result.json()[0]["application_id"] == preview["recipients"][0]["application_id"]
        assert client.get(f"/api/interviews/schedules?job_posting_id={empty_posting.id}", headers=headers).json() == []
        assert len(client.get("/api/interviews/schedules", headers=headers).json()) == 1
        assert client.get("/api/interviews/schedules?job_posting_id=0", headers=headers).status_code == 422
        assert client.get("/api/interviews/schedules?job_posting_id=999999", headers=headers).status_code == 404
        denied = {"Authorization": "Bearer " + create_access_token(other.id)}
        assert client.get(f"/api/interviews/schedules?job_posting_id={posting.id}", headers=denied).status_code == 403
    assert sender.calls == []
    assert db.scalar(select(func.count(InterviewSchedule.id))) == 1


def test_job_ownership_document_failure_and_ranking_freshness(setup):
    db, owner, other, posting, apps, _, service, _ = setup
    from app.models import CVDocument, JobDescription
    document = db.scalar(select(CVDocument).where(CVDocument.application_id == apps[0].id))
    document.extraction_warnings = ["An image-only page was not read"]
    db.commit()
    # Evidence changed, so a saved preview cannot silently absorb a different document state.
    with pytest.raises(InterviewConflict, match="evidence changed"):
        select_preview(setup, mode="top_n", top_n=1)
    db.rollback()
    document.extraction_warnings = []
    db.commit()
    job = db.get(JobDescription, posting.job_description_id)
    job.created_by_user_id = other.id
    db.commit()
    with pytest.raises(LookupError):
        select_preview(setup, mode="top_n", top_n=1)


def successful_ocr_document(db, app):
    from app.models.candidate import CVDocument
    from app.screening.ocr import ocr_page_notice
    document = db.scalar(select(CVDocument).where(CVDocument.application_id == app.id))
    data = deepcopy(document.extraction_data)
    data["parser"] = {**data["parser"], "parser": "pypdf+tesseract", "ocr": {"pages": [{"page": 1,
        "mean_confidence": 94, "uncertain_character_ratio": 0.02, "word_count": 50,
        "identity": {"policy": {"min_confidence": 80, "max_uncertain_ratio": 0.15, "min_words": 5}}}]}}
    document.extraction_data = data
    document.extraction_warnings = [ocr_page_notice(1)]
    return document


def test_successful_ocr_candidate_can_be_selected_and_invitation_prepared(setup):
    db, owner, _, posting, apps, run, service, sender = setup
    document = successful_ocr_document(db, apps[0]); db.commit()
    # Recalculate against this new evidence state; scheduling still validates
    # the exact saved ranking and does not bypass evidence freshness.
    ScoringService().run(db, user_id=owner.id, job_id=posting.id, data=ScoreRunRequest(configuration_id=run["configuration_id"]))
    selection = service.preview_selection(db, owner.id, SelectionRequest(job_posting_id=posting.id, mode="manual", application_ids=[apps[0].id]))
    assert selection["recipient_count"] == 1 and selection["excluded"] == []
    invitation = service.prepare(db, owner.id, schedule_data(selection["selection_token"]))
    assert invitation["recipient_count"] == 1
    assert document.extraction_warnings  # Keep the OCR provenance visible.
    assert sender.calls == [] and db.scalar(select(func.count(InterviewSchedule.id))) == 0


@pytest.mark.parametrize("problem", ["unknown_warning", "missing_trace", "low_confidence", "failed_status", "active_error", "unverified_page"])
def test_ocr_notice_does_not_bypass_real_cv_problems(setup, problem):
    db, _, _, _, apps, _, service, sender = setup
    document = successful_ocr_document(db, apps[0])
    if problem == "unknown_warning": document.extraction_warnings += ["An image-only page was not read"]
    elif problem == "missing_trace": document.extraction_data = {"parser": {}}
    elif problem == "low_confidence":
        data = deepcopy(document.extraction_data)
        data["parser"]["ocr"]["pages"][0]["mean_confidence"] = 30
        document.extraction_data = data
    elif problem == "failed_status": document.status = "failed"
    elif problem == "active_error": document.error_message = "CV OCR could not finish"
    elif problem == "unverified_page":
        from app.screening.ocr import ocr_page_notice
        document.extraction_warnings = [ocr_page_notice(2)]
    db.commit()
    _, reasons = service.eligibility(db, apps[0], "technical")
    assert any("CV processing" in reason for reason in reasons) and sender.calls == []


def test_expired_preview_is_rejected_before_schedules_exist(setup):
    db, owner, _, _, _, _, service, _ = setup
    preview = prepared(setup, count=1)
    import jwt
    payload = jwt.decode(preview["confirmation_token"], service.settings.jwt_secret_key.get_secret_value(), algorithms=["HS256"], audience="invitation")
    payload["exp"] = int((datetime.now(timezone.utc) - timedelta(minutes=1)).timestamp())
    expired = jwt.encode(payload, service.settings.jwt_secret_key.get_secret_value(), algorithm="HS256")
    with pytest.raises(InterviewConflict, match="expired"):
        service.confirm(db, owner.id, preview["id"], confirm_data({"confirmation_token": expired}))
    assert db.scalar(select(func.count(InterviewSchedule.id))) == 0


def test_application_deletion_removes_schedules_deliveries_and_redacts_batch_snapshots(setup):
    db, owner, _, _, apps, _, service, _ = setup
    preview = prepared(setup, count=2)
    service.confirm(db, owner.id, preview["id"], confirm_data(preview))
    from app.services.candidate_application_service import CandidateApplicationService
    CandidateApplicationService(service.settings).delete(db, application_id=apps[0].id, interviewer_user_id=owner.id)
    assert db.scalar(select(func.count(InterviewSchedule.id))) == 1
    assert db.scalar(select(func.count(InterviewDelivery.id))) == 1
    batch = db.get(InterviewBatch, preview["id"])
    assert all(item["application_id"] != apps[0].id for item in batch.snapshot["recipients"])
    assert all(item["application_id"] != apps[0].id for item in batch.snapshot["selection"]["selected"])
