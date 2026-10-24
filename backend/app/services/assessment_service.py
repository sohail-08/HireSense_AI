import copy
from datetime import datetime, timezone
from fractions import Fraction
from uuid import uuid4
from sqlalchemy import select, update, delete, event
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.config import get_settings
from app.agents.interview_analysis import digest
from app.assessments.sources import owned_application, resolve_sources
from app.assessments.workflow import ConsolidatedAssessmentGraph, PROMPT_VERSION, POLICY
from app.models.assessment import AssessmentRun, AssessmentReview, AssessmentComparison, ReportArtifact
from app.models.candidate import CandidateApplication
from app.models.interview import InterviewSchedule
from app.schemas.assessment import GenerateAssessment
from app.services.interview_content import utc
from app.storage import private_storage_path


def now():
    return datetime.now(timezone.utc)


def unexpired(row):
    return row.expires_at is None or utc(row.expires_at) > now()


@event.listens_for(Session, "after_commit")
def remove_report_files(db):
    for path in db.info.pop("deleted_report_paths", set()):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass  # Private orphan file remains inaccessible; retry cleanup operationally.


@event.listens_for(Session, "after_rollback")
def retain_report_files(db):
    db.info.pop("deleted_report_paths", None)


class AssessmentService:
    def __init__(self, model=None, session_factory=None):
        self.model = model
        self.factory = session_factory or SessionLocal

    def enqueue(self, db, user_id, application_id, request):
        owned_application(db, user_id, application_id, lock=True)
        snapshot = resolve_sources(db, user_id, application_id, request)
        snapshot.update(model=get_settings().gemini_chat_model, prompt_version=PROMPT_VERSION)
        fingerprint = digest([snapshot["source_key"], PROMPT_VERSION, snapshot["model"], uuid4().hex if request.new_version else None])
        existing = db.scalar(select(AssessmentRun).where(AssessmentRun.application_id == application_id, AssessmentRun.fingerprint == fingerprint))
        if existing:
            db.commit()
            return existing
        last = db.scalar(select(AssessmentRun).where(AssessmentRun.application_id == application_id).order_by(AssessmentRun.version.desc()).limit(1))
        run = AssessmentRun(application_id=application_id, job_posting_id=snapshot["identification"]["job_posting_id"],
            version=last.version + 1 if last else 1, fingerprint=fingerprint, snapshot=snapshot, result={},
            status="queued", stage="queued", completeness="partial", created_by=user_id,
            expires_at=datetime.fromisoformat(snapshot["expires_at"]) if snapshot["expires_at"] else None)
        db.add(run)
        db.commit()
        return run

    @staticmethod
    def owned_run(db, user_id, run_id):
        row = db.get(AssessmentRun, run_id)
        if not row or not unexpired(row): raise LookupError("Assessment not found or expired")
        owned_application(db, user_id, row.application_id)
        return row

    def read(self, db, user_id, run_id):
        row = self.owned_run(db, user_id, run_id)
        try:
            current = resolve_sources(db, user_id, row.application_id, GenerateAssessment.model_validate(row.snapshot["selection"]))
            stale = current["source_key"] != row.snapshot["source_key"] or row.snapshot.get("prompt_version") != PROMPT_VERSION
        except (ValueError, LookupError):
            stale = True
        notes = [{"id": n.id, "note": n.note, "reviewed": n.reviewed, "author_id": n.created_by,
                  "created_at": utc(n.created_at).isoformat()} for n in db.scalars(select(AssessmentReview).where(
                      AssessmentReview.run_id == row.id).order_by(AssessmentReview.id))]
        from app.assessments.performance_summary import report_performance_summary
        presented = copy.deepcopy(row.result)
        if presented.get("evidence_summary"):
            presented["evidence_summary"] = report_performance_summary(presented)
        return {"id": row.id, "version": row.version, "application_id": row.application_id, "job_posting_id": row.job_posting_id,
            "status": row.status, "stage": row.stage, "completeness": row.completeness,
            "review_status": "reviewed" if any(n["reviewed"] for n in notes) else "not_reviewed",
            "created_at": utc(row.created_at).isoformat(), "completed_at": utc(row.completed_at).isoformat() if row.completed_at else None,
            "error": row.error, "stale": stale, "selection_policy": row.snapshot["selection_policy"],
            "source_versions": {"requirement_version": row.snapshot["identification"]["requirement_version"],
                "scoring_run_id": (row.snapshot["cv"] or {}).get("scoring_run_id"),
                "interview_analysis_ids": [i["analysis"]["id"] for i in row.snapshot["interviews"] if i["analysis"]]},
            "missing": row.result.get("missing", row.snapshot["missing"]), "result": presented, "notes": notes}

    def list_application(self, db, user_id, application_id):
        app, _ = owned_application(db, user_id, application_id)
        runs = list(db.scalars(select(AssessmentRun).where(AssessmentRun.application_id == application_id).order_by(AssessmentRun.version.desc())))
        interviews = list(db.scalars(select(InterviewSchedule).where(InterviewSchedule.application_id == application_id).order_by(InterviewSchedule.start_utc.desc())))
        ready = resolve_sources(db, user_id, application_id, GenerateAssessment())
        return {"application_id": app.id, "job_posting_id": app.job_posting_id, "identification": ready["identification"],
            "missing": ready["missing"], "selection_policy": ready["selection_policy"],
            "versions": [{"id": r.id, "version": r.version, "status": r.status, "completeness": r.completeness} for r in runs if unexpired(r)],
            "interviews": [{"id": i.id, "date": utc(i.start_utc).isoformat(), "status": i.status} for i in interviews]}

    def process(self, run_id):
        with self.factory() as db:
            if db.execute(update(AssessmentRun).where(AssessmentRun.id == run_id, AssessmentRun.status == "queued")
                          .values(status="processing", stage="resolve_source_versions")).rowcount != 1:
                db.rollback()
                return
            db.commit()
            row = db.get(AssessmentRun, run_id)
            snapshot, owner = copy.deepcopy(row.snapshot), row.created_by
        def checkpoint(stage):
            with self.factory() as db:
                row = self.owned_run(db, owner, run_id)
                if row.status != "processing": raise ValueError("Assessment no longer processing")
                row.stage = stage
                db.commit()
        def persist(result):
            with self.factory() as db:
                row = self.owned_run(db, owner, run_id)
                if row.status != "processing": raise ValueError("Assessment no longer processing")
                row.result, row.completeness = result, result["completeness"]
                row.status, row.stage, row.completed_at = "completed", "completed", now()
                db.commit()
        try:
            # Answer analysis already used the model. Combining numbers and writing
            # short, source-backed explanations needs no additional provider call.
            ConsolidatedAssessmentGraph(self.model, checkpoint, persist).graph.invoke({"snapshot": snapshot})
        except Exception:
            with self.factory() as db:
                db.execute(update(AssessmentRun).where(AssessmentRun.id == run_id, AssessmentRun.status == "processing")
                    .values(status="failed", stage="failed", error="Assessment could not finish. Check saved sources and generate a new version.", completed_at=now()))
                db.commit()

    def tick(self):
        with self.factory() as db:
            self.delete_sources(db, expired=True)
            db.commit()
            pending = db.scalar(select(AssessmentRun.id).where(AssessmentRun.status == "queued").order_by(AssessmentRun.id).limit(1))
        if pending is not None:
            self.process(pending)
        # The same durable background loop also renders requested report exports.
        from app.services.report_service import ReportService
        ReportService(session_factory=self.factory).tick()

    @staticmethod
    def recover(db):
        db.execute(update(AssessmentRun).where(AssessmentRun.status == "processing").values(status="queued", stage="restart_recovery"))
        db.execute(update(ReportArtifact).where(ReportArtifact.status == "processing").values(status="queued"))
        db.commit()

    def review(self, db, user_id, run_id, request):
        run = self.owned_run(db, user_id, run_id)
        if run.status != "completed": raise ValueError("Wait for report generation before recording a review")
        note = AssessmentReview(run_id=run_id, note=request.note.strip(), reviewed=request.reviewed, created_by=user_id)
        if not note.note: raise ValueError("Enter a review note")
        db.add(note)
        db.commit()
        return self.read(db, user_id, run_id)

    def compare(self, db, user_id, ids):
        reports = [self.read(db, user_id, i) for i in ids]
        jobs = {r["job_posting_id"] for r in reports}
        if len(jobs) != 1 or len({r["application_id"] for r in reports}) != len(reports):
            raise ValueError("Compare distinct applications for the same job posting")
        if any(r["status"] != "completed" for r in reports): raise ValueError("Wait for each assessment to finish")
        issues, interview_issues = [], []
        signatures, rubrics = set(), set()
        for report in reports:
            cv = report["result"]["cv"]
            if not cv or cv["final_score"] is None or cv["screening_status"] != "completed" or not cv.get("compatible", True):
                issues.append(f"Application #{report['application_id']} has no comparable completed CV score")
            else:
                signatures.add(digest([report["result"]["identification"]["requirement_version"], cv["formula_version"], cv["configuration"]]))
            if report["stale"]: issues.append(f"Application #{report['application_id']} uses stale source versions; generate a new assessment")
            for interview in report["result"]["interviews"]:
                if interview["analysis_id"]: rubrics.add(interview["rubric_version"])
        if len(signatures) > 1: issues.append("Requirement versions or CV formulas/weights differ; use a common approved configuration before comparing score order")
        if len(rubrics) > 1: interview_issues.append("Interview rubrics differ; interview ratings are informational only")
        ordered = sorted(reports, key=lambda r: r["application_id"])
        if not issues:
            def exact(report):
                cv = report["result"]["cv"]
                value = cv["breakdown"].get("exact_final_score")
                return Fraction(int(value["numerator"]), int(value["denominator"])) if value else Fraction(cv["final_score"])
            ordered.sort(key=lambda r: (-exact(r), r["application_id"]))
            previous, rank = None, None
            for index, report in enumerate(ordered, 1):
                value = exact(report)
                if value != previous: rank = index
                report["comparison_cv_rank"], previous = rank, value
        snapshot = {"basis": "CV score order" if not issues else "Informational comparison", "policy": POLICY,
            "combined_ranking_available": False, "cv_order_compatible": not issues, "incompatibilities": sorted(set(issues)),
            "interview_incompatibilities": interview_issues, "assessments": ordered,
            "selected_cohort_application_ids": sorted(r["application_id"] for r in reports),
            "assessment_ids": ids, "cohort_policy": "Explicit comparison cohort; original full-job CV ranks are preserved in each component."}
        if any(r["result"].get("score_summary", {}).get("ready") for r in reports):
            from app.assessments.final_scoring import rank_reports, POLICY as FINAL_POLICY
            ordered, issue = rank_reports(reports)
            snapshot.update(basis="Final candidate ranking", policy=FINAL_POLICY, assessments=ordered,
                combined_ranking_available=not issue and any(r.get("final_rank") for r in ordered),
                incompatibilities=[issue] if issue else [])
        fingerprint = digest(snapshot)
        job_id = next(iter(jobs))
        old = db.scalar(select(AssessmentComparison).where(AssessmentComparison.job_posting_id == job_id, AssessmentComparison.fingerprint == fingerprint))
        if old: return self.read_comparison(db, user_id, old.id)
        expiry = [self.owned_run(db, user_id, i).expires_at for i in ids if self.owned_run(db, user_id, i).expires_at]
        comparison = AssessmentComparison(job_posting_id=job_id, fingerprint=fingerprint, assessment_ids=ids, snapshot=snapshot,
            created_by=user_id, expires_at=min(utc(e) for e in expiry) if expiry else None)
        db.add(comparison)
        db.commit()
        return self.read_comparison(db, user_id, comparison.id)

    def read_comparison(self, db, user_id, comparison_id):
        row = db.get(AssessmentComparison, comparison_id)
        if not row or not unexpired(row): raise LookupError("Comparison not found or expired")
        from app.services.final_ranking_service import FinalRankingService
        FinalRankingService.owned_job(db, user_id, row.job_posting_id)
        current = [self.read(db, user_id, i) for i in row.assessment_ids]
        return {"id": row.id, "created_at": utc(row.created_at).isoformat(), "snapshot": copy.deepcopy(row.snapshot),
            "stale_source_assessment_ids": [r["id"] for r in current if r["stale"]]}

    @staticmethod
    def delete_sources(db, *, application_ids=(), interview_ids=(), expired=False):
        rows = list(db.scalars(select(AssessmentRun)))
        ids = [r.id for r in rows if r.application_id in application_ids or
            any(i["id"] in interview_ids for i in r.snapshot.get("interviews", [])) or
            any(i["interview_id"] in interview_ids for i in r.snapshot.get("practical_assessments", [])) or (expired and not unexpired(r))]
        comparisons = list(db.scalars(select(AssessmentComparison)))
        cids = [c.id for c in comparisons if set(c.assessment_ids) & set(ids) or
            set(c.snapshot.get("selected_cohort_application_ids", [])) & set(application_ids) or
            set(c.snapshot.get("source_interview_ids", [])) & set(interview_ids) or (expired and not unexpired(c))]
        if not ids and not cids: return
        artifacts = list(db.scalars(select(ReportArtifact).where(
            ReportArtifact.assessment_id.in_(ids) | ReportArtifact.comparison_id.in_(cids))))
        paths = db.info.setdefault("deleted_report_paths", set())
        for artifact in artifacts:
            if artifact.storage_key: paths.add(private_storage_path(artifact.storage_key))
        db.execute(delete(ReportArtifact).where(ReportArtifact.id.in_([a.id for a in artifacts])))
        db.execute(delete(AssessmentComparison).where(AssessmentComparison.id.in_(cids)))
        db.execute(delete(AssessmentReview).where(AssessmentReview.run_id.in_(ids)))
        db.execute(delete(AssessmentRun).where(AssessmentRun.id.in_(ids)))
