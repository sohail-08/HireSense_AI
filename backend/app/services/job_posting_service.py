import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.integrations.discord_mcp import (
    DiscordConfigurationError,
    DiscordDeliveryUncertainError,
    DiscordPublishError,
    DiscordPublishResult,
    DiscordMCPPublisher,
)
from app.models.job import (
    JobDescription,
    JobDescriptionStatus,
    JobPosting,
    JobPostingStatus,
)
from app.schemas.job_posting import DiscordPostPreviewRequest


DISCORD_CONTENT_LIMIT = 2000
DISCORD_EMBED_TITLE_LIMIT = 256
DISCORD_EMBED_DESCRIPTION_LIMIT = 4096
DISCORD_EMBED_FIELD_NAME_LIMIT = 256
DISCORD_EMBED_FIELD_VALUE_LIMIT = 1024
DISCORD_EMBED_FIELDS_LIMIT = 25
DISCORD_EMBED_TOTAL_LIMIT = 6000


class PublicationConflictError(RuntimeError):
    pass


class StaleJobDescriptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class DiscordPostOptions:
    heading: str
    application_url: str | None = None
    contact_email: str | None = None
    location: str | None = None
    application_deadline: date | None = None
    additional_instructions: str | None = None


@dataclass(frozen=True)
class ComposedDiscordPost:
    reviewed_content: str
    payload: dict[str, Any]


class DiscordJobPostComposer:
    def compose(
        self,
        *,
        job_title: str,
        job_description: str,
        options: DiscordPostOptions,
    ) -> ComposedDiscordPost:
        fields: list[dict[str, Any]] = []
        footer_lines: list[str] = []

        self._append_optional_field(
            fields,
            footer_lines,
            "Application link",
            options.application_url,
        )
        self._append_optional_field(
            fields,
            footer_lines,
            "Contact email",
            options.contact_email,
        )
        self._append_optional_field(
            fields,
            footer_lines,
            "Location",
            options.location,
        )
        self._append_optional_field(
            fields,
            footer_lines,
            "Application deadline",
            (
                options.application_deadline.isoformat()
                if options.application_deadline
                else None
            ),
        )
        self._append_optional_field(
            fields,
            footer_lines,
            "Additional application instructions",
            options.additional_instructions,
        )

        embed: dict[str, Any] = {
            "title": job_title,
            "description": job_description,
        }
        if fields:
            embed["fields"] = fields

        payload = {
            "content": options.heading,
            "embeds": [embed],
            "allowed_mentions": {"parse": []},
        }
        self._validate_payload(payload)

        reviewed_parts = [
            options.heading,
            job_title,
            job_description,
        ]
        if footer_lines:
            reviewed_parts.append("\n".join(footer_lines))

        return ComposedDiscordPost(
            reviewed_content="\n\n".join(reviewed_parts),
            payload=payload,
        )

    @staticmethod
    def _append_optional_field(
        fields: list[dict[str, Any]],
        footer_lines: list[str],
        name: str,
        value: str | None,
    ) -> None:
        if value is None or not value.strip():
            return
        normalized = value.strip()
        fields.append({"name": name, "value": normalized, "inline": False})
        footer_lines.append(f"{name}: {normalized}")

    @staticmethod
    def _validate_payload(payload: dict[str, Any]) -> None:
        content = payload["content"]
        embed = payload["embeds"][0]
        fields = embed.get("fields", [])

        if not content.strip():
            raise ValueError("Discord post heading cannot be empty")
        if len(content) > DISCORD_CONTENT_LIMIT:
            raise ValueError(
                f"Discord post heading exceeds {DISCORD_CONTENT_LIMIT} characters"
            )
        if len(embed["title"]) > DISCORD_EMBED_TITLE_LIMIT:
            raise ValueError(
                f"Job title exceeds Discord's {DISCORD_EMBED_TITLE_LIMIT}-character embed-title limit"
            )
        if len(embed["description"]) > DISCORD_EMBED_DESCRIPTION_LIMIT:
            raise ValueError(
                "Job description exceeds Discord's 4096-character embed-description limit"
            )
        if len(fields) > DISCORD_EMBED_FIELDS_LIMIT:
            raise ValueError("Discord job post contains too many footer fields")

        for field in fields:
            if len(field["name"]) > DISCORD_EMBED_FIELD_NAME_LIMIT:
                raise ValueError("A Discord footer label is too long")
            if len(field["value"]) > DISCORD_EMBED_FIELD_VALUE_LIMIT:
                raise ValueError(
                    f"{field['name']} exceeds Discord's 1024-character field limit"
                )

        embed_character_count = len(embed["title"]) + len(embed["description"])
        embed_character_count += sum(
            len(field["name"]) + len(field["value"])
            for field in fields
        )
        if embed_character_count > DISCORD_EMBED_TOTAL_LIMIT:
            raise ValueError(
                "The complete Discord embed exceeds the 6000-character combined limit"
            )


