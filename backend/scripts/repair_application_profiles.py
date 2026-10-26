"""Restore application-owned contacts from saved form data; never read Google or call an LLM."""
import argparse
import json
from sqlalchemy import select, text, func
from app.database import engine, SessionLocal
from app.models.user import User, UserRole
from app.models.candidate import Candidate, CandidateApplication, CVDocument, ApplicationSource
from app.models.job import JobPosting, JobDescription
from app.models.scoring import ScoringRun
from app.models.assessment import AssessmentRun
from app.services.application_identity import submitted_profile, bind_profile, canonical_applications
from app.services.scoring_service import ScoringService
from app.schemas.scoring import ScoreRunRequest
from app.schemas.assessment import GenerateAssessment
from app.services.assessment_service import AssessmentService
from app.agents.interview_analysis import digest


def repair(db, owner_id, *, apply=False):
    query = select(CandidateApplication).join(JobPosting).join(JobDescription).where(
        JobDescription.created_by_user_id == owner_id, CandidateApplication.source == ApplicationSource.GOOGLE_FORM).order_by(CandidateApplication.id)
    apps = list(db.scalars(query.with_for_update() if apply else query))
    originals = {a.id: digest({k:v for k,v in (a.response_data or {}).items() if k not in {"_identity_repair", "_duplicate_submission"}}) for a in apps}
    documents = list(db.scalars(select(CVDocument).where(CVDocument.application_id.in_([a.id for a in apps]))))
    file_evidence = {d.id: (d.application_id, d.sha256, d.storage_path, d.file_size_bytes) for d in documents}
    changes, skipped, planned = [], [], []
    for app in apps:
        profile = submitted_profile(app.response_data or {})
        if not profile["name"] and not profile["email"]:
            skipped.append(app.id); continue
        candidate = db.get(Candidate, app.candidate_id) if app.candidate_id else None
        shared = bool(candidate and db.scalar(select(func.count()).select_from(CandidateApplication).where(
            CandidateApplication.candidate_id == candidate.id)) > 1)
        if not candidate or shared or any(getattr(candidate,k) != v for k,v in profile.items()): planned.append(app.id)
        if apply and bind_profile(db, app, profile): changes.append(app.id)
    canonical = canonical_applications(db, apps, mark_repeats=apply)
    if apply:
        db.flush()
        assert originals == {a.id: digest({k:v for k,v in (a.response_data or {}).items() if k not in {"_identity_repair", "_duplicate_submission"}}) for a in apps}
        assert file_evidence == {d.id: (d.application_id, d.sha256, d.storage_path, d.file_size_bytes) for d in documents}
        db.commit()
    return {"source_applications": len(apps), "visible_applications": len(canonical),
        "grouped_repeat_submissions": len(apps)-len(canonical), "profile_changes_needed": planned, "repaired_application_ids": changes,
        "missing_original_identity": skipped, "job_ids": sorted({a.job_posting_id for a in apps})}


def refresh_saved_results(db, owner_id, job_ids):
    """CV arithmetic and report consolidation only. No new model work is enqueued."""
    results = []
    for job_id in job_ids:
        service = ScoringService()
        previous = db.scalar(select(ScoringRun).where(ScoringRun.job_posting_id == job_id).order_by(ScoringRun.id.desc()))
        if not previous: continue
        proposal = service.proposal(db, user_id=owner_id, job_id=job_id)
        configuration = proposal.get("approved_configuration")
        if not configuration: continue
        run = service.run(db, user_id=owner_id, job_id=job_id, data=ScoreRunRequest(configuration_id=configuration["id"]))
        results.append({"job_id": job_id, "scoring_run_id": run["id"], "ranked_applications": len(run["results"])})
    return results


def refresh_saved_reports(db, owner_id, application_ids, *, session_factory=None):
    service = AssessmentService(session_factory=session_factory or SessionLocal)
    refreshed = []
    for app_id in application_ids:
        previous = db.scalar(select(AssessmentRun).where(AssessmentRun.application_id == app_id,
            AssessmentRun.status == "completed").order_by(AssessmentRun.id.desc()))
        if not previous: continue
        selection = previous.snapshot.get("selection", {})
        request = GenerateAssessment(interview_ids=selection.get("interview_ids"), analysis_run_ids=selection.get("analysis_run_ids"))
        run = service.enqueue(db, owner_id, app_id, request)
        service.process(run.id)
        refreshed.append(run.id)
    return refreshed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with engine.connect() as guard:
        locked = False
        try:
            if engine.dialect.name == "postgresql":
                locked = bool(guard.scalar(text("SELECT pg_try_advisory_lock(681274092725)"))); guard.commit()
                if not locked: raise RuntimeError("Another profile repair is running")
            with SessionLocal() as db:
                owner = db.scalar(select(User).where(User.role == UserRole.INTERVIEWER, User.is_active.is_(True)))
                if not owner: raise RuntimeError("No active interviewer")
                result = repair(db, owner.id, apply=args.apply)
                if args.apply:
                    result["rankings"] = refresh_saved_results(db, owner.id, result["job_ids"])
                    result["refreshed_report_ids"] = refresh_saved_reports(db, owner.id, result["repaired_application_ids"])
                print(json.dumps({"applied": args.apply, **result, "deleted_applications": 0, "external_actions": 0}))
        finally:
            if locked: guard.execute(text("SELECT pg_advisory_unlock(681274092725)")); guard.commit()


if __name__ == "__main__": main()
