from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from alembic import command
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from app.models.interview import InterviewBatch, InterviewSchedule, InterviewDelivery
from app.services.interview_service import InterviewService
from app.services.scoring_service import ScoringService
from app.services.screening_service import ScreeningService
from app.schemas.interview import SelectionRequest
from app.schemas.scoring import ScoreRunRequest
from test_pgvector import pg_database, _config
from test_screening import _records, _application_with_docx, _settings, FakeScreeningAI
from test_scoring import approval
from test_interviews import FakeSender, schedule_data, confirm_data


def test_postgresql_concurrent_confirmation_delivery_and_restart(pg_database, tmp_path):
    command.upgrade(_config(pg_database), "head")
    engine = create_engine(pg_database)
    settings, sender = _settings(tmp_path), FakeSender()
    service = InterviewService(settings, sender=sender, session_factory=lambda: Session(engine, expire_on_commit=False))
    with Session(engine, expire_on_commit=False) as db:
        owner, _, posting = _records(db)
        _application_with_docx(db, tmp_path, posting, 1)
        db.commit()
        screening = ScreeningService(settings, ai=FakeScreeningAI())
        screened = screening.create_batch(db, interviewer_user_id=owner.id, job_posting_id=posting.id, application_ids=None)
        screening.process_batch(db, batch_id=screened.id)
        scoring = ScoringService()
        configuration = scoring.approve(db, user_id=owner.id, job_id=posting.id, data=approval(db, owner, posting))
        ranking = scoring.run(db, user_id=owner.id, job_id=posting.id, data=ScoreRunRequest(configuration_id=configuration["id"]))
        selection = service.preview_selection(db, owner.id, SelectionRequest(job_posting_id=posting.id, ranking_run_id=ranking["id"], mode="top_n", top_n=1))
        preview = service.prepare(db, owner.id, schedule_data(selection["selection_token"]))
        owner_id, batch_id = owner.id, preview["id"]
    barrier = Barrier(2)
    def confirm():
        with Session(engine, expire_on_commit=False) as db:
            barrier.wait(timeout=10)
            return service.confirm(db, owner_id, batch_id, confirm_data(preview))["id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: confirm(), range(2)))
    assert results == [batch_id, batch_id]
    with Session(engine) as db:
        assert db.scalar(select(func.count(InterviewSchedule.id))) == 1
        assert db.scalar(select(func.count(InterviewDelivery.id))) == 1
    barrier = Barrier(2)
    def deliver():
        with Session(engine, expire_on_commit=False) as db:
            barrier.wait(timeout=10)
            service.deliver_pending(db, batch_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: deliver(), range(2)))
    assert len(sender.calls) == 1
    with Session(engine) as restarted:
        assert service.batch(restarted, owner_id, batch_id)["sent"] == 1
        assert service.schedules(restarted, owner_id)[0]["sequence"] == 0
        assert restarted.scalar(select(InterviewDelivery)).attempts == 1
    engine.dispose()
