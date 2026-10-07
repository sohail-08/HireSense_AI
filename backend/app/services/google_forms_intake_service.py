import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.integrations.google_workspace import GoogleWorkspaceReader
from app.models.candidate import (
    ApplicationSource,
    Candidate,
    CandidateApplication,
    CVDocument,
    CVProcessingStatus,
)
from app.models.job import JobDescription, JobPosting


HEADER_ALIASES = {
    "timestamp": ("timestamp", "submitted at", "submission time"),
    "name": ("name", "full name", "candidate name"),
    "email": ("email", "email address", "candidate email"),
    "phone": ("phone", "phone number", "mobile", "mobile number"),
    "linkedin": ("linkedin", "linkedin url", "linkedin profile"),
    "portfolio": ("portfolio", "portfolio url", "website"),
    "location": ("location", "current location", "city", "country"),
    "cv": (
        "cv",
        "resume",
        "upload cv",
        "cv upload",
        "upload your cv",
        "upload resume",
        "curriculum vitae",
    ),
}

ALLOWED_CV_TYPES = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        ".docx"
    ),
}
ALLOWED_CV_SUFFIXES = {".pdf", ".docx"}


class GoogleFormsIntakeService:
    def __init__(
        self,
        reader: GoogleWorkspaceReader,
        settings: Settings,
    ):
        self.reader = reader
        self.settings = settings

    def sync(
        self,
        db: Session,
        *,
        interviewer_user_id: int,
        job_posting_id: int,
    ) -> dict[str, Any]:
        spreadsheet_id = self.settings.google_forms_spreadsheet_id
        if not spreadsheet_id:
            raise ValueError(
                "GOOGLE_FORMS_SPREADSHEET_ID is not configured"
            )
        posting, job = self._owned_posting(
            db,
            interviewer_user_id=interviewer_user_id,
            job_posting_id=job_posting_id,
        )
        rows = self.reader.read_sheet(
            spreadsheet_id=spreadsheet_id,
            sheet_name=self.settings.google_forms_sheet_name,
        )
        if not rows:
            return self._empty_result()

        headers = [str(value).strip() for value in rows[0]]
        mapping = self._column_mapping(headers)
        result = self._empty_result()
        downloaded_paths: list[Path] = []

        try:
            for row_number, raw_row in enumerate(rows[1:], start=2):
                values = [str(value).strip() for value in raw_row]
                if not any(values):
                    continue
                record = {
                    header: values[index] if index < len(values) else ""
                    for index, header in enumerate(headers)
                    if header
                }
                if not self._matches_job(
                    values,
                    mapping.get("job"),
                    posting=posting,
                    job=job,
                ):
                    result["skipped_other_jobs"] += 1
                    continue

                reference = self._source_reference(
                    spreadsheet_id=spreadsheet_id,
                    sheet_name=self.settings.google_forms_sheet_name,
                    job_posting_id=posting.id,
                    record=record,
                )
                existing = db.scalar(
                    select(CandidateApplication).where(
                        CandidateApplication.job_posting_id == posting.id,
                        CandidateApplication.source
                        == ApplicationSource.GOOGLE_FORM,
                        CandidateApplication.source_reference == reference,
                    )
                )
                if existing is not None:
                    result["skipped_existing"] += 1
                    if not existing.cv_documents and existing.candidate_id:
                        candidate = db.get(Candidate, existing.candidate_id)
                        if candidate is not None:
                            retry_warnings: list[str] = []
                            file_ids = self._drive_file_ids(
                                self._value(values, mapping.get("cv"))
                            )
                            for file_id in file_ids:
                                try:
                                    path = self._download_cv(
                                        application=existing,
                                        candidate=candidate,
                                        file_id=file_id,
                                    )
                                    downloaded_paths.append(path)
                                    result["downloaded_cvs"] += 1
                                except (RuntimeError, ValueError) as exc:
                                    retry_warnings.append(str(exc))
                            existing.response_data = {
                                **record,
                                "_google_import": {
                                    "sheet_name": (
                                        self.settings.google_forms_sheet_name
                                    ),
                                    "row_number": row_number,
                                    "drive_file_ids": file_ids,
                                    "warnings": retry_warnings,
                                },
                            }
                            result["issues"].extend(
                                {
                                    "row_number": row_number,
                                    "message": warning,
                                }
                                for warning in retry_warnings
                            )
                    continue

                row_warnings: list[str] = []
                name = self._value(values, mapping.get("name"))
                email_value = self._value(values, mapping.get("email"))
                email = ""
                if email_value:
                    try:
                        email = validate_email(
                            email_value,
                            check_deliverability=False,
                        ).normalized.lower()
                    except EmailNotValidError:
                        row_warnings.append(
                            f"Ignored invalid candidate email '{email_value}'"
                        )
                if not name and not email:
                    result["issues"].append(
                        {
                            "row_number": row_number,
                            "message": "Skipped row without a candidate name or email",
                        }
                    )
                    continue

                candidate = self._candidate(
                    db,
                    name=name,
                    email=email,
                    phone=self._value(values, mapping.get("phone")),
                    linkedin_url=self._value(
                        values,
                        mapping.get("linkedin"),
                    ),
                    portfolio_url=self._value(
                        values,
                        mapping.get("portfolio"),
                    ),
                    location=self._value(values, mapping.get("location")),
                )
                submitted_at = self._parse_timestamp(
                    self._value(values, mapping.get("timestamp"))
                )
                application = CandidateApplication(
                    job_posting_id=posting.id,
                    candidate_id=candidate.id,
                    source=ApplicationSource.GOOGLE_FORM,
                    source_reference=reference,
                    submitted_at=submitted_at,
                    response_data=record,
                )
                db.add(application)
                db.flush()

                cv_value = self._value(values, mapping.get("cv"))
                file_ids = self._drive_file_ids(cv_value)
                if not file_ids:
                    row_warnings.append(
                        "No Google Drive CV link was found in the configured CV column"
                    )
                for file_id in file_ids:
                    try:
                        path = self._download_cv(
                            application=application,
                            candidate=candidate,
                            file_id=file_id,
                        )
                        downloaded_paths.append(path)
                        result["downloaded_cvs"] += 1
                    except (RuntimeError, ValueError) as exc:
                        row_warnings.append(str(exc))

                application.response_data = {
                    **record,
                    "_google_import": {
                        "sheet_name": self.settings.google_forms_sheet_name,
                        "row_number": row_number,
                        "drive_file_ids": file_ids,
                        "warnings": row_warnings,
                    },
                }
                result["imported_applications"] += 1
                result["issues"].extend(
                    {
                        "row_number": row_number,
                        "message": warning,
                    }
                    for warning in row_warnings
                )

            db.commit()
            return result
        except Exception:
            db.rollback()
            for path in downloaded_paths:
                path.unlink(missing_ok=True)
            raise

    @staticmethod
    def list_postings(
        db: Session,
        *,
        interviewer_user_id: int,
    ) -> list[dict[str, Any]]:
        rows = db.execute(
            select(JobPosting, JobDescription)
            .join(
                JobDescription,
                JobDescription.id == JobPosting.job_description_id,
            )
            .where(JobDescription.created_by_user_id == interviewer_user_id)
            .order_by(JobPosting.created_at.desc(), JobPosting.id.desc())
        ).all()
        return [
            {
                "id": posting.id,
                "job_description_id": job.id,
                "title": job.title,
                "status": posting.status.value,
                "published_at": posting.published_at,
            }
            for posting, job in rows
        ]

    @staticmethod
    def list_applications(
        db: Session,
        *,
        interviewer_user_id: int,
        job_posting_id: int | None = None,
    ) -> list[dict[str, Any]]:
        query = (
            select(CandidateApplication, Candidate, JobDescription)
            .join(
                Candidate,
                Candidate.id == CandidateApplication.candidate_id,
            )
            .join(
                JobPosting,
                JobPosting.id == CandidateApplication.job_posting_id,
            )
            .join(
                JobDescription,
                JobDescription.id == JobPosting.job_description_id,
            )
            .where(JobDescription.created_by_user_id == interviewer_user_id)
            .order_by(
                CandidateApplication.submitted_at.desc(),
                CandidateApplication.id.desc(),
            )
        )
        if job_posting_id is not None:
            query = query.where(
                CandidateApplication.job_posting_id == job_posting_id
            )
        rows = db.execute(query).all()
        application_ids = [application.id for application, _, _ in rows]
        documents_by_application: dict[int, list[CVDocument]] = {}
        if application_ids:
            documents = db.scalars(
                select(CVDocument).where(
                    CVDocument.application_id.in_(application_ids)
                )
            )
            for document in documents:
                if document.application_id is not None:
                    documents_by_application.setdefault(
                        document.application_id,
                        [],
                    ).append(document)
        return [
            {
                "id": application.id,
                "job_posting_id": application.job_posting_id,
                "job_title": job.title,
                "source": application.source,
                "source_reference": application.source_reference,
                "status": application.status,
                "submitted_at": application.submitted_at,
                "response_data": application.response_data,
                "candidate": candidate,
                "cv_documents": documents_by_application.get(
                    application.id,
                    [],
                ),
            }
            for application, candidate, job in rows
        ]

    def _column_mapping(self, headers: list[str]) -> dict[str, int | None]:
        configured = {
            "timestamp": self.settings.google_forms_timestamp_column,
            "name": self.settings.google_forms_name_column,
            "email": self.settings.google_forms_email_column,
            "phone": self.settings.google_forms_phone_column,
            "linkedin": self.settings.google_forms_linkedin_column,
            "portfolio": self.settings.google_forms_portfolio_column,
            "location": self.settings.google_forms_location_column,
            "cv": self.settings.google_forms_cv_column,
        }
        mapping = {
            field: self._find_header(headers, preferred, HEADER_ALIASES[field])
            for field, preferred in configured.items()
        }
        if mapping["cv"] is None:
            raise ValueError(
                "The configured CV column was not found in the response sheet. "
                f"Available headers: {', '.join(headers)}"
            )
        job_column = self.settings.google_forms_job_column
        mapping["job"] = (
            self._find_header(headers, job_column, (job_column,))
            if job_column
            else None
        )
        if job_column and mapping["job"] is None:
            raise ValueError(
                f"Configured job column '{job_column}' was not found"
            )
        return mapping

    @staticmethod
    def _find_header(
        headers: list[str],
        preferred: str | None,
        aliases: tuple[str | None, ...],
    ) -> int | None:
        normalized = [GoogleFormsIntakeService._normalize(item) for item in headers]
        candidates = [preferred, *aliases]
        for candidate in candidates:
            if not candidate:
                continue
            expected = GoogleFormsIntakeService._normalize(candidate)
            if expected in normalized:
                return normalized.index(expected)
        for index, header in enumerate(normalized):
            for candidate in candidates:
                if not candidate:
                    continue
                expected = GoogleFormsIntakeService._normalize(candidate)
                if len(expected) >= 3 and expected in header:
                    return index
        return None

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()

    @staticmethod
    def _value(values: list[str], index: int | None) -> str:
        return values[index].strip() if index is not None and index < len(values) else ""

    @staticmethod
    def _source_reference(
        *,
        spreadsheet_id: str,
        sheet_name: str,
        job_posting_id: int,
        record: dict[str, str],
    ) -> str:
        payload = json.dumps(
            [spreadsheet_id, sheet_name, job_posting_id, record],
            ensure_ascii=False,
            sort_keys=True,
        )
        return "gform:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _matches_job(
        self,
        values: list[str],
        job_index: int | None,
        *,
        posting: JobPosting,
        job: JobDescription,
    ) -> bool:
        if job_index is None:
            return True
        selected = self._normalize(self._value(values, job_index))
        return selected in {
            self._normalize(str(posting.id)),
            self._normalize(job.title),
        }

    @staticmethod
    def _candidate(
        db: Session,
        *,
        name: str,
        email: str,
        phone: str,
        linkedin_url: str,
        portfolio_url: str,
        location: str,
    ) -> Candidate:
        candidate = None
        if email:
            candidate = db.scalar(
                select(Candidate).where(func.lower(Candidate.email) == email)
            )
        if candidate is None:
            candidate = Candidate(email=email or None)
            db.add(candidate)
        updates = {
            "name": name[:200],
            "phone": phone[:50],
            "linkedin_url": linkedin_url[:2048],
            "portfolio_url": portfolio_url[:2048],
            "location": location[:200],
        }
        for field, value in updates.items():
            if value:
                setattr(candidate, field, value)
        db.flush()
        return candidate

    def _download_cv(
        self,
        *,
        application: CandidateApplication,
        candidate: Candidate,
        file_id: str,
    ) -> Path:
        metadata = self.reader.get_file(file_id)
        suffix = Path(metadata.name).suffix.lower()
        if (
            metadata.mime_type not in ALLOWED_CV_TYPES
            and suffix not in ALLOWED_CV_SUFFIXES
        ):
            raise ValueError(
                f"Skipped unsupported CV type for '{metadata.name}'; "
                "only PDF and DOCX are accepted"
            )
        max_bytes = self.settings.cv_max_file_size_mb * 1024 * 1024
        if metadata.size is not None and metadata.size > max_bytes:
            raise ValueError(
                f"Skipped '{metadata.name}' because it exceeds "
                f"{self.settings.cv_max_file_size_mb} MB"
            )
        safe_name = self._safe_filename(metadata.name)
        if Path(safe_name).suffix.lower() not in ALLOWED_CV_SUFFIXES:
            safe_name = self._safe_filename(
                safe_name + ALLOWED_CV_TYPES.get(metadata.mime_type, "")
            )
        root = Path(self.settings.storage_root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        destination = (
            root / f"cvs/{application.id}/{file_id[:16]}_{safe_name}"
        ).resolve()
        if root not in destination.parents:
            raise ValueError("CV storage path escaped the private storage root")
        size = self.reader.download_file(
            file_id=file_id,
            destination=destination,
            max_bytes=max_bytes,
        )
        digest = hashlib.sha256()
        with destination.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        relative_path = destination.relative_to(root).as_posix()
        document = CVDocument(
            application_id=application.id,
            candidate_id=candidate.id,
            original_filename=safe_name,
            storage_path=relative_path,
            mime_type=metadata.mime_type[:100],
            file_size_bytes=size,
            sha256=digest.hexdigest(),
            source=ApplicationSource.GOOGLE_FORM,
            status=CVProcessingStatus.VALIDATED,
        )
        application.cv_documents.append(document)
        return destination

    @staticmethod
    def _safe_filename(value: str) -> str:
        name = Path(value).name
        name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
        return (name or "candidate-cv")[:255]

    @staticmethod
    def _drive_file_ids(value: str) -> list[str]:
        ids: list[str] = []
        for token in re.split(r"[\s,;]+", value):
            token = token.strip()
            if not token:
                continue
            parsed = urlparse(token)
            query_id = parse_qs(parsed.query).get("id", [None])[0]
            path_match = re.search(r"/d/([A-Za-z0-9_-]+)", parsed.path)
            raw_match = re.fullmatch(r"[A-Za-z0-9_-]{10,}", token)
            file_id = query_id or (path_match.group(1) if path_match else None)
            if file_id is None and raw_match:
                file_id = token
            if file_id and file_id not in ids:
                ids.append(file_id)
        return ids

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        if value:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return (
                    parsed.replace(tzinfo=timezone.utc)
                    if parsed.tzinfo is None
                    else parsed
                )
            except ValueError:
                pass
            for date_format in (
                "%m/%d/%Y %H:%M:%S",
                "%d/%m/%Y %H:%M:%S",
                "%m/%d/%Y %H:%M",
                "%d/%m/%Y %H:%M",
            ):
                try:
                    return datetime.strptime(value, date_format).replace(
                        tzinfo=timezone.utc
                    )
                except ValueError:
                    continue
        return datetime.now(timezone.utc)

    @staticmethod
    def _owned_posting(
        db: Session,
        *,
        interviewer_user_id: int,
        job_posting_id: int,
    ) -> tuple[JobPosting, JobDescription]:
        row = db.execute(
            select(JobPosting, JobDescription)
            .join(
                JobDescription,
                JobDescription.id == JobPosting.job_description_id,
            )
            .where(
                JobPosting.id == job_posting_id,
                JobDescription.created_by_user_id == interviewer_user_id,
            )
        ).one_or_none()
        if row is None:
            raise LookupError("Job posting not found")
        return row[0], row[1]

    @staticmethod
    def _empty_result() -> dict[str, Any]:
        return {
            "imported_applications": 0,
            "skipped_existing": 0,
            "skipped_other_jobs": 0,
            "downloaded_cvs": 0,
            "issues": [],
        }
