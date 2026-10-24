"""Persistent examples are idempotent, source-bound and entirely offline."""
import io
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from pypdf import PdfReader
from app.database import Base
from app.models.user import User, UserRole
from app.models.candidate import CandidateApplication, CVDocument
from app.models.interview import InterviewSchedule, InterviewDelivery
from app.models.interview_analysis import InterviewAnalysisRun
from app.models.identity import FaceReference, IdentityCheck
from app.models.assessment import AssessmentRun
from app.models.work_sample import WorkSampleAssessment
from app.services import preview_seed
from app.services.final_ranking_service import FinalRankingService
from app.services.interview_analysis import InterviewAnalysisService
from app.services.assessment_service import AssessmentService


def test_seed_complete_flow_is_readable_idempotent_and_has_no_external_effects(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = lambda: Session(engine, expire_on_commit=False)
    monkeypatch.setattr(preview_seed, "private_storage_path", lambda key: tmp_path / key)
    with factory() as db:
        owner = User(name="Owner", email="owner@example.test", password_hash="unused", role=UserRole.INTERVIEWER)
        db.add(owner); db.commit()
        first = preview_seed.seed_recruitment(db, owner.id, session_factory=factory)
        assert [j["title"] for j in first] == ["Backend Engineer", "HR Executive"]
        assert db.scalar(select(func.count(CandidateApplication.id))) == 5
        assert db.scalar(select(func.count(InterviewSchedule.id))) == 5
        assert db.scalar(select(func.count(AssessmentRun.id))) == 5
        assert db.scalar(select(func.count(InterviewDelivery.id))) == 0
        assert db.scalar(select(func.count(FaceReference.id))) == 0  # No invented biometric consent.
        assert db.scalar(select(func.count(IdentityCheck.id))) == 0
        for row in db.scalars(select(WorkSampleAssessment)):
            assert row.status == "approved" and row.snapshot["model"] == "authored-fixture-v1"
        for row in db.scalars(select(InterviewAnalysisRun)):
            value = InterviewAnalysisService(session_factory=factory).read(db, owner.id, row.interview_id)
            assert not value["run"]["stale"]
        for item in first:
            ranking = FinalRankingService(session_factory=factory).read(db, owner.id, item["job_posting_id"])
            from app.assessments.sources import resolve_sources
            from app.schemas.assessment import GenerateAssessment
            differences = []
            for report_id in item["reports"]:
                saved = db.get(AssessmentRun, report_id)
                current = resolve_sources(db, owner.id, saved.application_id, GenerateAssessment())
                differences.extend((k, saved.snapshot.get(k), v) for k, v in current.items() if k not in {"source_key", "selection", "expires_at", "model", "prompt_version"} and saved.snapshot.get(k) != v)
            assert ranking["status"] == "completed" and not ranking["stale"], differences
            assert all(c["final_rank"] and c["final_score"] is not None for c in ranking["candidates"])
            for report_id in item["reports"]:
                report = AssessmentService(session_factory=factory).read(db, owner.id, report_id)
                assert not report["stale"] and report["result"]["score_summary"]["ready"]
        for doc in db.scalars(select(CVDocument)):
            content = (tmp_path / doc.storage_path).read_bytes()
            reader = PdfReader(io.BytesIO(content))
            assert len(reader.pages) == 1 and doc.extracted_text[:30] in reader.pages[0].extract_text()
        before = len(list(tmp_path.rglob("*.pdf")))
        assert preview_seed.seed_recruitment(db, owner.id, session_factory=factory) == first
        assert len(list(tmp_path.rglob("*.pdf"))) == before
        assert db.scalar(select(func.count(CandidateApplication.id))) == 5
        assert db.scalar(select(func.count(AssessmentRun.id))) == 5
