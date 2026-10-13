"""Actual row-lock tests on the existing disposable PostgreSQL test fixture."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4
from alembic import command
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models import Candidate, CandidateApplication, ApplicationSource
from app.models.interview import InterviewBatch, InterviewSchedule
from app.services.interview_rooms import InterviewRooms, RoomAccessError
from test_pgvector import pg_database, _config
from test_screening import _records, _settings
from test_interview_rooms import FakeMedia


def test_concurrent_admission_and_end_are_serialized(pg_database, tmp_path):
    command.upgrade(_config(pg_database), "head")
    engine = create_engine(pg_database)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    config = _settings(tmp_path)
    media = FakeMedia(config)
    service = InterviewRooms(config, media=media)
    try:
        with factory() as db:
            owner, _, posting = _records(db)
            candidate = Candidate(name="Concurrency test", email="candidate@example.com")
            db.add(candidate); db.flush()
            app = CandidateApplication(candidate_id=candidate.id, job_posting_id=posting.id,
                source=ApplicationSource.IMPORT, source_reference=uuid4().hex)
            db.add(app); db.flush()
            batch = InterviewBatch(job_posting_id=posting.id, snapshot={}, confirmation_hash=uuid4().hex,
                created_by_user_id=owner.id)
            db.add(batch); db.flush()
            now = datetime.now(timezone.utc)
            row = InterviewSchedule(batch_id=batch.id, job_posting_id=posting.id, application_id=app.id,
                stage="technical", start_utc=now + timedelta(minutes=5), end_utc=now + timedelta(minutes=35),
                timezone="Asia/Dhaka", local_start=now.isoformat(), duration_minutes=30, buffer_minutes=0,
                mode="sequential", calendar_uid=uuid4().hex, created_by_user_id=owner.id)
            material = service.links.material(app.id, row.start_utc, row.end_utc)
            service.links.install(row, material)
            db.add(row); db.commit()
            owner_id, interview_id = owner.id, row.id
            cookie, _, _ = service.exchange(db, service.links.token(material))
            service.waiting(db, cookie)
        barrier = Barrier(2)
        def admit():
            with factory() as db:
                barrier.wait(timeout=10)
                return service.admit(db, owner_id, interview_id)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: admit(), range(2)))
        assert results[0]["room_version"] == results[1]["room_version"]
        barrier = Barrier(2)
        def end():
            with factory() as db:
                barrier.wait(timeout=10)
                return service.end(db, owner_id, interview_id)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: end(), range(2)))
        assert all(item["room_status"] == "ended" for item in results)
        assert len(media.closed) == 1
        with factory() as db:
            try:
                service.media_access(db, candidate_token=cookie)
            except RoomAccessError as error:
                assert error.code == "ended"
            else:
                raise AssertionError("Ended room issued a candidate credential")
    finally:
        engine.dispose()
