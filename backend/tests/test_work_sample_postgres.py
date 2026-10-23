"""Real row-lock races, using only explicitly configured disposable databases."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4
from alembic import command
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models import Candidate, CandidateApplication, ApplicationSource
from app.models.interview import InterviewBatch, InterviewSchedule
from app.schemas.work_sample import Task, SaveTask, Action, CandidateReady, SaveSubmission, CorrectnessDecision
from app.services.interview_rooms import InterviewRooms, RoomConflict, RoomAccessError
from app.services.work_sample import WorkSampleService
from test_pgvector import pg_database, _config  # noqa: F401
from test_screening import _records, _settings
from test_interview_rooms import FakeMedia
from test_work_samples import TASK


def test_concurrent_candidate_saves_and_shutdown_are_serialized(pg_database, tmp_path):
    command.upgrade(_config(pg_database), "head")
    engine = create_engine(pg_database)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = _settings(tmp_path)
    rooms = InterviewRooms(settings, media=FakeMedia(settings))
    service = WorkSampleService(rooms=rooms, session_factory=factory)
    try:
        with factory() as db:
            owner, _, posting = _records(db)
            candidate = Candidate(name="Synthetic practical test", email="practical@example.test")
            db.add(candidate); db.flush()
            application = CandidateApplication(candidate_id=candidate.id, job_posting_id=posting.id,
                source=ApplicationSource.IMPORT, source_reference=uuid4().hex)
            db.add(application); db.flush()
            batch = InterviewBatch(job_posting_id=posting.id, snapshot={}, confirmation_hash=uuid4().hex,
                created_by_user_id=owner.id)
            db.add(batch); db.flush()
            current = datetime.now(timezone.utc)
            row = InterviewSchedule(batch_id=batch.id, job_posting_id=posting.id, application_id=application.id,
                stage="practical", start_utc=current, end_utc=current + timedelta(minutes=30), timezone="Asia/Dhaka",
                local_start=current.isoformat(), duration_minutes=30, buffer_minutes=0, mode="sequential",
                calendar_uid=uuid4().hex, created_by_user_id=owner.id)
            material = rooms.links.material(application.id, row.start_utc, row.end_utc)
            rooms.links.install(row, material)
            db.add(row); db.commit()
            owner_id, interview_id = owner.id, row.id
            cookie, _, _ = rooms.exchange(db, rooms.links.token(material))
            rooms.waiting(db, cookie); rooms.admit(db, owner.id, row.id)
            saved = service.save_task(db, owner.id, row.id, SaveTask(version=0, task=Task(**TASK)))
            shared = service.action(db, owner.id, row.id, Action(version=saved["exercise"]["version"], action="share"))
            attempt_id = shared["exercise"]["attempt"]["id"]
            ready = service.ready(db, cookie, CandidateReady(attempt_id=attempt_id))
            service.action(db, owner.id, row.id, Action(version=ready["exercise"]["version"], action="start"))
        barrier = Barrier(2)
        def save(text):
            with factory() as db:
                barrier.wait(timeout=10)
                try:
                    service.save_submission(db, cookie, SaveSubmission(attempt_id=attempt_id, revision=0, content=text))
                    return "saved"
                except RoomConflict:
                    db.rollback()
                    return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(save, ["first writer", "second writer"])) == ["conflict", "saved"]
        with factory() as db:
            attempt = service.read(db, owner_id, interview_id)["exercise"]["attempt"]
            preserved = attempt["content"]
            assert attempt["revision"] == 1
        barrier = Barrier(2)
        def submit_or_end(kind):
            with factory() as db:
                barrier.wait(timeout=10)
                if kind == "end":
                    rooms.end(db, owner_id, interview_id)
                    return "ended"
                try:
                    service.save_submission(db, cookie, SaveSubmission(attempt_id=attempt_id, revision=1,
                        content="final response", submit=True))
                    return "submitted"
                except (RoomConflict, RoomAccessError):
                    db.rollback()
                    return "closed"
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(submit_or_end, ["submit", "end"]))
        with factory() as db:
            attempt = service.read(db, owner_id, interview_id)["exercise"]["attempt"]
            assert attempt["status"] == ("submitted" if outcomes[0] == "submitted" else "interview_ended")
            assert attempt["content"] == ("final response" if outcomes[0] == "submitted" else preserved)
            assert attempt["submission_hash"]
            submission_hash = attempt["submission_hash"]
        barrier = Barrier(2)
        def decide(correct):
            with factory() as db:
                barrier.wait(timeout=10)
                try:
                    value = service.decide(db, owner_id, interview_id, CorrectnessDecision(
                        submission_hash=submission_hash, correct=correct, confirmed=True))
                    return value["exercise"]["decision"]["correct"]
                except RoomConflict:
                    db.rollback()
                    return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            decisions = list(pool.map(decide, [True, False]))
        assert decisions.count("conflict") == 1
        with factory() as db:
            decision = service.read(db, owner_id, interview_id)["exercise"]["decision"]
            assert decision["score"] == (100 if decision["correct"] else 0)
            assert decision["submission_hash"] == submission_hash
    finally:
        engine.dispose()