class DiscordJobPostingService:
    def __init__(
        self,
        publisher: DiscordMCPPublisher | None = None,
        composer: DiscordJobPostComposer | None = None,
    ):
        self.publisher = publisher or DiscordMCPPublisher()
        self.composer = composer or DiscordJobPostComposer()

    def preview(
        self,
        db: Session,
        *,
        data: DiscordPostPreviewRequest,
        interviewer_user_id: int,
    ) -> JobPosting:
        job = self._owned_approved_job(
            db,
            data.job_description_id,
            interviewer_user_id,
        )
        options = self._options(data)
        composed = self.composer.compose(
            job_title=job.title,
            job_description=job.content,
            options=options,
        )

        if data.posting_id is None:
            posting = JobPosting(
                job_description_id=job.id,
                platform="discord",
            )
            db.add(posting)
        else:
            posting = self._owned_posting(
                db,
                data.posting_id,
                interviewer_user_id,
            )
            if posting.job_description_id != job.id:
                raise LookupError("Discord job-post preview not found")
            if posting.status is not JobPostingStatus.DRAFT:
                raise PublicationConflictError(
                    "Published or attempted previews cannot be edited. Prepare a new post instead."
                )

        posting.heading = options.heading
        posting.application_url = options.application_url
        posting.contact_email = options.contact_email
        posting.location = options.location
        posting.application_deadline = options.application_deadline
        posting.additional_instructions = options.additional_instructions
        posting.reviewed_content = composed.reviewed_content
        posting.discord_payload = composed.payload
        posting.job_description_version = job.version
        posting.job_description_content_hash = self._job_snapshot_hash(job)
        posting.status = JobPostingStatus.DRAFT
        posting.error_code = None
        posting.error_message = None
        db.commit()
        db.refresh(posting)
        return posting

    def list_for_job(
        self,
        db: Session,
        *,
        job_description_id: int,
        interviewer_user_id: int,
    ) -> list[JobPosting]:
        self._owned_job(db, job_description_id, interviewer_user_id)
        return list(
            db.scalars(
                select(JobPosting)
                .where(
                    JobPosting.job_description_id == job_description_id,
                    JobPosting.platform == "discord",
                )
                .order_by(JobPosting.created_at.desc(), JobPosting.id.desc())
            )
        )

    def publish(
        self,
        db: Session,
        *,
        posting_id: int,
        interviewer_user_id: int,
    ) -> JobPosting:
        posting = self._owned_posting(
            db,
            posting_id,
            interviewer_user_id,
        )
        job = self._owned_approved_job(
            db,
            posting.job_description_id,
            interviewer_user_id,
        )
        if posting.status is not JobPostingStatus.DRAFT:
            raise PublicationConflictError(
                "This preview has already been published or attempted. Prepare a new post for another publication."
            )
        if (
            posting.job_description_version != job.version
            or posting.job_description_content_hash != self._job_snapshot_hash(job)
        ):
            raise StaleJobDescriptionError(
                "The job description changed after this preview. Prepare and review a new preview before publishing."
            )
        if not posting.discord_payload or not posting.reviewed_content:
            raise ValueError("Prepare and review the Discord post before publishing")

        claimed = db.execute(
            update(JobPosting)
            .where(
                JobPosting.id == posting.id,
                JobPosting.status == JobPostingStatus.DRAFT,
            )
            .values(
                status=JobPostingStatus.PUBLISHING,
                attempt_started_at=datetime.now(timezone.utc),
                error_code=None,
                error_message=None,
            )
        )
        if claimed.rowcount != 1:
            db.rollback()
            raise PublicationConflictError(
                "This preview is already being published or has already been attempted."
            )
        db.commit()

        try:
            result = self.publisher.publish(posting.discord_payload)
        except DiscordDeliveryUncertainError as exc:
            self._record_failure(
                db,
                posting.id,
                JobPostingStatus.UNCERTAIN,
                exc,
            )
            raise
        except (DiscordConfigurationError, DiscordPublishError) as exc:
            self._record_failure(
                db,
                posting.id,
                JobPostingStatus.FAILED,
                exc,
            )
            raise

        return self._record_success(db, posting.id, result)

    @staticmethod
    def _record_failure(
        db: Session,
        posting_id: int,
        status: JobPostingStatus,
        error: DiscordPublishError,
    ) -> None:
        db.execute(
            update(JobPosting)
            .where(JobPosting.id == posting_id)
            .values(
                status=status,
                error_code=error.code,
                error_message=error.safe_message,
            )
        )
        db.commit()

    @staticmethod
    def _record_success(
        db: Session,
        posting_id: int,
        result: DiscordPublishResult,
    ) -> JobPosting:
        message_url = None
        if result.guild_id and result.channel_id and result.message_id:
            message_url = (
                "https://discord.com/channels/"
                f"{result.guild_id}/{result.channel_id}/{result.message_id}"
            )

        posting = db.get(JobPosting, posting_id)
        if posting is None:
            raise DiscordDeliveryUncertainError(
                "publication_persistence_failed",
                "Discord accepted the post, but HireSense could not save its confirmation.",
            )
        posting.external_post_id = result.message_id
        posting.external_server_id = result.guild_id
        posting.external_channel_id = result.channel_id
        posting.external_url = message_url
        posting.status = JobPostingStatus.PUBLISHED
        posting.published_at = datetime.now(timezone.utc)
        try:
            db.commit()
            db.refresh(posting)
            return posting
        except SQLAlchemyError as exc:
            db.rollback()
            try:
                db.execute(
                    update(JobPosting)
                    .where(JobPosting.id == posting_id)
                    .values(
                        status=JobPostingStatus.UNCERTAIN,
                        error_code="publication_persistence_failed",
                        error_message=(
                            "Discord accepted the post, but HireSense could not save its confirmation."
                        ),
                    )
                )
                db.commit()
            except SQLAlchemyError:
                db.rollback()
            raise DiscordDeliveryUncertainError(
                "publication_persistence_failed",
                "Discord accepted the post, but HireSense could not save its confirmation.",
            ) from exc

    @staticmethod
    def _owned_job(
        db: Session,
        job_description_id: int,
        interviewer_user_id: int,
    ) -> JobDescription:
        job = db.get(JobDescription, job_description_id)
        if job is None or job.created_by_user_id != interviewer_user_id:
            raise LookupError("Job description not found")
        return job

    def _owned_approved_job(
        self,
        db: Session,
        job_description_id: int,
        interviewer_user_id: int,
    ) -> JobDescription:
        job = self._owned_job(db, job_description_id, interviewer_user_id)
        if job.status is not JobDescriptionStatus.APPROVED:
            raise ValueError("Approve the job description before preparing a post")
        return job

    @staticmethod
    def _owned_posting(
        db: Session,
        posting_id: int,
        interviewer_user_id: int,
    ) -> JobPosting:
        posting = db.scalar(
            select(JobPosting)
            .join(JobDescription)
            .where(
                JobPosting.id == posting_id,
                JobPosting.platform == "discord",
                JobDescription.created_by_user_id == interviewer_user_id,
            )
        )
        if posting is None:
            raise LookupError("Discord job-post preview not found")
        return posting

    @staticmethod
    def _job_snapshot_hash(job: JobDescription) -> str:
        snapshot = json.dumps(
            {
                "id": job.id,
                "version": job.version,
                "title": job.title,
                "content": job.content,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return sha256(snapshot.encode("utf-8")).hexdigest()

    @staticmethod
    def _options(data: DiscordPostPreviewRequest) -> DiscordPostOptions:
        settings = get_settings()
        supplied = data.model_fields_set

        def optional_value(field: str, default):
            return getattr(data, field) if field in supplied else default

        application_url = optional_value(
            "application_url",
            settings.job_post_default_application_url,
        )
        return DiscordPostOptions(
            heading=data.heading or settings.discord_default_heading,
            application_url=(
                str(application_url) if application_url is not None else None
            ),
            contact_email=(
                str(
                    optional_value(
                        "contact_email",
                        settings.job_post_default_contact_email,
                    )
                )
                if optional_value(
                    "contact_email",
                    settings.job_post_default_contact_email,
                )
                is not None
                else None
            ),
            location=optional_value(
                "location",
                settings.job_post_default_location,
            ),
            application_deadline=optional_value(
                "application_deadline",
                settings.job_post_default_application_deadline,
            ),
            additional_instructions=optional_value(
                "additional_instructions",
                settings.job_post_default_instructions,
            ),
        )
