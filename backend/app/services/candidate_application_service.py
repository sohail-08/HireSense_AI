import hashlib
import json
import logging
import re
import zipfile
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.candidate import (
    ApplicationImportExclusion,
    ApplicationSource,
    Candidate,
    CandidateApplication,
    CVDocument,
)
from app.models.job import JobDescription, JobPosting
from app.models.scoring import CandidateScore, ScoringRequestKey, ScoringRun


logger = logging.getLogger(__name__)


def google_form_reference(
    *,
    spreadsheet_id: str,
    sheet_name: str,
    record: dict[str, object],
) -> str:
    payload = json.dumps(
        [spreadsheet_id, sheet_name, record],
        ensure_ascii=False,
        sort_keys=True,
    )
    return "gform:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CandidateApplicationService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def cv_file(self, db: Session, *, application_id: int, document_id: int,
                interviewer_user_id: int) -> tuple[Path, str, str]:
        """Resolve a private CV only after verifying posting ownership and both IDs."""
        from app.screening.parsing import CVParser, CVReviewRequired

        document = db.scalar(select(CVDocument)
            .join(CandidateApplication, CandidateApplication.id == CVDocument.application_id)
            .join(JobPosting, JobPosting.id == CandidateApplication.job_posting_id)
            .join(JobDescription, JobDescription.id == JobPosting.job_description_id)
            .where(CVDocument.id == document_id, CandidateApplication.id == application_id,
                   JobDescription.created_by_user_id == interviewer_user_id))
        if document is None:
            raise LookupError("CV not found")
        root = Path(self.settings.storage_root).expanduser().resolve()
        cv_root = (root / "cvs").resolve()
        path = (root / document.storage_path).resolve()
        if root not in cv_root.parents or cv_root not in path.parents or not path.is_file():
            raise LookupError("This CV is not available. Try syncing responses again.")
        mime_types = {".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
        if path.suffix.lower() not in mime_types:
            raise ValueError("Only PDF and Word (.docx) CV files can be opened.")
        try:
            CVParser(self.settings)._validate_file(path, document)
            if path.suffix.lower() == ".docx":
                with zipfile.ZipFile(path) as archive:
                    if not {"[Content_Types].xml", "word/document.xml"}.issubset(archive.namelist()):
                        raise ValueError("The saved file is not a Word document.")
        except FileNotFoundError:
            raise LookupError("This CV is no longer available.") from None
        except (CVReviewRequired, ValueError, OSError, zipfile.BadZipFile):
            raise ValueError("The saved CV could not be verified. Sync an updated copy and try again.") from None
        filename = re.sub(r"[\x00-\x1f\x7f]", "", document.original_filename.replace("\\", "/").split("/")[-1]).strip()
        if not filename: filename = "candidate-cv" + path.suffix.lower()
        if not filename.lower().endswith(path.suffix.lower()): filename += path.suffix.lower()
        return path, mime_types[path.suffix.lower()], filename

    def delete(
        self,
        db: Session,
        *,
        application_id: int,
        interviewer_user_id: int,
    ) -> None:
        self.delete_many(db, application_ids=[application_id], interviewer_user_id=interviewer_user_id)

    def delete_many(self, db: Session, *, application_ids: list[int], interviewer_user_id: int) -> list[int]:
        ids = list(dict.fromkeys(application_ids))
        if not ids or len(ids) > 100 or any(type(value) is not int or value <= 0 for value in ids):
            raise ValueError("Select between 1 and 100 applications to delete.")
        applications = list(db.scalars(
            select(CandidateApplication)
            .join(
                JobPosting,
                JobPosting.id == CandidateApplication.job_posting_id,
            )
            .join(
                JobDescription,
                JobDescription.id == JobPosting.job_description_id,
            )
            .where(
                CandidateApplication.id.in_(ids),
                JobDescription.created_by_user_id == interviewer_user_id,
            )
        ))
        # Validate the entire selection before touching any application or file.
        if len(applications) != len(ids):
            raise LookupError("Candidate application not found")
        paths: list[Path] = []
        candidate_ids: set[int | None] = set()
        try:
            for application in applications:
                removed_paths, candidate_id = self.delete_record(db, application=application,
                    interviewer_user_id=interviewer_user_id, remember_import=True)
                paths.extend(removed_paths)
                candidate_ids.add(candidate_id)
                # Subsequent deletes must see updated shared snapshots even with autoflush disabled.
                db.flush()
            for candidate_id in candidate_ids:
                self.delete_orphan_candidate(db, candidate_id)
            db.commit()
        except Exception:
            db.rollback()
            raise
        self.cleanup_cv_files(paths)
        return ids

    def delete_record(
        self,
        db: Session,
        *,
        application: CandidateApplication,
        interviewer_user_id: int,
        remember_import: bool,
    ) -> tuple[list[Path], int | None]:
        from app.services.assessment_service import AssessmentService
        AssessmentService.delete_sources(db, application_ids=[application.id])
        documents = list(
            db.scalars(
                select(CVDocument).where(
                    CVDocument.application_id == application.id
                )
            )
        )
        paths = [self._cv_path(document.storage_path) for document in documents]
        candidate_id = application.candidate_id

        if remember_import:
            for reference in self._deletion_references(application):
                exists = db.scalar(
                    select(ApplicationImportExclusion.id).where(
                        ApplicationImportExclusion.created_by_user_id
                        == interviewer_user_id,
                        ApplicationImportExclusion.source == application.source,
                        ApplicationImportExclusion.source_reference == reference,
                    )
                )
                if exists is None:
                    db.add(
                        ApplicationImportExclusion(
                            created_by_user_id=interviewer_user_id,
                            source=application.source,
                            source_reference=reference,
                        )
                    )

        # Remove whole immutable calculation snapshots containing this application,
        # rather than retaining deleted CV evidence or rewriting historical scores.
        from copy import deepcopy
        from app.models.interview import InterviewBatch, InterviewSchedule, InterviewDelivery, CandidateInterviewSession
        schedule_ids = list(db.scalars(select(InterviewSchedule.id).where(InterviewSchedule.application_id == application.id)))
        from app.services.work_sample import WorkSampleService
        WorkSampleService.delete_for_interviews(db, schedule_ids)
        from app.services.transcription_service import TranscriptionService
        TranscriptionService.delete_for_interviews(db, schedule_ids)
        db.execute(delete(CandidateInterviewSession).where(CandidateInterviewSession.application_id == application.id))
        db.execute(delete(InterviewDelivery).where(InterviewDelivery.application_id == application.id))
        db.execute(delete(InterviewSchedule).where(InterviewSchedule.application_id == application.id))
        for batch in db.scalars(select(InterviewBatch)):
            if not any(item.get("application_id") == application.id for item in batch.snapshot.get("recipients", [])):
                continue
            snapshot = deepcopy(batch.snapshot)
            snapshot["recipients"] = [item for item in snapshot["recipients"] if item.get("application_id") != application.id]
            snapshot.pop("selection_token", None)
            for key in ("selected", "excluded"):
                if "selection" in snapshot:
                    snapshot["selection"][key] = [item for item in snapshot["selection"].get(key, []) if item.get("application_id") != application.id]
            if "selection" in snapshot:
                snapshot["selection"]["recipient_count"] = len(snapshot["selection"]["selected"])
            if "schedule_ids" in snapshot.get("schedule", {}):
                snapshot["schedule"]["schedule_ids"] = [item for item in snapshot["schedule"]["schedule_ids"] if item not in schedule_ids]
            batch.snapshot = snapshot
            if batch.status == "draft":
                batch.status = "invalidated"
            if not snapshot["recipients"]:
                db.delete(batch)
        score_run_ids = list(db.scalars(select(CandidateScore.scoring_run_id).where(CandidateScore.application_id == application.id)))
        if score_run_ids:
            db.execute(delete(ScoringRequestKey).where(ScoringRequestKey.scoring_run_id.in_(score_run_ids)))
            db.execute(delete(CandidateScore).where(CandidateScore.scoring_run_id.in_(score_run_ids)))
            db.execute(delete(ScoringRun).where(ScoringRun.id.in_(score_run_ids)))
        for document in documents:
            from app.models.cv_evidence import CVPassage
            db.execute(delete(CVPassage).where(CVPassage.document_id == document.id))
            db.delete(document)
        db.delete(application)
        return paths, candidate_id

    @staticmethod
    def delete_orphan_candidate(
        db: Session,
        candidate_id: int | None,
    ) -> None:
        if candidate_id is None:
            return
        remaining_applications = db.scalar(
            select(func.count(CandidateApplication.id)).where(
                CandidateApplication.candidate_id == candidate_id
            )
        )
        remaining_documents = db.scalar(
            select(func.count(CVDocument.id)).where(
                CVDocument.candidate_id == candidate_id
            )
        )
        if not remaining_applications and not remaining_documents:
            candidate = db.get(Candidate, candidate_id)
            if candidate is not None:
                db.delete(candidate)

    def cleanup_cv_files(self, paths: list[Path]) -> None:
        storage_root = Path(self.settings.storage_root).expanduser().resolve()
        cv_root = (storage_root / "cvs").resolve()
        for path in paths:
            try:
                path.unlink(missing_ok=True)
                parent = path.parent
                if parent != cv_root and cv_root in parent.parents:
                    parent.rmdir()
            except OSError:
                logger.warning("Could not remove deleted CV file %s", path)

    def _cv_path(self, relative_path: str) -> Path:
        root = Path(self.settings.storage_root).expanduser().resolve()
        path = (root / relative_path).resolve()
        if root not in path.parents:
            raise ValueError("CV storage path escaped the private storage root")
        return path

    def _deletion_references(
        self,
        application: CandidateApplication,
    ) -> set[str]:
        references = {
            reference
            for reference in [application.source_reference]
            if reference
        }
        if application.source != ApplicationSource.GOOGLE_FORM:
            return references

        response_data = application.response_data or {}
        record = {
            key: value
            for key, value in response_data.items()
            if key != "_google_import"
        }
        metadata = response_data.get("_google_import", {})
        spreadsheet_id = metadata.get("spreadsheet_id") or (
            self.settings.google_forms_spreadsheet_id
        )
        sheet_name = metadata.get("sheet_name") or (
            self.settings.google_forms_sheet_name
        )
        if spreadsheet_id and record:
            references.add(
                google_form_reference(
                    spreadsheet_id=str(spreadsheet_id),
                    sheet_name=str(sheet_name),
                    record=record,
                )
            )
        return references
