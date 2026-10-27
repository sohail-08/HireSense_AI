import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.integrations.google_workspace import GoogleWorkspaceReader
from app.models.candidate import (
    ApplicationSource,
    ApplicationImportExclusion,
    Candidate,
    CandidateApplication,
    CVDocument,
    CVProcessingStatus,
)
from app.models.job import JobDescription, JobPosting
from app.services.candidate_application_service import google_form_reference
from app.services.google_forms_notifications import sheet_snapshots
from app.services.application_identity import bind_profile, submitted_profile, canonical_applications


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
JOB_HEADER_ALIASES = (
    "job posting",
    "job posting id",
    "job id",
    "position applied for",
    "applied position",
    "job title",
    "role applied for",
)

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

    def pending_responses(self, db: Session, *, interviewer_user_id: int) -> dict[str, Any]:
        """Count only new responses; all DB work is read-only and Drive is unused.

        Reconcile every request against current imports/exclusions, even when the
        source sheet is cached. Syncing therefore updates counts immediately.
        """
        spreadsheet_id = self.settings.google_forms_spreadsheet_id
        if not spreadsheet_id:
            raise ValueError("Google Forms is not configured")
        sheet_name = self.settings.google_forms_sheet_name
        key = (interviewer_user_id, spreadsheet_id, sheet_name, str(self.settings.google_service_account_file))
        rows, checked_at = sheet_snapshots.read(key, lambda: self.reader.read_sheet(
            spreadsheet_id=spreadsheet_id, sheet_name=sheet_name))
        result = {"status": "ready", "pending_count": 0, "unmatched_count": 0,
                  "jobs": [], "checked_at": checked_at, "message": None}
        if not rows:
            return result
        headers = [str(value).strip() for value in rows[0]]
        mapping = self._column_mapping(headers)
        postings = self._owned_postings(db, interviewer_user_id=interviewer_user_id)
        posting_ids = [posting.id for posting, _ in postings]
        existing_rows = self._existing_applications_by_row(db, postings=postings,
            spreadsheet_id=spreadsheet_id, sheet_name=sheet_name)
        seen = set(db.scalars(select(CandidateApplication.source_reference).where(
            CandidateApplication.job_posting_id.in_(posting_ids),
            CandidateApplication.source == ApplicationSource.GOOGLE_FORM)))
        seen.update(db.scalars(select(ApplicationImportExclusion.source_reference).where(
            ApplicationImportExclusion.created_by_user_id == interviewer_user_id,
            ApplicationImportExclusion.source == ApplicationSource.GOOGLE_FORM)))
        counts = {}
        for row_number, raw in enumerate(rows[1:], start=2):
            values = [str(value).strip() for value in raw]
            if not any(values) or row_number in existing_rows:
                continue
            record = {header: values[index] if index < len(values) else ""
                      for index, header in enumerate(headers) if header}
            reference = google_form_reference(spreadsheet_id=spreadsheet_id, sheet_name=sheet_name, record=record)
            if reference in seen:
                continue
            seen.add(reference)
            name, email = self._value(values, mapping.get("name")), self._value(values, mapping.get("email"))
            if email:
                try:
                    email = validate_email(email, check_deliverability=False).normalized
                except EmailNotValidError:
                    email = ""
            if not name and not email:
                continue  # The sync operation skips these malformed rows too.
            resolved, _ = self._resolve_posting(self._value(values, mapping.get("job")), postings)
            if resolved is None:
                result["unmatched_count"] += 1
                continue
            posting, job = resolved
            counts.setdefault(posting.id, {"job_posting_id": posting.id, "job_title": job.title, "count": 0})["count"] += 1
            result["pending_count"] += 1
        result["jobs"] = sorted(counts.values(), key=lambda item: (-item["count"], item["job_posting_id"]))
        return result

    def sync(
        self,
        db: Session,
        *,
        interviewer_user_id: int,
    ) -> dict[str, Any]:
        spreadsheet_id = self.settings.google_forms_spreadsheet_id
        if not spreadsheet_id:
            raise ValueError(
                "GOOGLE_FORMS_SPREADSHEET_ID is not configured"
            )
        rows = self.reader.read_sheet(
            spreadsheet_id=spreadsheet_id,
            sheet_name=self.settings.google_forms_sheet_name,
        )
        if not rows:
            return self._empty_result()

        headers = [str(value).strip() for value in rows[0]]
        mapping = self._column_mapping(headers)
        postings = self._owned_postings(
            db,
            interviewer_user_id=interviewer_user_id,
        )
        if not postings:
            raise LookupError("No job postings are available for candidate intake")
        existing_by_row = self._existing_applications_by_row(
            db,
            postings=postings,
            spreadsheet_id=spreadsheet_id,
            sheet_name=self.settings.google_forms_sheet_name,
        )
        deleted_references = set(
            db.scalars(
                select(ApplicationImportExclusion.source_reference).where(
                    ApplicationImportExclusion.created_by_user_id
                    == interviewer_user_id,
                    ApplicationImportExclusion.source
                    == ApplicationSource.GOOGLE_FORM,
                )
            )
        )
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
                job_value = self._value(values, mapping.get("job"))
                resolved, resolution_error = self._resolve_posting(
                    job_value,
                    postings,
                )
                if resolved is None:
                    result["unmatched_responses"] += 1
                    result["issues"].append(
                        {
                            "row_number": row_number,
                            "message": resolution_error,
                        }
                    )
                    continue
                posting, job = resolved

                reference = google_form_reference(
                    spreadsheet_id=spreadsheet_id,
                    sheet_name=self.settings.google_forms_sheet_name,
                    record=record,
                )
                if reference in deleted_references:
                    result["skipped_deleted"] += 1
                    continue
                existing = existing_by_row.get(row_number)
                if existing is not None:
                    old_profile = submitted_profile(existing.response_data or {}, self.settings)
                    new_profile = submitted_profile(record, self.settings)
                    # A sheet row number can move after insertion/deletion/sorting.
                    # It cannot authorize replacing a different person's submission.
                    from app.services.application_identity import normal
                    old_record = existing.response_data or {}
                    old_files = old_record.get("_google_import", {}).get("drive_file_ids", [])
                    new_files = self._drive_file_ids(self._value(values, mapping.get("cv")))
                    timestamp_keys = {normal(self.settings.google_forms_timestamp_column), *HEADER_ALIASES["timestamp"]}
                    old_time = next((str(v).strip() for k,v in old_record.items() if normal(k) in timestamp_keys), "")
                    new_time = self._value(values, mapping.get("timestamp"))
                    if (any(old_profile[k] and normal(old_profile[k]) != normal(new_profile[k]) for k in ("name", "email"))
                            or (old_files and set(old_files) != set(new_files))
                            or (old_time and new_time and old_time != new_time)):
                        existing = None
                if existing is None:
                    existing = db.scalar(
                        select(CandidateApplication).where(
                            CandidateApplication.job_posting_id.in_(
                                [owned_posting.id for owned_posting, _ in postings]
                            ),
                            CandidateApplication.source
                            == ApplicationSource.GOOGLE_FORM,
                            CandidateApplication.source_reference == reference,
                        )
                    )
                if existing is not None:
                    # Profiles belong to this submission, not every row using its email.
                    profile = submitted_profile(record, self.settings)
                    bind_profile(db, existing, profile)
                    if existing.job_posting_id != posting.id:
                        existing.job_posting_id = posting.id
                        result["reassigned_applications"] += 1
                    else:
                        result["skipped_existing"] += 1
                    existing.source_reference = reference
                    retry_warnings: list[str] = []
                    file_ids = self._drive_file_ids(
                        self._value(values, mapping.get("cv"))
                    )
                    if not existing.cv_documents and existing.candidate_id:
                        candidate = db.get(Candidate, existing.candidate_id)
                        if candidate is not None:
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
                        **{k:v for k,v in (existing.response_data or {}).items() if str(k).startswith("_") and k != "_google_import"},
                        **record,
                        "_google_import": {
                            "spreadsheet_id": spreadsheet_id,
                            "sheet_name": self.settings.google_forms_sheet_name,
                            "row_number": row_number,
                            "resolved_job_posting_id": posting.id,
                            "drive_file_ids": file_ids,
                            "warnings": retry_warnings,
                        },
                    }
                    self._import_face(db, existing, values, mapping, retry_warnings)
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
                        "spreadsheet_id": spreadsheet_id,
                        "sheet_name": self.settings.google_forms_sheet_name,
                        "row_number": row_number,
                        "resolved_job_posting_id": posting.id,
                        "drive_file_ids": file_ids,
                        "warnings": row_warnings,
                    },
                }
                self._import_face(db, application, values, mapping, row_warnings)
                result["imported_applications"] += 1
                result["issues"].extend(
                    {
                        "row_number": row_number,
                        "message": warning,
                    }
                    for warning in row_warnings
                )

            db.flush()
            all_imports = list(db.scalars(select(CandidateApplication).where(
                CandidateApplication.job_posting_id.in_([p.id for p, _ in postings]),
                CandidateApplication.source == ApplicationSource.GOOGLE_FORM)))
            canonical_applications(db, all_imports, mark_repeats=True)
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
        visible_ids = {a.id for a in canonical_applications(db, [a for a, _, _ in rows])}
        rows = [row for row in rows if row[0].id in visible_ids]
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
        mapping["photo"] = self._find_header(headers, self.settings.google_forms_photo_column, ("candidate photo", "upload your photo"))
        if mapping["cv"] is None:
            raise ValueError(
                "The configured CV column was not found in the response sheet. "
                f"Available headers: {', '.join(headers)}"
            )
        job_column = self.settings.google_forms_job_column
        mapping["job"] = self._find_header(
            headers,
            job_column,
            JOB_HEADER_ALIASES,
        )
        if mapping["job"] is None:
            raise ValueError(
                f"Required job-routing column '{job_column}' was not found. "
                "Add a required Google Form question such as 'Job Posting' "
                "and use a posting ID or an exact HireSense job title as its value. "
                f"Available headers: {', '.join(headers)}"
            )
        return mapping

    def _import_face(self, db, application, values, mapping, warnings):
        if mapping.get("photo") is None:
            return
        from app.services.candidate_identity import CandidateIdentityService
        candidate = db.get(Candidate, application.candidate_id)
        form_email = self._value(values, mapping.get("email")).strip().casefold()
        if not candidate or not candidate.email or form_email != candidate.email.casefold():
            warnings.append("Photo reference was not imported: application identity needs review.")
            return
        try:
            CandidateIdentityService(self.settings).import_photo(db, application, self.reader,
                self._drive_file_ids(self._value(values, mapping.get("photo"))))
        except Exception:
            # Photo failure must not fail CV intake or disclose biometric/provider data.
            warnings.append("Photo verification is unavailable; the interview can use manual identity confirmation.")

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

    def _resolve_posting(
        self,
        value: str,
        postings: list[tuple[JobPosting, JobDescription]],
    ) -> tuple[tuple[JobPosting, JobDescription] | None, str]:
        selected = value.strip()
        if not selected:
            return None, "Skipped response without a job posting value"

        posting_id: int | None = None
        if re.fullmatch(r"#?\d+", selected):
            posting_id = int(selected.lstrip("#"))
        else:
            match = re.search(
                r"(?:post(?:ing)?(?:\s+id)?|#)\s*#?\s*(\d+)",
                selected,
                flags=re.IGNORECASE,
            )
            if match:
                posting_id = int(match.group(1))

        if posting_id is not None:
            for posting, job in postings:
                if posting.id == posting_id:
                    return (posting, job), ""
            return None, (
                f"Skipped response for unknown or inaccessible posting ID "
                f"{posting_id}"
            )

        normalized_title = self._normalize(selected)
        title_matches = [
            (posting, job)
            for posting, job in postings
            if self._normalize(job.title) == normalized_title
        ]
        if len(title_matches) == 1:
            return title_matches[0], ""
        if len(title_matches) > 1:
            return None, (
                f"Skipped ambiguous job title '{selected}'; use a posting ID "
                "instead"
            )
        return None, (
            f"Skipped response for unknown job posting '{selected}'"
        )

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
        # Email is an unverified form field, not a global identity/ownership key.
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
    def _owned_postings(
        db: Session,
        *,
        interviewer_user_id: int,
    ) -> list[tuple[JobPosting, JobDescription]]:
        rows = db.execute(
            select(JobPosting, JobDescription)
            .join(
                JobDescription,
                JobDescription.id == JobPosting.job_description_id,
            )
            .where(
                JobDescription.created_by_user_id == interviewer_user_id,
            )
            .order_by(JobPosting.id)
        ).all()
        return [(posting, job) for posting, job in rows]

    @staticmethod
    def _existing_applications_by_row(
        db: Session,
        *,
        postings: list[tuple[JobPosting, JobDescription]],
        spreadsheet_id: str,
        sheet_name: str,
    ) -> dict[int, CandidateApplication]:
        posting_ids = [posting.id for posting, _ in postings]
        applications = db.scalars(
            select(CandidateApplication).where(
                CandidateApplication.job_posting_id.in_(posting_ids),
                CandidateApplication.source == ApplicationSource.GOOGLE_FORM,
            )
        )
        by_row: dict[int, CandidateApplication] = {}
        for application in applications:
            metadata = (application.response_data or {}).get(
                "_google_import",
                {},
            )
            if metadata.get("sheet_name") != sheet_name:
                continue
            stored_spreadsheet_id = metadata.get("spreadsheet_id")
            if stored_spreadsheet_id and stored_spreadsheet_id != spreadsheet_id:
                continue
            row_number = metadata.get("row_number")
            if isinstance(row_number, int):
                by_row[row_number] = application
        return by_row

    @staticmethod
    def _empty_result() -> dict[str, Any]:
        return {
            "imported_applications": 0,
            "reassigned_applications": 0,
            "skipped_existing": 0,
            "skipped_deleted": 0,
            "unmatched_responses": 0,
            "downloaded_cvs": 0,
            "issues": [],
        }
