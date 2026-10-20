import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.candidate import Candidate, CandidateApplication, CVDocument
from app.models.job import JobPosting
from app.models.scoring import CandidateScore, ScoringConfiguration, ScoringRequestKey, ScoringRun
from app.models.screening import RequirementMatch, ScreeningRun
from app.schemas.scoring import ScoreRunRequest, ScoringApproval
from app.scoring.workflow import CandidateScoringWorkflow
from app.services.scoring_calculation import CATEGORIES, DEFAULT_CATEGORY_WEIGHTS, FORMULA_VERSION, SNAPSHOT_VERSION, STATUS_VALUES, display_score
from app.services.screening_service import ScreeningService


class ScoringConflict(ValueError):
    pass


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


class ScoringService:
    @staticmethod
    def proposal(db: Session, *, user_id: int, job_id: int) -> dict:
        _, job, profile = ScreeningService._owned_context(db, interviewer_user_id=user_id, job_posting_id=job_id)
        snapshot, version = ScreeningService._requirement_snapshot(profile)
        requirements = []
        for item in snapshot["requirements"]:
            category = {"required_skill": "technical", "preferred_skill": "technical", "experience": "experience", "qualification": "qualification"}.get(item["category"])
            requirements.append({
                "requirement_id": item["key"], "name": item["name"], "category": category,
                "source_category": item["category"], "classification": "preferred" if item["category"] == "preferred_skill" else "required",
                "weight": str(item["weight"]), "evaluation_criterion": item.get("details") or item["name"],
                "requirement_version": version,
            })
        return {"job_posting_id": job_id, "job_title": job.title, "requirement_profile_id": profile.id,
                "requirement_version": version, "category_weights": DEFAULT_CATEGORY_WEIGHTS,
                "requirements": requirements, "formula_version": FORMULA_VERSION,
                "status_values": STATUS_VALUES, "approved_configuration": ScoringService.latest_configuration(db, job_id, version)}

    @staticmethod
    def latest_configuration(db, job_id, version=None):
        query = select(ScoringConfiguration).where(ScoringConfiguration.job_posting_id == job_id)
        if version:
            query = query.where(ScoringConfiguration.requirement_version == version)
        configuration = db.scalar(query.order_by(ScoringConfiguration.approved_at.desc(), ScoringConfiguration.id.desc()))
        return ScoringService.configuration_response(configuration) if configuration else None

    @staticmethod
    def configuration_response(configuration):
        return {"id": configuration.id, "approved_at": configuration.approved_at, "approved_by_user_id": configuration.approved_by_user_id,
                "snapshot": configuration.snapshot}

    def approve(self, db, *, user_id: int, job_id: int, data: ScoringApproval):
        proposal = self.proposal(db, user_id=user_id, job_id=job_id)
        db.scalar(select(JobPosting.id).where(JobPosting.id == job_id).with_for_update())
        if data.requirement_version != proposal["requirement_version"]:
            raise ScoringConflict("Requirements changed; reload and approve the current version")
        if set(data.category_weights) != set(CATEGORIES):
            raise ValueError("Provide all three category weights")
        weights = data.category_weights
        if any(not value.is_finite() or value < 0 or value > 100 for value in weights.values()) or sum(weights.values()) != 100:
            raise ValueError("Category weights must be non-negative and total exactly 100%")
        if any(value.normalize().as_tuple().exponent < -6 for value in weights.values()):
            raise ValueError("Category weights support at most six decimal places")
        originals = {item["requirement_id"]: item for item in proposal["requirements"]}
        if len(data.requirements) != len(originals) or {item.requirement_id for item in data.requirements} != set(originals):
            raise ValueError("Approve exactly one weight and category for every requirement")
        requirements = []
        for item in sorted(data.requirements, key=lambda item: item.requirement_id):
            original = originals[item.requirement_id]
            if item.category is None and original["source_category"] != "selection_criterion":
                raise ValueError("Only unmapped selection criteria may remain evidence-only")
            if item.classification != original["classification"]:
                raise ValueError("Required/preferred classification must match the confirmed profile")
            if original["category"] and item.category != original["category"]:
                raise ValueError("Only selection criteria require manual category assignment")
            requirements.append({**original, "category": item.category, "weight": format(item.weight.normalize(), "f"),
                                 "score_included": item.category is not None})
        for category in CATEGORIES:
            total = sum((Decimal(item["weight"]) for item in requirements if item["category"] == category), Decimal(0))
            if total == 0 and weights[category] > 0:
                raise ValueError(f"{category} has no positive requirement weights; set its category weight to zero and redistribute the weight")
        payload = {"requirement_version": proposal["requirement_version"], "requirement_profile_id": proposal["requirement_profile_id"],
                   "job_title": proposal["job_title"], "category_weights": {key: format(weights[key].normalize(), "f") for key in CATEGORIES},
                   "requirements": requirements, "formula_version": FORMULA_VERSION, "status_values": STATUS_VALUES}
        digest = fingerprint(payload)
        existing = db.scalar(select(ScoringConfiguration).where(ScoringConfiguration.job_posting_id == job_id, ScoringConfiguration.input_hash == digest))
        if existing:
            # Re-approving an earlier weight set makes it active without changing
            # any configuration snapshot or previously calculated run.
            existing.approved_at = datetime.now(timezone.utc)
            db.commit()
            return self.configuration_response(existing)
        configuration = ScoringConfiguration(job_posting_id=job_id, requirement_version=proposal["requirement_version"],
                                             input_hash=digest, snapshot=payload, approved_by_user_id=user_id)
        db.add(configuration)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            configuration = db.scalar(select(ScoringConfiguration).where(ScoringConfiguration.job_posting_id == job_id, ScoringConfiguration.input_hash == digest))
            if configuration is None:
                raise
        return self.configuration_response(configuration)

    def run(self, db, *, user_id: int, job_id: int, data: ScoreRunRequest):
        # Serialize calculations for a posting in PostgreSQL; unique constraints
        # remain the final duplicate guard. No external side effects occur here.
        ScreeningService._owned_context(db, interviewer_user_id=user_id, job_posting_id=job_id)
        db.scalar(select(JobPosting.id).where(JobPosting.id == job_id).with_for_update())
        ids = sorted(set(data.application_ids)) if data.application_ids is not None else None
        if ids == []:
            raise ValueError("Select at least one application")
        request_hash = fingerprint({"configuration_id": data.configuration_id, "application_ids": ids})
        if data.idempotency_key:
            previous = db.scalar(select(ScoringRequestKey).where(ScoringRequestKey.job_posting_id == job_id, ScoringRequestKey.key == data.idempotency_key))
            if previous:
                if previous.request_hash != request_hash:
                    raise ScoringConflict("This idempotency key was used for a different scoring request")
                return self.detail(db, user_id=user_id, run_id=previous.scoring_run_id)
        configuration = db.get(ScoringConfiguration, data.configuration_id)
        proposal = self.proposal(db, user_id=user_id, job_id=job_id)
        if not configuration or configuration.job_posting_id != job_id:
            raise LookupError("Approved scoring configuration not found")
        if configuration.requirement_version != proposal["requirement_version"]:
            raise ScoringConflict("The approved weights belong to an older requirement version")
        applications = self._inputs(db, job_id, configuration.requirement_version, ids)
        unavailable = [a for a in applications if a["screening_status"] != "completed" or not a["source_blocks"]]
        if unavailable and ids is not None:
            raise ScoringConflict("Some selected CVs have not finished screening. Retry failed screening before calculating their scores.")
        applications = [a for a in applications if a not in unavailable]
        if not applications:
            raise ValueError("No completed CV screenings are available to score. Finish screening first.")
        payload = {"snapshot_version": SNAPSHOT_VERSION, "job_posting_id": job_id,
                   "configuration": configuration.snapshot, "applications": applications,
                   "application_ids": [app["application_id"] for app in applications], "formula_version": FORMULA_VERSION,
                   "status_values": STATUS_VALUES}
        digest = fingerprint(payload)
        existing = db.scalar(select(ScoringRun).where(ScoringRun.job_posting_id == job_id, ScoringRun.input_hash == digest))
        if existing:
            self._save_key(db, data.idempotency_key, request_hash, existing)
            db.commit()
            return self.detail(db, user_id=user_id, run_id=existing.id)

        def persist(results):
            run = ScoringRun(job_posting_id=job_id, configuration_id=configuration.id, requirement_version=configuration.requirement_version,
                             formula_version=FORMULA_VERSION, input_hash=digest, snapshot=payload, created_by_user_id=user_id,
                             status="completed")
            db.add(run)
            db.flush()
            run.snapshot = {**payload, "calculated_at": run.created_at.isoformat()}
            for result in results:
                breakdown = result["breakdown"]
                scores = {category: breakdown["categories"][category]["score"] for category in CATEGORIES}
                db.add(CandidateScore(scoring_run_id=run.id, application_id=result["application_id"], screening_run_id=result["screening_run_id"],
                    technical_score=Decimal(scores["technical"]) if scores["technical"] is not None else None,
                    experience_score=Decimal(scores["experience"]) if scores["experience"] is not None else None,
                    qualification_score=Decimal(scores["qualification"]) if scores["qualification"] is not None else None,
                    final_score=Decimal(breakdown["final_score"]), rank=result["rank"], review_state=breakdown["review_state"],
                    breakdown=breakdown, written_justification=result["written_justification"]))
            self._save_key(db, data.idempotency_key, request_hash, run)
            db.commit()
            return run.id
        try:
            result = CandidateScoringWorkflow(persist).invoke(configuration.snapshot, applications)
        except IntegrityError:
            db.rollback()
            existing = db.scalar(select(ScoringRun).where(ScoringRun.job_posting_id == job_id, ScoringRun.input_hash == digest))
            if existing is None:
                raise
            self._save_key(db, data.idempotency_key, request_hash, existing)
            db.commit()
            return self.detail(db, user_id=user_id, run_id=existing.id)
        return self.detail(db, user_id=user_id, run_id=result["run_id"])

    @staticmethod
    def _save_key(db, key, request_hash, run):
        if key:
            db.add(ScoringRequestKey(job_posting_id=run.job_posting_id, key=key, request_hash=request_hash, scoring_run_id=run.id))

    @staticmethod
    def _inputs(db, job_id, version, ids):
        query = select(CandidateApplication).where(CandidateApplication.job_posting_id == job_id)
        if ids is not None:
            query = query.where(CandidateApplication.id.in_(ids))
        applications = list(db.scalars(query.order_by(CandidateApplication.id)))
        if ids is not None and len(applications) != len(ids):
            raise LookupError("Selected applications must belong to this job")
        inputs = []
        for app in applications:
            document = db.scalar(select(CVDocument).where(CVDocument.application_id == app.id).order_by(CVDocument.created_at.desc(), CVDocument.id.desc()))
            run = db.scalar(select(ScreeningRun).where(ScreeningRun.application_id == app.id,
                ScreeningRun.requirement_snapshot_hash == version, ScreeningRun.cv_sha256 == (document.sha256 if document else ""))
                .order_by(ScreeningRun.id.desc()))
            candidate = db.get(Candidate, app.candidate_id) if app.candidate_id else None
            blocks = (document.extraction_data or {}).get("source_blocks", []) if document else []
            matches = list(db.scalars(select(RequirementMatch).where(RequirementMatch.screening_run_id == run.id).order_by(RequirementMatch.requirement_key, RequirementMatch.id))) if run else []
            flags = list(run.review_flags or []) if run else []
            if document:
                flags.extend(document.extraction_warnings or [])
            inputs.append({"application_id": app.id, "candidate_name": candidate.name if candidate and candidate.name else f"Application #{app.id}",
                "screening_run_id": run.id if run else None, "screening_status": run.status.value if run else "pending",
                "error_message": run.error_message if run else "Screen this application's current CV against the current requirements first.",
                "cv_sha256": document.sha256 if document else "", "screening_prompt_version": run.prompt_version if run else None,
                "screening_formula_version": run.calculation_version if run else None, "screening_model": run.model_name if run else None,
                "source_blocks": sorted(blocks, key=lambda block: block["id"]), "review_flags": sorted(set(flags)),
                "matches": [{"id": match.id, "requirement_key": match.requirement_key, "status": match.status.value,
                             "evidence": match.evidence, "evidence_gaps": match.evidence_gaps, "review_flags": match.review_flags} for match in matches]})
        return inputs

    def list_runs(self, db, *, user_id, job_id):
        ScreeningService._owned_context(db, interviewer_user_id=user_id, job_posting_id=job_id)
        return [self.summary(run) for run in db.scalars(select(ScoringRun).where(ScoringRun.job_posting_id == job_id).order_by(ScoringRun.id.desc()))]

    @staticmethod
    def summary(run):
        return {"id": run.id, "job_posting_id": run.job_posting_id, "configuration_id": run.configuration_id,
                "requirement_version": run.requirement_version, "formula_version": run.formula_version, "status": run.status,
                "created_at": run.created_at, "input_hash": run.input_hash}

    def detail(self, db, *, user_id, run_id):
        run = db.get(ScoringRun, run_id)
        if not run:
            raise LookupError("Scoring run not found")
        # Historical reads remain possible even after the approved requirements change.
        from app.models.job import JobDescription
        owned = db.scalar(select(JobPosting.id).join(JobDescription).where(JobPosting.id == run.job_posting_id, JobDescription.created_by_user_id == user_id))
        if owned is None:
            raise LookupError("Scoring run not found")
        names = {app["application_id"]: app["candidate_name"] for app in run.snapshot["applications"]}
        results = []
        for score in db.scalars(select(CandidateScore).where(CandidateScore.scoring_run_id == run.id).order_by(CandidateScore.rank.asc().nulls_last(), CandidateScore.application_id)):
            breakdown = score.breakdown
            results.append({"id": score.id, "application_id": score.application_id, "candidate_name": names[score.application_id],
                            "screening_run_id": score.screening_run_id, "rank": score.rank, "review_state": score.review_state,
                            "final_score": breakdown["final_score"], "display_score": display_score(breakdown["final_score"]),
                            "breakdown": breakdown, "written_justification": score.written_justification})
        return {**self.summary(run), "configuration": run.snapshot["configuration"], "snapshot_version": run.snapshot["snapshot_version"],
                "application_ids": sorted(names), "results": results}
