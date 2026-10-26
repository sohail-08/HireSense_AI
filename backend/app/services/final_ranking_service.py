"""Persisted job-wide scoring coordinator. Reads never call an AI provider."""
import copy
from datetime import datetime
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.agents.interview_analysis import digest, PROMPT_VERSION, RUBRIC_VERSION, PAIRING_VERSION
from app.agents.interview_scope import SCOPING_VERSION, apply_scoring_scope
from app.assessments.sources import resolve_sources
from app.assessments.final_scoring import FORMULA_VERSION, POLICY, rank_reports
from app.models.assessment import AssessmentComparison, AssessmentRun
from app.models.candidate import CandidateApplication
from app.models.job import JobPosting, JobDescription
from app.models.interview_analysis import InterviewAnalysisRun
from app.schemas.assessment import GenerateAssessment
from app.services.assessment_service import AssessmentService, unexpired
from app.services.interview_analysis import InterviewAnalysisService
from app.services.application_identity import current_application_ids


def source_identity(source):
    # Selection syntax and wall-clock retention time are not source changes.
    return digest({k: v for k, v in source.items() if k not in {
        "source_key", "selection", "expires_at", "model", "prompt_version"}})


def needs_answer_scoring(result, rubric):
    return rubric != RUBRIC_VERSION or any(not p.get("score") or p["state"] not in {"analyzed", "unanswered"} or
        p["score"].get("rubric_version") != rubric for p in result.get("pairs", [])
        if not p.get("excluded") and p.get("state") != "excluded")


