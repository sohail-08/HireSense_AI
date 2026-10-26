"""Disposable PostgreSQL checks: migration, source integrity and consent races."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event
from uuid import uuid4
import pytest
from alembic import command
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.models import Candidate, CandidateApplication, ApplicationSource
from app.models.interview import InterviewBatch, InterviewSchedule
from app.models.identity import FaceReference
from app.services.candidate_identity import CandidateIdentityService
from app.services.interview_rooms import InterviewRooms, RoomConflict
from app.services import preview_seed
from app.services.final_ranking_service import FinalRankingService
from test_pgvector import pg_database, _config  # noqa: F401
from test_screening import _records, _settings
from test_interview_rooms import FakeMedia
from test_candidate_identity import Engine, Reader, pixels


def test_withdrawal_during_real_unlocked_inference_discards_result(pg_database, tmp_path):
    command.upgrade(_config(pg_database), "head")
    engine = create_engine(pg_database); factory = sessionmaker(bind=engine, expire_on_commit=False)
    config = _settings(tmp_path); rooms = InterviewRooms(config, media=FakeMedia(config))
    model = Engine(); service = CandidateIdentityService(settings=config, rooms=rooms, engine=model, session_factory=factory)
    try:
        with factory() as db:
            owner, _, posting = _records(db)
            candidate = Candidate(name="Local concurrency example", email="identity@example.test")
            db.add(candidate); db.flush()
            application = CandidateApplication(candidate_id=candidate.id, job_posting_id=posting.id, source=ApplicationSource.IMPORT, source_reference=uuid4().hex)
            db.add(application); db.flush()
            batch = InterviewBatch(job_posting_id=posting.id, snapshot={}, confirmation_hash=uuid4().hex, created_by_user_id=owner.id)
            db.add(batch); db.flush(); now = datetime.now(timezone.utc)
            row = InterviewSchedule(batch_id=batch.id, job_posting_id=posting.id, application_id=application.id, stage="interview",
                start_utc=now+timedelta(minutes=5), end_utc=now+timedelta(minutes=35), timezone="Asia/Dhaka", local_start=now.isoformat(),
                duration_minutes=30, mode="sequential", calendar_uid=uuid4().hex, created_by_user_id=owner.id)
            material = rooms.links.material(application.id, row.start_utc, row.end_utc); rooms.links.install(row, material)
            db.add(row); db.commit()
            cookie, _, _ = rooms.exchange(db, rooms.links.token(material))
            service.import_photo(db, application, Reader(), ["unit-file"]); db.commit()
            service.live_consent(db, cookie, True)
            ref_id = db.scalar(select(FaceReference.id).where(FaceReference.application_id == application.id)); db.commit()
            service.process_reference(ref_id)
            rooms.waiting(db, cookie); rooms.admit(db, owner.id, row.id)
            state = service.candidate_state(db, cookie)
        entered, resume = Event(), Event()
        def pause():
            entered.set(); assert resume.wait(timeout=10)
        model.hook = pause
        def verify():
            with factory() as db:
                return service.verify(db, cookie, [pixels()]*3, state["version"])
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(verify)
            assert entered.wait(timeout=10)
            try:
                with factory() as db: service.withdraw(db, cookie)
            finally: resume.set()
            with pytest.raises(RoomConflict): future.result(timeout=10)
        with factory() as db:
            assert service.candidate_state(db, cookie)["status"] == "withdrawn"
            ref = db.get(FaceReference, ref_id)
            assert not ref.photo_cipher and not ref.embedding_cipher
    finally: engine.dispose()


def test_full_examples_on_postgres_have_current_ranking_and_no_duplicates(pg_database, tmp_path, monkeypatch):
    command.upgrade(_config(pg_database), "head")
    engine = create_engine(pg_database); factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(preview_seed, "private_storage_path", lambda key: tmp_path / key)
    try:
        with factory() as db:
            owner, _, _ = _records(db)
            first = preview_seed.seed_recruitment(db, owner.id, session_factory=factory)
            for item in first:
                result = FinalRankingService(session_factory=factory).read(db, owner.id, item["job_posting_id"])
                assert not result["stale"] and result["status"] == "completed"
                assert all(c["final_rank"] and c["final_score"] for c in result["candidates"])
            assert preview_seed.seed_recruitment(db, owner.id, session_factory=factory) == first
    finally: engine.dispose()
