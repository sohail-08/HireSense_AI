"""No external Google, model, mail or biometric calls."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models.candidate import Candidate, CandidateApplication, CVDocument, ApplicationSource
from app.models.interview import InterviewBatch, InterviewSchedule
from app.services.application_identity import bind_profile, submitted_profile, canonical_applications
from app.services.google_forms_intake_service import GoogleFormsIntakeService
from app.services.scoring_service import ScoringService
from app.services.screening_service import ScreeningService
from scripts.repair_application_profiles import repair
from test_google_forms_intake import FakeGoogleReader, _settings
from test_screening import _records, FakeScreeningAI
from test_pgvector import pg_database, _config


@pytest.fixture
def identities(tmp_path):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        owner, other, posting = _records(db)
        db.commit()
        yield db, owner, other, posting, _settings(tmp_path)
    engine.dispose()


def application(db, posting, *, name="Ada Candidate", email="same@example.com", cv="a", candidate=None, row=2):
    candidate = candidate or Candidate(name=name, email=email)
    db.add(candidate); db.flush()
    app = CandidateApplication(job_posting_id=posting.id, candidate_id=candidate.id,
        source=ApplicationSource.GOOGLE_FORM, source_reference=uuid4().hex,
        response_data={"Full Name": name, "Email": email, "Phone": "123", "_google_import": {"row_number": row}})
    db.add(app); db.flush()
    doc = CVDocument(application_id=app.id, candidate_id=candidate.id, original_filename="cv.pdf", storage_path="not-read.pdf",
        mime_type="application/pdf", file_size_bytes=100, sha256=cv*64, source=ApplicationSource.GOOGLE_FORM)
    db.add(doc); db.flush()
    return app, doc


def test_same_email_never_overwrites_another_new_submission(identities):
    db, _, _, _, _ = identities
    first = GoogleFormsIntakeService._candidate(db, name="Ada", email="shared@example.com", phone="111", linkedin_url="", portfolio_url="", location="Dhaka")
    second = GoogleFormsIntakeService._candidate(db, name="Nadia", email="shared@example.com", phone="222", linkedin_url="", portfolio_url="", location="Chattogram")
    assert first.id != second.id and first.name == "Ada" and first.phone == "111"
    assert second.name == "Nadia" and second.phone == "222"


def test_saved_profile_uses_the_same_descriptive_header_matching_as_intake(identities):
    _, _, _, _, settings = identities
    profile = submitted_profile({"Full Name (as on CV)": "Ada", "Email-address": "ADA@example.com",
        "Phone number (mobile)": "0123", "LinkedIn profile URL": "https://example.com/ada"}, settings)
    assert profile["name"] == "Ada" and profile["email"] == "ada@example.com"
    assert profile["phone"] == "0123" and profile["linkedin_url"] == "https://example.com/ada"


def test_repair_detaches_shared_profiles_and_keeps_cv_ownership_and_raw_evidence(identities):
    db, owner, _, posting, _ = identities
    shared = Candidate(name="Wrong last name", email="same@example.com")
    first, d1 = application(db, posting, name="Ada", candidate=shared)
    second, d2 = application(db, posting, name="Nadia", candidate=shared, row=3)
    originals = [deepcopy(a.response_data) for a in (first, second)]
    checksums = [d1.sha256, d2.sha256]
    db.commit()
    preview = repair(db, owner.id)
    assert not preview["repaired_application_ids"] and first.candidate_id == second.candidate_id
    result = repair(db, owner.id, apply=True)
    assert len(result["repaired_application_ids"]) == 2
    assert first.candidate_id != second.candidate_id
    assert [db.get(Candidate, a.candidate_id).name for a in (first,second)] == ["Ada", "Nadia"]
    assert [d1.candidate_id, d2.candidate_id] == [first.candidate_id, second.candidate_id]
    assert [d1.sha256, d2.sha256] == checksums
    for a, before in zip((first,second), originals):
        assert {k:v for k,v in a.response_data.items() if k != "_identity_repair"} == before
    count = db.scalar(select(func.count(Candidate.id)))
    assert repair(db, owner.id, apply=True)["repaired_application_ids"] == []
    assert db.scalar(select(func.count(Candidate.id))) == count


@pytest.mark.parametrize("variation", ["name", "email", "cv", "job", "source", "missing_identity", "missing_cv"])
def test_different_submissions_are_never_collapsed_by_email_or_cv_alone(identities, variation):
    db, _, _, posting, _ = identities
    first, _ = application(db, posting)
    second, doc = application(db, posting, row=3)
    if variation == "name": second.response_data = {**second.response_data, "Full Name": "Nadia"}
    elif variation == "email": second.response_data = {**second.response_data, "Email": "other@example.com"}
    elif variation == "cv": doc.sha256 = "b"*64
    elif variation == "job": second.job_posting_id = posting.id+1  # In-memory comparison, not a database insert.
    elif variation == "source": second.source = ApplicationSource.IMPORT
    elif variation == "missing_identity": second.response_data = {}
    elif variation == "missing_cv": db.delete(doc)
    db.flush()
    assert len(canonical_applications(db, [first,second])) == 2


def test_exact_repeats_share_one_cohort_but_originals_are_retained(identities):
    db, owner, _, posting, settings = identities
    first, _ = application(db, posting)
    second, _ = application(db, posting, name="  ADA   Candidate ", row=3)
    db.commit()
    assert [a.id for a in canonical_applications(db, [second,first])] == [second.id]
    assert len(GoogleFormsIntakeService.list_applications(db, interviewer_user_id=owner.id)) == 1
    assert len(ScoringService._inputs(db, posting.id, "no-completed-runs", None)) == 1
    service = ScreeningService(settings, ai=FakeScreeningAI())
    assert service.list_jobs(db, interviewer_user_id=owner.id)[0]["application_count"] == 1
    assert db.scalar(select(func.count(CandidateApplication.id))) == 2
    assert db.scalar(select(func.count(CVDocument.id))) == 2


def test_existing_interview_is_not_displaced_by_a_repeat(identities):
    db, owner, _, posting, _ = identities
    first, _ = application(db, posting)
    second, _ = application(db, posting, row=3)
    batch = InterviewBatch(job_posting_id=posting.id, snapshot={}, confirmation_hash=uuid4().hex, created_by_user_id=owner.id)
    db.add(batch); db.flush(); now = datetime.now(timezone.utc)
    schedule = InterviewSchedule(batch_id=batch.id, job_posting_id=posting.id, application_id=second.id, stage="Interview",
        start_utc=now, end_utc=now+timedelta(minutes=30), timezone="Asia/Dhaka", local_start=now.isoformat(),
        duration_minutes=30, mode="sequential", calendar_uid=uuid4().hex, created_by_user_id=owner.id)
    db.add(schedule); db.flush()
    assert [a.id for a in canonical_applications(db, [first,second])] == [second.id]


def test_deleting_a_grouped_submission_does_not_resurrect_retained_repeats(identities):
    db, _, _, posting, _ = identities
    first, _ = application(db, posting)
    second, doc = application(db, posting, row=3)
    assert canonical_applications(db, [first,second], mark_repeats=True) == [second]
    db.delete(doc); db.delete(second); db.flush()
    assert canonical_applications(db, [first]) == []
    assert canonical_applications(db, [first], mark_repeats=True) == []


def test_same_cv_repeat_uses_latest_contacts_when_no_interview_exists(identities):
    db, _, _, posting, _ = identities
    first, _ = application(db, posting)
    second, _ = application(db, posting, row=3)
    second.response_data = {**second.response_data, "Phone": "456"}
    assert canonical_applications(db, [first,second]) == [second]


def test_repair_is_owner_scoped_and_never_changes_non_form_records(identities):
    db, owner, other, posting, _ = identities
    app, _ = application(db, posting)
    db.get(Candidate, app.candidate_id).name = "Old"
    app.source = ApplicationSource.IMPORT
    db.commit()
    assert repair(db, owner.id, apply=True)["source_applications"] == 0
    assert repair(db, other.id, apply=True)["source_applications"] == 0
    assert db.get(Candidate, app.candidate_id).name == "Old"


def test_sync_with_reordered_rows_never_changes_the_original_person(identities):
    db, owner, _, _, settings = identities
    reader = FakeGoogleReader()
    original = reader.read_sheet(spreadsheet_id="sheet-123", sheet_name="Form Responses 1")
    reader.read_sheet = lambda **kw: deepcopy(original)
    intake = GoogleFormsIntakeService(reader, settings)
    intake.sync(db, interviewer_user_id=owner.id)
    first = db.scalar(select(CandidateApplication))
    old_name = db.get(Candidate, first.candidate_id).name
    changed = deepcopy(original); changed[1][1] = "Other person"
    reader.read_sheet = lambda **kw: deepcopy(changed)
    assert intake.sync(db, interviewer_user_id=owner.id)["imported_applications"] == 1
    assert db.get(Candidate, first.candidate_id).name == old_name
    assert db.scalar(select(func.count(CandidateApplication.id))) == 2
    assert intake.sync(db, interviewer_user_id=owner.id)["imported_applications"] == 0


def test_same_identity_new_cv_reference_creates_a_preserved_revision(identities):
    db, owner, _, _, settings = identities
    reader = FakeGoogleReader()
    original = reader.read_sheet(spreadsheet_id="sheet-123", sheet_name="Form Responses 1")
    reader.read_sheet = lambda **kw: deepcopy(original)
    intake = GoogleFormsIntakeService(reader, settings)
    intake.sync(db, interviewer_user_id=owner.id)
    first = db.scalar(select(CandidateApplication)); original_record = deepcopy(first.response_data)
    revised = deepcopy(original); revised[1][6] = "https://drive.google.com/file/d/new-drive-file-12345/view"
    reader.read_sheet = lambda **kw: deepcopy(revised)
    # This reader rejects the new download; the original document must survive.
    reader.get_file = lambda file_id: (_ for _ in ()).throw(ValueError("CV unavailable"))
    assert intake.sync(db, interviewer_user_id=owner.id)["imported_applications"] == 1
    assert first.response_data == original_record
    assert db.scalar(select(func.count(CVDocument.id))) == 1


def test_profile_repair_and_grouping_on_postgres(pg_database):
    from alembic import command
    command.upgrade(_config(pg_database), "head")
    engine = create_engine(pg_database)
    try:
        with Session(engine, expire_on_commit=False) as db:
            owner, _, posting = _records(db)
            shared = Candidate(name="Last imported name", email="same@example.com")
            first, _ = application(db, posting, name="Ada", candidate=shared)
            second, _ = application(db, posting, name="Nadia", candidate=shared, row=3)
            third, _ = application(db, posting, name="Ada", candidate=shared, row=4)
            db.commit()
            result = repair(db, owner.id, apply=True)
            assert len(result["repaired_application_ids"]) == 3
            assert result["visible_applications"] == 2
            assert len({a.candidate_id for a in (first,second,third)}) == 3
            assert db.scalar(select(func.count(CandidateApplication.id))) == 3
            assert db.scalar(select(func.count(CVDocument.id))) == 3
            assert repair(db, owner.id, apply=True)["repaired_application_ids"] == []
    finally:
        engine.dispose()