class FinalRankingService:
    def __init__(self, session_factory=None):
        self.factory = session_factory or SessionLocal
        self.request_bound_factory = session_factory is None

    @staticmethod
    def owned_job(db, user_id, job_id, lock=False):
        query = select(JobPosting).join(JobDescription).where(JobPosting.id == job_id,
            JobDescription.created_by_user_id == user_id)
        row = db.scalar(query.with_for_update() if lock else query)
        if not row: raise LookupError("Job posting not found")
        return row

    @staticmethod
    def latest(db, job_id):
        rows = db.scalars(select(AssessmentComparison).where(AssessmentComparison.job_posting_id == job_id)
            .order_by(AssessmentComparison.id.desc()))
        return next((r for r in rows if r.snapshot.get("kind") == "final_ranking" and unexpired(r)), None)

    def answer_readiness(self, db, user_id, sources):
        """Read saved analysis readiness only. Ranking never requests model work."""
        analyses = InterviewAnalysisService(session_factory=self.factory)
        result = []
        for source in sources:
            for interview in source["interviews"]:
                response = analyses.read(db, user_id, interview["id"])
                item = response["run"]
                raw = db.get(InterviewAnalysisRun, item["id"]) if item else None
                result.append({"application_id": source["identification"]["application_id"], "interview_id": interview["id"],
                    "run_id": item["id"] if item else None, "status": item["status"] if item else "missing",
                    "stale": bool(item and item["stale"]), "scored": bool(raw and not needs_answer_scoring(apply_scoring_scope(raw.result, raw.snapshot), raw.snapshot.get("rubric_version")))})
        return result

    def start(self, db, user_id, job_id):
        if self.request_bound_factory:
            # Honor the caller's database binding for inline aggregation, including
            # injected request sessions and isolated tests.
            bind = db.get_bind()
            self.factory = lambda: Session(bind, expire_on_commit=False)
        self.owned_job(db, user_id, job_id, lock=True)
        previous = self.latest(db, job_id)
        if previous and previous.snapshot["status"] == "processing":
            db.commit()
            self.advance(previous.id)
            db.expire_all()
            return self.read(db, user_id, job_id)
        ids = current_application_ids(db, job_id)
        if not ids: raise ValueError("No candidates have applied for this job yet.")
        sources = [resolve_sources(db, user_id, app_id, GenerateAssessment()) for app_id in ids]
        readiness = self.answer_readiness(db, user_id, sources)
        fingerprint = digest([FORMULA_VERSION, self.scoring_policy(), [source_identity(s) for s in sources], readiness])
        existing = db.scalar(select(AssessmentComparison).where(AssessmentComparison.job_posting_id == job_id,
            AssessmentComparison.fingerprint == fingerprint))
        if existing and unexpired(existing):
            # An explicit retry after failed processing gets a new durable attempt.
            failed_report = any(r.get("status") == "failed" for r in existing.snapshot.get("assessments", []))
            if existing.snapshot.get("status") != "failed" and not failed_report:
                return self.present(db, user_id, existing)
        if existing:
            fingerprint = digest([fingerprint, uuid4().hex])
        expiry = [datetime.fromisoformat(s["expires_at"]) for s in sources if s["expires_at"]]
        plans = [{"application_id": s["identification"]["application_id"], "interview_ids": [i["id"] for i in s["interviews"]],
            "scoring_run_id": (s.get("cv") or {}).get("scoring_run_id"), "analysis_ids": [], "analysis_requested": False,
            "assessment_id": None} for s in sources]
        snapshot = {"kind": "final_ranking", "status": "processing", "stage": "calculating_scores", "policy": POLICY,
            "analysis_readiness": readiness,
            "scoring_policy": self.scoring_policy(),
            "basis": "Final candidate ranking", "formula_version": FORMULA_VERSION, "plans": plans,
            "selected_cohort_application_ids": ids, "source_interview_ids": [i for p in plans for i in p["interview_ids"]],
            "assessment_ids": [], "assessments": [], "incompatibilities": [], "interview_incompatibilities": [],
            "combined_ranking_available": False, "cv_order_compatible": True, "cohort_policy": "All candidates for this job."}
        row = AssessmentComparison(job_posting_id=job_id, fingerprint=fingerprint, assessment_ids=[], snapshot=snapshot,
            created_by=user_id, expires_at=min(expiry) if expiry else None)
        db.add(row)
        db.commit()
        self.advance(row.id)
        db.expire_all()
        return self.present(db, user_id, db.get(AssessmentComparison, row.id))

    def read(self, db, user_id, job_id):
        self.owned_job(db, user_id, job_id)
        row = self.latest(db, job_id)
        if row: return self.present(db, user_id, row)
        ids = current_application_ids(db, job_id)
        candidates = []
        for app_id in ids:
            source = resolve_sources(db, user_id, app_id, GenerateAssessment())
            candidates.append({"application_id": app_id, "candidate_name": source["identification"]["candidate_name"],
                "cv_score": (source.get("cv") or {}).get("final_score"), "interview_score": None, "practical_score": None, "final_score": None,
                "final_rank": None, "assessment_id": None, "reason": "Use Analyze answers in the interview console, then calculate the final ranking from saved scores."})
        return {"id": None, "status": "not_started", "stage": "not_started", "policy": POLICY, "candidates": candidates,
            "stale": False, "incompatibilities": []}

    def present(self, db, user_id, row):
        self.owned_job(db, user_id, row.job_posting_id)
        snapshot = row.snapshot
        current_ids = current_application_ids(db, row.job_posting_id)
        stale = sorted(current_ids) != sorted(snapshot["selected_cohort_application_ids"]) or snapshot.get("scoring_policy") != self.scoring_policy() or snapshot.get("formula_version") != FORMULA_VERSION
        candidates = []
        saved = {r["application_id"]: r for r in snapshot.get("assessments", [])}
        service = AssessmentService(session_factory=self.factory)
        current_sources = []
        for plan in snapshot["plans"]:
            app_id = plan["application_id"]
            current = resolve_sources(db, user_id, app_id, GenerateAssessment())
            current_sources.append(current)
            item = saved.get(app_id)
            if item and plan.get("assessment_id"):
                run = service.owned_run(db, user_id, plan["assessment_id"])
                stale = stale or source_identity(current) != source_identity(run.snapshot)
            summary = (item or {}).get("result", {}).get("score_summary", {})
            candidates.append({"application_id": app_id, "candidate_name": current["identification"]["candidate_name"],
                "cv_score": summary.get("cv_score", (current.get("cv") or {}).get("final_score")),
                "interview_score": summary.get("interview_score"), "practical_score": summary.get("practical_score"), "final_score": summary.get("final_score"),
                "final_rank": (item or {}).get("final_rank"), "assessment_id": plan.get("assessment_id"),
                "reason": summary.get("reason", plan.get("error", "Interview not scored yet"))})
        candidates.sort(key=lambda c: (c["final_rank"] is None, c["final_rank"] or 0, c["application_id"]))
        stale = stale or self.answer_readiness(db, user_id, current_sources) != snapshot.get("analysis_readiness")
        return {"id": row.id, "status": snapshot["status"], "stage": snapshot["stage"], "policy": snapshot.get("policy", POLICY),
            "candidates": candidates, "stale": stale, "incompatibilities": snapshot.get("incompatibilities", []),
            "error": snapshot.get("error")}

    @staticmethod
    def scoring_policy():
        return {"prompt": PROMPT_VERSION, "rubric": RUBRIC_VERSION, "pairing": PAIRING_VERSION, "scoping": SCOPING_VERSION, "ranking_flow": "saved-scores-only-v1"}

    def tick(self):
        with self.factory() as db:
            rows = db.scalars(select(AssessmentComparison).order_by(AssessmentComparison.id))
            row_id = next((r.id for r in rows if r.snapshot.get("kind") == "final_ranking" and
                r.snapshot.get("status") == "processing" and unexpired(r)), None)
        if row_id is not None:
            self.advance(row_id)

    def advance(self, row_id):
        with self.factory() as db:
            row = db.get(AssessmentComparison, row_id)
            if not row or not unexpired(row) or row.snapshot.get("status") != "processing": return
            snapshot = copy.deepcopy(row.snapshot)
            try:
                assessments = AssessmentService(session_factory=self.factory)
                waiting = False
                for plan in snapshot["plans"]:
                    source = resolve_sources(db, row.created_by, plan["application_id"], GenerateAssessment(
                        scoring_run_id=plan["scoring_run_id"], interview_ids=plan["interview_ids"]))
                    ready = self.answer_readiness(db, row.created_by, [source])
                    plan["analysis_ids"], plan["error"] = [], None
                    if not source["interviews"]:
                        plan["error"] = "Complete the interview and use Analyze answers in its console first."
                    for interview, status in zip(source["interviews"], ready):
                        if not interview["finalized"] or not interview["segments"]:
                            plan["error"] = "Finalize the transcript and use Analyze answers in the interview console first."
                        elif status["status"] in {"queued", "processing"}:
                            plan["error"] = "Answer analysis is still running. Wait for it to finish, then calculate the ranking again."
                        elif status["status"] != "completed" or status["stale"] or not status["scored"]:
                            plan["error"] = "Use Analyze answers in the interview console to save a current interview score first."
                        else:
                            plan["analysis_ids"].append(status["run_id"])
                    plan["analysis_requested"] = True  # Legacy durable plan field; no analysis is enqueued.
                    if not plan["assessment_id"]:
                        request = GenerateAssessment(scoring_run_id=plan["scoring_run_id"], interview_ids=plan["interview_ids"],
                            analysis_run_ids=plan["analysis_ids"] if plan["analysis_ids"] and not plan["error"] else None)
                        report = assessments.enqueue(db, row.created_by, plan["application_id"], request)
                        if report.status == "failed":
                            report = assessments.enqueue(db, row.created_by, plan["application_id"], request.model_copy(update={"new_version": True}))
                        plan["assessment_id"] = report.id
                        row.assessment_ids = [p["assessment_id"] for p in snapshot["plans"] if p["assessment_id"]]
                        row.snapshot = copy.deepcopy(snapshot)
                        db.commit()
                    report = db.get(AssessmentRun, plan["assessment_id"])
                    if report is None: raise LookupError("The selected report was deleted")
                    if report.status == "queued":
                        # Report aggregation is deterministic and model-free. Complete
                        # it here instead of waiting for one worker tick per candidate.
                        db.commit()
                        assessments.process(report.id)
                        db.expire_all()
                        row = db.get(AssessmentComparison, row_id)
                        report = db.get(AssessmentRun, plan["assessment_id"])
                    if report.status in {"queued", "processing"}: waiting = True
                snapshot["stage"] = "calculating_scores"
                if not waiting:
                    reports = [assessments.read(db, row.created_by, p["assessment_id"]) for p in snapshot["plans"]]
                    for plan, report in zip(snapshot["plans"], reports):
                        if report["status"] == "failed" and not plan.get("error"):
                            plan["error"] = "Saved scores could not be combined. Check the sources and calculate the ranking again."
                        if plan.get("error"):
                            report["result"].setdefault("score_summary", {}).update(ready=False, interview_score=None, final_score=None, reason=plan["error"])
                    ordered, issue = rank_reports(reports)
                    snapshot.update(status="completed", stage="completed", assessments=ordered,
                        assessment_ids=[r["id"] for r in ordered], incompatibilities=[issue] if issue else [],
                        combined_ranking_available=any(r.get("final_rank") for r in ordered))
                row.snapshot = snapshot
                db.commit()
            except (ValueError, LookupError):
                db.rollback()
                row = db.get(AssessmentComparison, row_id)
                if row:
                    snapshot.update(status="failed", stage="failed", error="The saved sources changed. Calculate the ranking again.")
                    row.snapshot = snapshot
                    db.commit()
