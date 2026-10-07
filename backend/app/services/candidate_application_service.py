import hashlib
import json
import logging
from pathlib import Path

from sqlalchemy import func, select
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

    def delete(
        self,
        db: Session,
        *,
        application_id: int,
        interviewer_user_id: int,
    ) -> None:
        application = db.scalar(
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
                CandidateApplication.id == application_id,
                JobDescription.created_by_user_id == interviewer_user_id,
            )
        )
        if application is None:
            raise LookupError("Candidate application not found")

        paths, candidate_id = self.delete_record(
            db,
            application=application,
            interviewer_user_id=interviewer_user_id,
            remember_import=True,
        )
        db.flush()
        self.delete_orphan_candidate(db, candidate_id)
        db.commit()
        self.cleanup_cv_files(paths)

    def delete_record(
        self,
        db: Session,
        *,
        application: CandidateApplication,
        interviewer_user_id: int,
        remember_import: bool,
    ) -> tuple[list[Path], int | None]:
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

        for document in documents:
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
