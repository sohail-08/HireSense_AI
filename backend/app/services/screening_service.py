import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.candidate import (
    ApplicationStatus,
    Candidate,
    CandidateApplication,
    CVDocument,
    CVProcessingStatus,
)
from app.models.job import (
    JobDescription,
    JobDescriptionStatus,
    JobPosting,
    RequirementProfile,
    RequirementProfileStatus,
)
from app.models.screening import (
    RankingDisposition,
    RankingEntry,
    RankingSnapshot,
    RequirementMatch,
    RequirementMatchStatus,
    ScreeningBatch,
    ScreeningBatchItem,
    ScreeningBatchStatus,
    ScreeningRun,
    ScreeningRunStatus,
)
from app.screening.ai import GeminiScreeningAI, ScreeningAI
from app.screening.parsing import CVParser, CVReviewRequired
from app.screening.workflow import ScreeningWorkflow


PROMPT_VERSION = "three-outcome-v2"
CALCULATION_VERSION = "three-outcome-coverage-v2"
STATUS_FACTORS = {
    RequirementMatchStatus.MET: 1.0,
    RequirementMatchStatus.PARTIALLY_MET: 0.5,
    RequirementMatchStatus.UNMET: 0.0,
    RequirementMatchStatus.UNABLE_TO_DETERMINE: 0.0,
}


