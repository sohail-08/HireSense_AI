"""Persisted job-wide scoring coordinator. Reads never call an AI provider."""
import copy
from datetime import datetime
from uuid import uuid4
from sqlalchemy import select
from app.database import SessionLocal
from app.agents.interview_analysis import digest, PROMPT_VERSION, RUBRIC_VERSION, PAIRING_VERSION
from app.assessments.sources import resolve_sources
from app.assessments.final_scoring import FORMULA_VERSION, POLICY, rank_reports
from app.models.assessment import AssessmentComparison, AssessmentRun
from app.models.candidate import CandidateApplication
from app.models.job import JobPosting, JobDescription
from app.models.interview_analysis import InterviewAnalysisRun
from app.schemas.assessment import GenerateAssessment
from app.schemas.interview_analysis import StartAnalysis
from app.services.assessment_service import AssessmentService, unexpired
from app.services.interview_analysis import InterviewAnalysisService


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

    def start(self, db, user_id, job_id):
        self.owned_job(db, user_id, job_id, lock=True)
        previous = self.latest(db, job_id)
        if previous and previous.snapshot["status"] == "processing":
            return self.read(db, user_id, job_id)
        ids = list(db.scalars(select(CandidateApplication.id).where(CandidateApplication.job_posting_id == job_id)
            .order_by(CandidateApplication.id)))
        if not ids: raise ValueError("No candidates have applied for this job yet.")
        sources = [resolve_sources(db, user_id, app_id, GenerateAssessment()) for app_id in ids]
        fingerprint = digest([FORMULA_VERSION, self.scoring_policy(), [source_identity(s) for s in sources]])
        existing = db.scalar(select(AssessmentComparison).where(AssessmentComparison.job_posting_id == job_id,
            AssessmentComparison.fingerprint == fingerprint))
        if existing and unexpired(existing):
            # An explicit retry after failed processing gets a new durable attempt.
            retry_sources = any(i["finalized"] and i["segments"] and (not i["analysis"] or
                needs_answer_scoring(i["analysis"]["result"], i["analysis"]["rubric_version"]))
                for s in sources for i in s["interviews"])
            failed_report = any(r.get("status") == "failed" for r in existing.snapshot.get("assessments", []))
            if existing.snapshot.get("status") != "failed" and not retry_sources and not failed_report:
                return self.present(db, user_id, existing)
        if existing:
            fingerprint = digest([fingerprint, uuid4().hex])
        expiry = [datetime.fromisoformat(s["expires_at"]) for s in sources if s["expires_at"]]
        plans = [{"application_id": s["identification"]["application_id"], "interview_ids": [i["id"] for i in s["interviews"]],
            "scoring_run_id": (s.get("cv") or {}).get("scoring_run_id"), "analysis_ids": [], "analysis_requested": False,
            "assessment_id": None} for s in sources]
        snapshot = {"kind": "final_ranking", "status": "processing", "stage": "scoring_answers", "policy": POLICY,
            "scoring_policy": self.scoring_policy(),
            "basis": "Final candidate ranking", "formula_version": FORMULA_VERSION, "plans": plans,
            "selected_cohort_application_ids": ids, "source_interview_ids": [i for p in plans for i in p["interview_ids"]],
            "assessment_ids": [], "assessments": [], "incompatibilities": [], "interview_incompatibilities": [],
            "combined_ranking_available": False, "cv_order_compatible": True, "cohort_policy": "All candidates for this job."}
        row = AssessmentComparison(job_posting_id=job_id, fingerprint=fingerprint, assessment_ids=[], snapshot=snapshot,
            created_by=user_id, expires_at=min(expiry) if expiry else None)
        db.add(row)
        db.commit()
        return self.present(db, user_id, row)

    def read(self, db, user_id, job_id):
        self.owned_job(db, user_id, job_id)
        row = self.latest(db, job_id)
        if row: return self.present(db, user_id, row)
        ids = list(db.scalars(select(CandidateApplication.id).where(CandidateApplication.job_posting_id == job_id)))
        candidates = []
        for app_id in ids:
            source = resolve_sources(db, user_id, app_id, GenerateAssessment())
            candidates.append({"application_id": app_id, "candidate_name": source["identification"]["candidate_name"],
                "cv_score": (source.get("cv") or {}).get("final_score"), "interview_score": None, "final_score": None,
                "final_rank": None, "assessment_id": None, "reason": "Calculate the final ranking to score interview answers."})
        return {"id": None, "status": "not_started", "stage": "not_started", "policy": POLICY, "candidates": candidates,
            "stale": False, "incompatibilities": []}

    def present(self, db, user_id, row):
        self.owned_job(db, user_id, row.job_posting_id)
        snapshot = row.snapshot
        current_ids = list(db.scalars(select(CandidateApplication.id).where(CandidateApplication.job_posting_id == row.job_posting_id)))
        stale = sorted(current_ids) != sorted(snapshot["selected_cohort_application_ids"]) or snapshot.get("scoring_policy") != self.scoring_policy() or snapshot.get("formula_version") != FORMULA_VERSION
        candidates = []
        saved = {r["application_id"]: r for r in snapshot.get("assessments", [])}
        service = AssessmentService(session_factory=self.factory)
        for plan in snapshot["plans"]:
            app_id = plan["application_id"]
            current = resolve_sources(db, user_id, app_id, GenerateAssessment())
            item = saved.get(app_id)
            if item and plan.get("assessment_id"):
                run = service.owned_run(db, user_id, plan["assessment_id"])
                stale = stale or source_identity(current) != source_identity(run.snapshot)
            summary = (item or {}).get("result", {}).get("score_summary", {})
            candidates.append({"application_id": app_id, "candidate_name": current["identification"]["candidate_name"],
                "cv_score": summary.get("cv_score", (current.get("cv") or {}).get("final_score")),
                "interview_score": summary.get("interview_score"), "final_score": summary.get("final_score"),
                "final_rank": (item or {}).get("final_rank"), "assessment_id": plan.get("assessment_id"),
                "reason": summary.get("reason", plan.get("error", "Interview not scored yet"))})
        candidates.sort(key=lambda c: (c["final_rank"] is None, c["final_rank"] or 0, c["application_id"]))
        return {"id": row.id, "status": snapshot["status"], "stage": snapshot["stage"], "policy": POLICY,
            "candidates": candidates, "stale": stale, "incompatibilities": snapshot.get("incompatibilities", []),
            "error": snapshot.get("error")}

    @staticmethod
    def scoring_policy():
        return {"prompt": PROMPT_VERSION, "rubric": RUBRIC_VERSION, "pairing": PAIRING_VERSION}

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
                analyses = InterviewAnalysisService(session_factory=self.factory)
                assessments = AssessmentService(session_factory=self.factory)
                waiting = False
                for plan in snapshot["plans"]:
                    if not plan["analysis_requested"]:
                        source = resolve_sources(db, row.created_by, plan["application_id"], GenerateAssessment(
                            scoring_run_id=plan["scoring_run_id"], interview_ids=plan["interview_ids"]))
                        for interview in source["interviews"]:
                            if not interview["finalized"] or not interview["segments"]: continue
                            response = analyses.read(db, row.created_by, interview["id"])
                            previous = response["run"]
                            raw = db.get(InterviewAnalysisRun, previous["id"]) if previous else None
                            retry = bool(previous and (previous["status"] in {"failed", "cancelled"} or
                                (previous["status"] == "completed" and needs_answer_scoring(raw.result, raw.snapshot.get("rubric_version")))))
                            if not previous or previous["stale"] or retry:
                                run = analyses.enqueue(db, row.created_by, interview["id"], StartAnalysis(automatic=False, reanalyze=retry))
                                plan["analysis_ids"].append(run.id)
                            else:
                                plan["analysis_ids"].append(previous["id"])
                        plan["analysis_requested"] = True
                        row.snapshot = copy.deepcopy(snapshot)
                        db.commit()
                    if any(db.get(InterviewAnalysisRun, i) is None for i in plan["analysis_ids"]):
                        raise LookupError("The selected analysis was deleted")
                    if any(db.get(InterviewAnalysisRun, i).status in {"queued", "processing"} for i in plan["analysis_ids"]):
                        waiting = True
                        continue
                    if not plan["assessment_id"]:
                        request = GenerateAssessment(scoring_run_id=plan["scoring_run_id"], interview_ids=plan["interview_ids"],
                            analysis_run_ids=plan["analysis_ids"] or None)
                        report = assessments.enqueue(db, row.created_by, plan["application_id"], request)
                        if report.status == "failed":
                            report = assessments.enqueue(db, row.created_by, plan["application_id"], request.model_copy(update={"new_version": True}))
                        plan["assessment_id"] = report.id
                        row.assessment_ids = [p["assessment_id"] for p in snapshot["plans"] if p["assessment_id"]]
                        row.snapshot = copy.deepcopy(snapshot)
                        db.commit()
                    report = db.get(AssessmentRun, plan["assessment_id"])
                    if report is None: raise LookupError("The selected report was deleted")
                    if report.status in {"queued", "processing"}: waiting = True
                snapshot["stage"] = "scoring_answers" if any(
                    db.get(InterviewAnalysisRun, i).status in {"queued", "processing"} for p in snapshot["plans"] for i in p["analysis_ids"]
                ) else "calculating_scores"
                if not waiting:
                    reports = [assessments.read(db, row.created_by, p["assessment_id"]) for p in snapshot["plans"]]
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