class ScreeningService:
    def __init__(
        self,
        settings: Settings,
        *,
        ai: ScreeningAI | None = None,
        parser: CVParser | None = None,
    ):
        self.settings = settings
        self.ai = ai or GeminiScreeningAI()
        self.parser = parser or CVParser(settings)

    def create_batch(
        self,
        db: Session,
        *,
        interviewer_user_id: int,
        job_posting_id: int,
        application_ids: list[int] | None,
    ) -> ScreeningBatch:
        _, _, profile = self._owned_context(
            db,
            interviewer_user_id=interviewer_user_id,
            job_posting_id=job_posting_id,
        )
        _, snapshot_hash = self._requirement_snapshot(profile)
        if application_ids == []:
            raise ValueError("Select at least one application to screen")
        query = select(CandidateApplication).where(
            CandidateApplication.job_posting_id == job_posting_id
        )
        if application_ids:
            unique_ids = list(dict.fromkeys(application_ids))
            query = query.where(CandidateApplication.id.in_(unique_ids))
        applications = list(db.scalars(query.order_by(CandidateApplication.id)))
        if application_ids and len(applications) != len(set(application_ids)):
            raise LookupError(
                "One or more selected applications do not belong to this job posting"
            )
        if not applications:
            raise ValueError("This job posting has no applications to screen")
        if len(applications) > self.settings.screening_batch_max_applications:
            raise ValueError(
                "The batch exceeds the configured limit of "
                f"{self.settings.screening_batch_max_applications} applications"
            )

        if application_ids is None:
            applications = [
                application
                for application in applications
                if not self._compatible_run(
                    db,
                    application_id=application.id,
                    cv_sha256=self._latest_cv_sha(db, application.id),
                    requirement_snapshot_hash=snapshot_hash,
                )
            ]
            if not applications:
                raise ValueError(
                    "All applications for this job already have current screening results"
                )

        batch = ScreeningBatch(
            job_posting_id=job_posting_id,
            created_by_user_id=interviewer_user_id,
            status=ScreeningBatchStatus.QUEUED,
            application_ids=[application.id for application in applications],
            total_applications=len(applications),
        )
        db.add(batch)
        db.flush()
        for application in applications:
            db.add(
                ScreeningBatchItem(
                    batch_id=batch.id,
                    application_id=application.id,
                    status=ScreeningRunStatus.QUEUED,
                )
            )
        db.commit()
        db.refresh(batch)
        return batch

    def list_jobs(
        self,
        db: Session,
        *,
        interviewer_user_id: int,
    ) -> list[dict[str, Any]]:
        rows = db.execute(
            select(JobPosting, JobDescription)
            .join(JobDescription, JobDescription.id == JobPosting.job_description_id)
            .where(JobDescription.created_by_user_id == interviewer_user_id)
            .order_by(JobPosting.created_at.desc(), JobPosting.id.desc())
        ).all()
        result: list[dict[str, Any]] = []
        for posting, job in rows:
            applications = list(
                db.scalars(
                    select(CandidateApplication).where(
                        CandidateApplication.job_posting_id == posting.id
                    )
                )
            )
            try:
                profile = db.get(RequirementProfile, job.requirement_profile_id)
                _, snapshot_hash = (
                    self._requirement_snapshot(profile)
                    if profile is not None
                    else ({}, "")
                )
            except ValueError:
                snapshot_hash = ""
            pending = 0
            for application in applications:
                if not self._compatible_run(
                    db,
                    application_id=application.id,
                    cv_sha256=self._latest_cv_sha(db, application.id),
                    requirement_snapshot_hash=snapshot_hash,
                ):
                    pending += 1
            result.append(
                {
                    "id": posting.id,
                    "title": job.title,
                    "posting_status": posting.status.value,
                    "application_count": len(applications),
                    "pending_count": pending,
                }
            )
        return result

    def dashboard(
        self,
        db: Session,
        *,
        interviewer_user_id: int,
        job_posting_id: int,
    ) -> dict[str, Any]:
        _, job, profile = self._owned_context(
            db,
            interviewer_user_id=interviewer_user_id,
            job_posting_id=job_posting_id,
        )
        _, snapshot_hash = self._requirement_snapshot(profile)
        applications = list(
            db.scalars(
                select(CandidateApplication)
                .where(CandidateApplication.job_posting_id == job_posting_id)
                .order_by(CandidateApplication.submitted_at.desc())
            )
        )
        application_items: list[dict[str, Any]] = []
        for application in applications:
            candidate = db.get(Candidate, application.candidate_id)
            document = db.scalar(
                select(CVDocument)
                .where(CVDocument.application_id == application.id)
                .order_by(CVDocument.created_at.desc(), CVDocument.id.desc())
            )
            run = db.scalar(
                select(ScreeningRun)
                .where(
                    ScreeningRun.application_id == application.id,
                    ScreeningRun.requirement_snapshot_hash == snapshot_hash,
                )
                .order_by(ScreeningRun.created_at.desc(), ScreeningRun.id.desc())
            )
            same_document = bool(
                run
                and (
                    (document is not None and run.cv_sha256 == document.sha256)
                    or (document is None and not run.cv_sha256)
                )
            )
            is_current = bool(
                run
                and same_document
                and run.prompt_version == PROMPT_VERSION
                and run.calculation_version == CALCULATION_VERSION
            )
            application_items.append(
                {
                    "id": application.id,
                    "candidate_name": (
                        candidate.name if candidate and candidate.name else f"Candidate #{application.id}"
                    ),
                    "candidate_email": candidate.email if candidate else None,
                    "submitted_at": application.submitted_at,
                    "cv_filename": document.original_filename if document else None,
                    "screening_status": run.status.value if is_current else "pending",
                    "screening_run_id": run.id if is_current else None,
                    "requirement_coverage": (
                        run.requirement_coverage if is_current else None
                    ),
                    "error_message": run.error_message if is_current else None,
                }
            )
        return {
            "job_posting_id": job_posting_id,
            "job_title": job.title,
            "requirement_profile_id": profile.id,
            "applications": application_items,
            "ranking": self._ranking_response(
                db,
                job_posting_id=job_posting_id,
                requirement_snapshot_hash=snapshot_hash,
            ),
        }

    @staticmethod
    def get_batch(
        db: Session,
        *,
        interviewer_user_id: int,
        batch_id: int,
    ) -> dict[str, Any]:
        batch = db.scalar(
            select(ScreeningBatch).where(
                ScreeningBatch.id == batch_id,
                ScreeningBatch.created_by_user_id == interviewer_user_id,
            )
        )
        if batch is None:
            raise LookupError("Screening batch not found")
        items = list(
            db.scalars(
                select(ScreeningBatchItem)
                .where(ScreeningBatchItem.batch_id == batch.id)
                .order_by(ScreeningBatchItem.id)
            )
        )
        return {
            "id": batch.id,
            "job_posting_id": batch.job_posting_id,
            "status": batch.status.value,
            "application_ids": batch.application_ids,
            "total_applications": batch.total_applications,
            "processed_applications": batch.processed_applications,
            "successful_applications": batch.successful_applications,
            "review_applications": batch.review_applications,
            "failed_applications": batch.failed_applications,
            "error_message": batch.error_message,
            "started_at": batch.started_at,
            "completed_at": batch.completed_at,
            "created_at": batch.created_at,
            "items": [
                {
                    "id": item.id,
                    "application_id": item.application_id,
                    "screening_run_id": item.screening_run_id,
                    "status": item.status.value,
                    "error_message": item.error_message,
                }
                for item in items
            ],
        }

    @staticmethod
    def run_detail(
        db: Session,
        *,
        interviewer_user_id: int,
        run_id: int,
    ) -> dict[str, Any]:
        run = db.scalar(
            select(ScreeningRun)
            .join(JobPosting, JobPosting.id == ScreeningRun.job_posting_id)
            .join(JobDescription, JobDescription.id == JobPosting.job_description_id)
            .where(
                ScreeningRun.id == run_id,
                JobDescription.created_by_user_id == interviewer_user_id,
            )
        )
        if run is None:
            raise LookupError("Screening result not found")
        document = db.get(CVDocument, run.cv_document_id) if run.cv_document_id else None
        matches = list(
            db.scalars(
                select(RequirementMatch)
                .where(RequirementMatch.screening_run_id == run.id)
                .order_by(RequirementMatch.id)
            )
        )
        extraction_data = document.extraction_data if document else {}
        return {
            "id": run.id,
            "application_id": run.application_id,
            "status": run.status.value,
            "requirement_coverage": run.requirement_coverage,
            "extracted_profile": run.extracted_profile,
            "source_blocks": (extraction_data or {}).get("source_blocks", []),
            "suitability_summary": run.suitability_summary,
            "strengths": run.strengths,
            "gaps": run.gaps,
            "points_to_verify": run.points_to_verify,
            "review_flags": run.review_flags,
            "error_message": run.error_message,
            "model_name": run.model_name,
            "prompt_version": run.prompt_version,
            "calculation_version": run.calculation_version,
            "requirement_snapshot": run.requirement_snapshot,
            "matches": [
                {
                    "requirement_key": match.requirement_key,
                    "category": match.category,
                    "name": match.name,
                    "details": match.details,
                    "weight": match.weight,
                    "status": match.status.value,
                    "explanation": match.explanation,
                    "evidence": match.evidence,
                    "evidence_gaps": match.evidence_gaps,
                    "review_flags": match.review_flags,
                }
                for match in matches
            ],
        }

    def process_batch(self, db: Session, *, batch_id: int) -> None:
        batch = db.get(ScreeningBatch, batch_id)
        if batch is None:
            return
        batch.status = ScreeningBatchStatus.PROCESSING
        batch.started_at = datetime.now(timezone.utc)
        db.commit()

        try:
            _, _, profile = self._owned_context(
                db,
                interviewer_user_id=batch.created_by_user_id,
                job_posting_id=batch.job_posting_id,
            )
            snapshot, snapshot_hash = self._requirement_snapshot(profile)
            items = list(
                db.scalars(
                    select(ScreeningBatchItem)
                    .where(ScreeningBatchItem.batch_id == batch.id)
                    .order_by(ScreeningBatchItem.id)
                )
            )
            for item in items:
                self._process_item(
                    db,
                    batch=batch,
                    item=item,
                    profile=profile,
                    snapshot=snapshot,
                    snapshot_hash=snapshot_hash,
                )
            self._create_ranking_snapshot(
                db,
                posting_id=batch.job_posting_id,
                interviewer_user_id=batch.created_by_user_id,
                requirement_snapshot_hash=snapshot_hash,
            )
            # Scoring follows persisted, evidence-validated matches. Only an
            # explicitly approved configuration for this requirement version
            # can trigger the deterministic workflow; no defaults are approved here.
            from app.services.scoring_service import ScoringService
            from app.schemas.scoring import ScoreRunRequest
            configuration = ScoringService.latest_configuration(db, batch.job_posting_id, snapshot_hash)
            if configuration:
                ScoringService().run(
                    db, user_id=batch.created_by_user_id, job_id=batch.job_posting_id,
                    data=ScoreRunRequest(configuration_id=configuration["id"]),
                )
            batch = db.get(ScreeningBatch, batch_id)
            batch.status = (
                ScreeningBatchStatus.COMPLETED_WITH_ERRORS
                if batch.failed_applications or batch.review_applications
                else ScreeningBatchStatus.COMPLETED
            )
            batch.completed_at = datetime.now(timezone.utc)
            db.commit()
        except Exception as exc:
            db.rollback()
            batch = db.get(ScreeningBatch, batch_id)
            if batch is not None:
                batch.status = ScreeningBatchStatus.FAILED
                batch.error_message = str(exc)[:2000]
                batch.completed_at = datetime.now(timezone.utc)
                db.commit()

    def _process_item(
        self,
        db: Session,
        *,
        batch: ScreeningBatch,
        item: ScreeningBatchItem,
        profile: RequirementProfile,
        snapshot: dict[str, Any],
        snapshot_hash: str,
    ) -> None:
        item.status = ScreeningRunStatus.PROCESSING
        db.commit()
        document = db.scalar(
            select(CVDocument)
            .where(CVDocument.application_id == item.application_id)
            .order_by(CVDocument.created_at.desc(), CVDocument.id.desc())
        )
        compatible = self._compatible_run(
            db,
            application_id=item.application_id,
            cv_sha256=document.sha256 if document else "",
            requirement_snapshot_hash=snapshot_hash,
        )
        if compatible is not None:
            item.screening_run_id = compatible.id
            item.status = ScreeningRunStatus.COMPLETED
            self._advance_batch(batch, ScreeningRunStatus.COMPLETED)
            db.commit()
            return

        run = ScreeningRun(
            application_id=item.application_id,
            cv_document_id=document.id if document else None,
            job_posting_id=batch.job_posting_id,
            requirement_profile_id=profile.id,
            status=ScreeningRunStatus.PROCESSING,
            cv_sha256=document.sha256 if document else "",
            requirement_snapshot_hash=snapshot_hash,
            requirement_snapshot=snapshot,
            model_name=self.ai.model_name,
            prompt_version=PROMPT_VERSION,
            calculation_version=CALCULATION_VERSION,
            started_at=datetime.now(timezone.utc),
        )
        db.add(run)
        db.flush()
        item.screening_run_id = run.id
        db.commit()

        application = db.get(CandidateApplication, item.application_id)
        try:
            if document is None:
                raise CVReviewRequired(
                    "No stored CV is associated with this application"
                )
            document.status = CVProcessingStatus.PROCESSING
            if application is not None:
                application.status = ApplicationStatus.SCREENING
            db.commit()
            ScreeningWorkflow(
                db=db,
                parser=self.parser,
                ai=self.ai,
                validate_result=self._validate_assessment,
                persist_result=lambda **values: self._persist_result(db, **values),
            ).invoke(run_id=run.id, document_id=document.id)
            item = db.get(ScreeningBatchItem, item.id)
            item.status = ScreeningRunStatus.COMPLETED
            application = db.get(CandidateApplication, item.application_id)
            if application is not None:
                application.status = ApplicationStatus.REVIEWED
        except CVReviewRequired as exc:
            db.rollback()
            run = db.get(ScreeningRun, run.id)
            item = db.get(ScreeningBatchItem, item.id)
            application = db.get(CandidateApplication, item.application_id)
            run.status = ScreeningRunStatus.FAILED
            run.error_message = str(exc)
            run.review_flags = [str(exc)]
            run.completed_at = datetime.now(timezone.utc)
            item.status = ScreeningRunStatus.FAILED
            item.error_message = str(exc)
            if document is not None:
                saved_document = db.get(CVDocument, document.id)
                saved_document.status = CVProcessingStatus.FAILED
                saved_document.error_message = str(exc)
            if application is not None:
                application.status = ApplicationStatus.RECEIVED
        except Exception as exc:
            db.rollback()
            run = db.get(ScreeningRun, run.id)
            item = db.get(ScreeningBatchItem, item.id)
            application = db.get(CandidateApplication, item.application_id)
            safe_error = str(exc)[:2000] or "Screening failed"
            run.status = ScreeningRunStatus.FAILED
            run.error_message = safe_error
            run.completed_at = datetime.now(timezone.utc)
            item.status = ScreeningRunStatus.FAILED
            item.error_message = safe_error
            if document is not None:
                saved_document = db.get(CVDocument, document.id)
                saved_document.status = CVProcessingStatus.FAILED
                saved_document.error_message = safe_error
            if application is not None:
                application.status = ApplicationStatus.RECEIVED

        batch = db.get(ScreeningBatch, batch.id)
        self._advance_batch(batch, item.status)
        db.commit()

    @staticmethod
    def _advance_batch(
        batch: ScreeningBatch,
        status: ScreeningRunStatus,
    ) -> None:
        batch.processed_applications += 1
        if status is ScreeningRunStatus.COMPLETED:
            batch.successful_applications += 1
        elif status is ScreeningRunStatus.REVIEW_REQUIRED:
            batch.review_applications += 1
        else:
            batch.failed_applications += 1

    def _persist_result(
        self,
        db: Session,
        *,
        run_id: int,
        text: str,
        blocks: list[dict[str, str]],
        parser_metadata: dict[str, Any],
        profile: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        run = db.get(ScreeningRun, run_id)
        if run is None:
            raise ValueError("The screening run no longer exists")
        document = db.get(CVDocument, run.cv_document_id)
        if document is None:
            raise ValueError("The CV record no longer exists")
        document.extracted_text = text
        document.extraction_data = {
            "source_blocks": blocks,
            "parser": parser_metadata,
            "structured_profile": profile,
        }
        document.extraction_warnings = parser_metadata.get("warnings", [])
        document.status = CVProcessingStatus.PROCESSED
        document.error_message = None
        document.processed_at = datetime.now(timezone.utc)

        for match in result["matches"]:
            db.add(
                RequirementMatch(
                    screening_run_id=run.id,
                    requirement_key=match["requirement_key"],
                    category=match["category"],
                    name=match["name"],
                    details=match.get("details"),
                    weight=match["weight"],
                    status=RequirementMatchStatus(match["status"]),
                    explanation=match["explanation"],
                    evidence=match["evidence"],
                    evidence_gaps=match["evidence_gaps"],
                    review_flags=match["review_flags"],
                )
            )
        run.extracted_profile = profile
        run.suitability_summary = result["suitability_summary"]
        run.strengths = result["strengths"]
        run.gaps = result["gaps"]
        run.points_to_verify = result["points_to_verify"]
        run.requirement_coverage = result["requirement_coverage"]
        run.met_count = result["counts"]["met"]
        run.partially_met_count = result["counts"]["partially_met"]
        run.unmet_count = result["counts"]["unmet"]
        run.uncertain_count = 0
        run.review_flags = result["review_flags"]
        run.status = ScreeningRunStatus.COMPLETED
        run.completed_at = datetime.now(timezone.utc)
        db.flush()

    @staticmethod
    def _validate_assessment(
        *,
        requirements: list[dict[str, Any]],
        blocks: list[dict[str, str]],
        assessment: dict[str, Any],
        evidence_validation: dict[str, Any],
    ) -> dict[str, Any]:
        block_map = {block["id"]: block for block in blocks}
        raw_by_key: dict[str, dict[str, Any]] = {}
        global_flags: list[str] = []
        for match in assessment.get("matches", []):
            key = match.get("requirement_key")
            if key in raw_by_key:
                global_flags.append(f"Duplicate AI result for {key} was ignored")
                continue
            raw_by_key[key] = match
        validation_by_key = {
            item.get("requirement_key"): item
            for item in evidence_validation.get("validations", [])
        }

        validated: list[dict[str, Any]] = []
        total_weight = 0.0
        contribution = 0.0
        counts = {status.value: 0 for status in (RequirementMatchStatus.MET, RequirementMatchStatus.PARTIALLY_MET, RequirementMatchStatus.UNMET)}
        for requirement in requirements:
            total_weight += requirement["weight"]
            raw = raw_by_key.get(requirement["key"])
            flags: list[str] = []
            if raw is None:
                status = RequirementMatchStatus.UNABLE_TO_DETERMINE
                explanation = "The model did not return an assessment for this requirement."
                evidence = []
                gaps = ["A complete assessment was not produced"]
                flags.append("missing_model_assessment")
            else:
                status = RequirementMatchStatus(raw["status"])
                explanation = raw.get("explanation", "").strip()
                gaps = list(raw.get("evidence_gaps", []))
                evidence = []
                for item in raw.get("evidence", []):
                    block = block_map.get(item.get("block_id"))
                    quote = item.get("quote", "").strip()
                    if block is None or not quote or quote not in block["text"]:
                        flags.append("invalid_or_unverifiable_quote")
                        continue
                    evidence.append(
                        {
                            "block_id": block["id"],
                            "locator": block["locator"],
                            "quote": quote,
                        }
                    )
                if status in {
                    RequirementMatchStatus.MET,
                    RequirementMatchStatus.PARTIALLY_MET,
                } and not evidence:
                    status = RequirementMatchStatus.UNABLE_TO_DETERMINE
                    gaps.append("No verifiable supporting quotation was returned")
                    flags.append("unsupported_positive_assessment")
                audit = validation_by_key.get(requirement["key"])
                if audit is None:
                    status = RequirementMatchStatus.UNABLE_TO_DETERMINE
                    gaps.append("Independent evidence validation was not returned")
                    flags.append("missing_evidence_validation")
                elif not audit.get("supports_conclusion"):
                    status = RequirementMatchStatus.UNABLE_TO_DETERMINE
                    gaps.append(
                        audit.get("reason")
                        or "Independent review did not support the conclusion"
                    )
                    flags.append("evidence_does_not_support_conclusion")
            if status is RequirementMatchStatus.UNABLE_TO_DETERMINE:
                status = RequirementMatchStatus.UNMET
                explanation = "Unmet: sufficient validated CV evidence was not found."
            counts[status.value] += 1
            contribution += STATUS_FACTORS[status] * requirement["weight"]
            validated.append(
                {
                    "requirement_key": requirement["key"],
                    "category": requirement["category"],
                    "name": requirement["name"],
                    "details": requirement.get("details"),
                    "weight": requirement["weight"],
                    "status": status.value,
                    "explanation": explanation,
                    "evidence": evidence,
                    "evidence_gaps": gaps,
                    "review_flags": flags,
                }
            )
            global_flags.extend(
                f"{requirement['key']}: {flag}" for flag in flags
            )
        if total_weight <= 0:
            raise ValueError("Approved requirement weights must total more than zero")

        status_by_key = {
            match["requirement_key"]: match["status"] for match in validated
        }

        def summary_points(name: str, allowed: set[str]) -> list[dict[str, str]]:
            points: list[dict[str, str]] = []
            for point in assessment.get(name, []):
                key = point.get("requirement_key")
                text = point.get("text", "").strip()
                if key in status_by_key and status_by_key[key] in allowed and text:
                    points.append({"requirement_key": key, "text": text})
                else:
                    global_flags.append(f"Unsupported {name} summary point was removed")
            return points

        strengths = summary_points("strengths", {"met", "partially_met"})
        gaps = summary_points("gaps", {"unmet", "partially_met"})
        points_to_verify = []
        summary_sections = []
        if strengths:
            summary_sections.append(
                "Evidence-supported strengths: "
                + "; ".join(point["text"] for point in strengths)
            )
        if gaps:
            summary_sections.append(
                "Evidence gaps: " + "; ".join(point["text"] for point in gaps)
            )
        if points_to_verify:
            summary_sections.append(
                "Verify: "
                + "; ".join(point["text"] for point in points_to_verify)
            )
        return {
            "matches": validated,
            "requirement_coverage": round(contribution / total_weight * 100, 2),
            "counts": counts,
            "suitability_summary": " ".join(summary_sections),
            "strengths": strengths,
            "gaps": gaps,
            "points_to_verify": points_to_verify,
            "review_flags": global_flags,
        }

    def _create_ranking_snapshot(
        self,
        db: Session,
        *,
        posting_id: int,
        interviewer_user_id: int,
        requirement_snapshot_hash: str,
    ) -> RankingSnapshot:
        runs = list(
            db.scalars(
                select(ScreeningRun)
                .where(
                    ScreeningRun.job_posting_id == posting_id,
                    ScreeningRun.requirement_snapshot_hash
                    == requirement_snapshot_hash,
                )
                .order_by(ScreeningRun.created_at.desc(), ScreeningRun.id.desc())
            )
        )
        latest_by_application: dict[int, ScreeningRun] = {}
        for run in runs:
            latest_by_application.setdefault(run.application_id, run)
        ranked_runs = sorted(
            (
                run
                for run in latest_by_application.values()
                if run.status in {ScreeningRunStatus.COMPLETED, ScreeningRunStatus.FAILED, ScreeningRunStatus.REVIEW_REQUIRED}
            ),
            key=lambda run: (-(run.requirement_coverage or 0), run.application_id),
        )
        snapshot = RankingSnapshot(
            job_posting_id=posting_id,
            requirement_snapshot_hash=requirement_snapshot_hash,
            calculation_version=CALCULATION_VERSION,
            created_by_user_id=interviewer_user_id,
        )
        db.add(snapshot)
        db.flush()
        previous_score: float | None = None
        previous_rank = 0
        for index, run in enumerate(ranked_runs, start=1):
            coverage = run.requirement_coverage or 0
            rank = previous_rank if coverage == previous_score else index
            previous_score = coverage
            previous_rank = rank
            self._add_ranking_entry(
                db,
                snapshot=snapshot,
                run=run,
                rank=rank,
                disposition=RankingDisposition.RANKED,
            )
        db.commit()
        return snapshot

    @staticmethod
    def _ranking_response(
        db: Session,
        *,
        job_posting_id: int,
        requirement_snapshot_hash: str,
    ) -> dict[str, Any]:
        snapshot = db.scalar(
            select(RankingSnapshot)
            .where(
                RankingSnapshot.job_posting_id == job_posting_id,
                RankingSnapshot.requirement_snapshot_hash
                == requirement_snapshot_hash,
            )
            .order_by(RankingSnapshot.created_at.desc(), RankingSnapshot.id.desc())
        )
        empty = {
            "snapshot_id": None,
            "created_at": None,
            "calculation_version": CALCULATION_VERSION,
            "ranked": [],
            "review": [],
        }
        if snapshot is None:
            return empty
        entries = list(
            db.scalars(
                select(RankingEntry)
                .where(RankingEntry.ranking_snapshot_id == snapshot.id)
                .order_by(
                    RankingEntry.rank.asc().nulls_last(),
                    RankingEntry.application_id,
                )
            )
        )
        ranked: list[dict[str, Any]] = []
        review: list[dict[str, Any]] = []
        for entry in entries:
            application = db.get(CandidateApplication, entry.application_id)
            candidate = (
                db.get(Candidate, application.candidate_id)
                if application and application.candidate_id
                else None
            )
            item = {
                "application_id": entry.application_id,
                "screening_run_id": entry.screening_run_id,
                "candidate_name": (
                    candidate.name
                    if candidate and candidate.name
                    else f"Candidate #{entry.application_id}"
                ),
                "candidate_email": candidate.email if candidate else None,
                "rank": entry.rank,
                "disposition": entry.disposition.value,
                "requirement_coverage": entry.requirement_coverage,
                "met_count": entry.met_count,
                "partially_met_count": entry.partially_met_count,
                "unmet_count": entry.unmet_count,
                "uncertain_count": entry.uncertain_count,
                "suitability_summary": entry.suitability_summary,
                "strengths": entry.strengths,
                "gaps": entry.gaps,
                "points_to_verify": entry.points_to_verify,
            }
            (ranked if entry.disposition is RankingDisposition.RANKED else review).append(
                item
            )
        return {
            "snapshot_id": snapshot.id,
            "created_at": snapshot.created_at,
            "calculation_version": snapshot.calculation_version,
            "ranked": ranked,
            "review": review,
        }

    @staticmethod
    def _add_ranking_entry(
        db: Session,
        *,
        snapshot: RankingSnapshot,
        run: ScreeningRun,
        rank: int | None,
        disposition: RankingDisposition,
    ) -> None:
        db.add(
            RankingEntry(
                ranking_snapshot_id=snapshot.id,
                screening_run_id=run.id,
                application_id=run.application_id,
                rank=rank,
                disposition=disposition,
                requirement_coverage=run.requirement_coverage or 0,
                met_count=run.met_count,
                partially_met_count=run.partially_met_count,
                unmet_count=run.unmet_count,
                uncertain_count=run.uncertain_count,
                suitability_summary=run.suitability_summary,
                strengths=run.strengths,
                gaps=run.gaps,
                points_to_verify=run.points_to_verify,
            )
        )

    @staticmethod
    def _owned_context(
        db: Session,
        *,
        interviewer_user_id: int,
        job_posting_id: int,
    ) -> tuple[JobPosting, JobDescription, RequirementProfile]:
        row = db.execute(
            select(JobPosting, JobDescription, RequirementProfile)
            .join(JobDescription, JobDescription.id == JobPosting.job_description_id)
            .join(
                RequirementProfile,
                RequirementProfile.id == JobDescription.requirement_profile_id,
            )
            .where(
                JobPosting.id == job_posting_id,
                JobDescription.created_by_user_id == interviewer_user_id,
            )
        ).one_or_none()
        if row is None:
            raise LookupError("Job posting not found")
        posting, job, profile = row
        if job.status is not JobDescriptionStatus.APPROVED:
            raise ValueError("Approve the job description before screening candidates")
        if profile.status is not RequirementProfileStatus.CONFIRMED:
            raise ValueError("Confirm the requirement profile before screening candidates")
        return posting, job, profile

    @staticmethod
    def _requirement_snapshot(
        profile: RequirementProfile,
    ) -> tuple[dict[str, Any], str]:
        requirements: list[dict[str, Any]] = []

        def append_items(category: str, values: list[Any]) -> None:
            for index, value in enumerate(values):
                if isinstance(value, str):
                    name, details, raw_weight = value, None, None
                else:
                    name = str(value.get("name") or value.get("title") or "").strip()
                    details = value.get("details") or value.get("description")
                    raw_weight = value.get("weight")
                if not name:
                    continue
                weight = 1.0 if raw_weight is None else float(raw_weight)
                if not math.isfinite(weight) or weight <= 0:
                    raise ValueError(
                        f"Requirement '{name}' has an invalid weight; use a number above zero"
                    )
                requirements.append(
                    {
                        "key": f"{category}:{index}",
                        "category": category,
                        "name": name,
                        "details": str(details).strip() if details else None,
                        "weight": weight,
                    }
                )

        append_items("required_skill", profile.required_skills or [])
        append_items("preferred_skill", profile.preferred_skills or [])
        append_items("qualification", profile.qualifications or [])
        if profile.min_years_experience is not None:
            requirements.append(
                {
                    "key": "experience:0",
                    "category": "experience",
                    "name": (
                        f"At least {profile.min_years_experience} years of "
                        "relevant experience"
                    ),
                    "details": (
                        "Assess relevant experience only from employment dates "
                        "and role evidence supported by the CV."
                    ),
                    "weight": 1.0,
                }
            )
        append_items("selection_criterion", profile.selection_criteria or [])
        if not requirements:
            raise ValueError(
                "The approved requirement profile has no screenable requirements"
            )
        snapshot = {
            "profile_id": profile.id,
            "profile_updated_at": profile.updated_at.isoformat(),
            "title": profile.title,
            "requirements": requirements,
            "default_weight": 1.0,
        }
        encoded = json.dumps(snapshot, sort_keys=True, ensure_ascii=False)
        return snapshot, hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _compatible_run(
        db: Session,
        *,
        application_id: int,
        cv_sha256: str,
        requirement_snapshot_hash: str,
    ) -> ScreeningRun | None:
        if not cv_sha256:
            return None
        return db.scalar(
            select(ScreeningRun)
            .where(
                ScreeningRun.application_id == application_id,
                ScreeningRun.cv_sha256 == cv_sha256,
                ScreeningRun.requirement_snapshot_hash
                == requirement_snapshot_hash,
                ScreeningRun.status == ScreeningRunStatus.COMPLETED,
                ScreeningRun.prompt_version == PROMPT_VERSION,
                ScreeningRun.calculation_version == CALCULATION_VERSION,
            )
            .order_by(ScreeningRun.created_at.desc(), ScreeningRun.id.desc())
        )

    @staticmethod
    def _latest_cv_sha(db: Session, application_id: int) -> str:
        document = db.scalar(
            select(CVDocument)
            .where(CVDocument.application_id == application_id)
            .order_by(CVDocument.created_at.desc(), CVDocument.id.desc())
        )
        return document.sha256 if document else ""

    @staticmethod
    def recover_interrupted(db: Session) -> None:
        message = "Screening was interrupted by an application restart; retry the batch."
        for batch in db.scalars(
            select(ScreeningBatch).where(
                ScreeningBatch.status.in_(
                    [ScreeningBatchStatus.QUEUED, ScreeningBatchStatus.PROCESSING]
                )
            )
        ):
            batch.status = ScreeningBatchStatus.FAILED
            batch.error_message = message
            batch.completed_at = datetime.now(timezone.utc)
        for run in db.scalars(
            select(ScreeningRun).where(
                ScreeningRun.status.in_(
                    [ScreeningRunStatus.QUEUED, ScreeningRunStatus.PROCESSING]
                )
            )
        ):
            run.status = ScreeningRunStatus.FAILED
            run.error_message = message
            run.completed_at = datetime.now(timezone.utc)
        for item in db.scalars(
            select(ScreeningBatchItem).where(
                ScreeningBatchItem.status.in_(
                    [ScreeningRunStatus.QUEUED, ScreeningRunStatus.PROCESSING]
                )
            )
        ):
            item.status = ScreeningRunStatus.FAILED
            item.error_message = message
        db.commit()
