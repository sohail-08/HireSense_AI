from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.job_posting import JobPostingAssistantGraph, PostingCommandModel
from app.agents.approval import is_explicit_approval
from app.models.job import JobDescription, JobPosting, JobPostingStatus
from app.schemas.job_posting import DiscordPostPreviewRequest
from app.services.job_posting_service import DiscordJobPostingService


class JobPostingAssistantService:
    def __init__(
        self,
        model: PostingCommandModel,
        posting_service: DiscordJobPostingService | None = None,
    ):
        self.model = model
        self.posting_service = posting_service or DiscordJobPostingService()

    def chat(
        self,
        db: Session,
        *,
        job_description_id: int,
        interviewer_user_id: int,
        message: str,
        posting_id: int | None = None,
    ) -> dict[str, Any]:
        job = self.posting_service._owned_approved_job(
            db,
            job_description_id,
            interviewer_user_id,
        )
        posting = self._draft_posting(
            db,
            job=job,
            interviewer_user_id=interviewer_user_id,
            posting_id=posting_id,
        )

        state = JobPostingAssistantGraph(self.model).invoke(
            message=message,
            current_application_url=(posting.application_url if posting else None),
            current_application_deadline=(
                posting.application_deadline if posting else None
            ),
        )
        if state.get("error"):
            raise RuntimeError(state["error"])

        action = state.get("action", "other")
        if action == "approve" and not is_explicit_approval(message):
            raise ValueError("Please explicitly approve the job post before publishing")
        missing = list(state.get("missing_fields", []))
        supplied_details = (
            state.get("application_url")
            != (posting.application_url if posting else None)
            or state.get("application_deadline")
            != (
                posting.application_deadline.isoformat()
                if posting and posting.application_deadline
                else None
            )
        )

        if action == "approve" and not supplied_details:
            if posting is None or missing:
                return self._details_response(posting, missing)
            self._validate_deadline(posting.application_deadline)
            published = self.posting_service.publish(
                db,
                posting_id=posting.id,
                interviewer_user_id=interviewer_user_id,
            )
            return {
                "status": "published",
                "assistant_message": (
                    "Approved and published to Discord successfully."
                ),
                "missing_fields": [],
                "posting": published,
            }

        if action == "reject":
            return {
                "status": "awaiting_changes",
                "assistant_message": (
                    "I will not publish it yet. Tell me the new application link "
                    "or deadline, then review the updated preview."
                ),
                "missing_fields": missing,
                "posting": posting,
            }

        if supplied_details:
            deadline = (
                date.fromisoformat(state["application_deadline"])
                if state.get("application_deadline")
                else None
            )
            if deadline is not None:
                self._validate_deadline(deadline)
            posting = self.posting_service.preview(
                db,
                data=DiscordPostPreviewRequest(
                    job_description_id=job.id,
                    posting_id=posting.id if posting else None,
                    application_url=state.get("application_url"),
                    application_deadline=deadline,
                ),
                interviewer_user_id=interviewer_user_id,
            )
            missing = []
            if not posting.application_url:
                missing.append("application_url")
            if not posting.application_deadline:
                missing.append("application_deadline")

        if missing:
            return self._details_response(posting, missing)

        if posting is not None:
            return {
                "status": "awaiting_approval",
                "assistant_message": (
                    "I prepared the Discord job post using the fixed company "
                    "posting details. Review the preview below. Type ‘approve’ "
                    "to publish it automatically, or tell me what link or "
                    "deadline to change."
                ),
                "missing_fields": [],
                "posting": posting,
            }

        return self._details_response(None, missing)

    def _draft_posting(
        self,
        db: Session,
        *,
        job: JobDescription,
        interviewer_user_id: int,
        posting_id: int | None,
    ) -> JobPosting | None:
        if posting_id is not None:
            posting = self.posting_service._owned_posting(
                db,
                posting_id,
                interviewer_user_id,
            )
            if posting.job_description_id != job.id:
                raise LookupError("Discord job-post preview not found")
            if posting.status is not JobPostingStatus.DRAFT:
                return None
            return posting

        return db.scalar(
            select(JobPosting)
            .where(
                JobPosting.job_description_id == job.id,
                JobPosting.platform == "discord",
                JobPosting.status == JobPostingStatus.DRAFT,
            )
            .order_by(JobPosting.created_at.desc(), JobPosting.id.desc())
        )

    @staticmethod
    def _details_response(
        posting: JobPosting | None,
        missing: list[str],
    ) -> dict[str, Any]:
        labels = {
            "application_url": "application link",
            "application_deadline": "application deadline",
        }
        needed = [labels[item] for item in missing]
        if not needed:
            needed = ["application link", "application deadline"]
        return {
            "status": "awaiting_details",
            "assistant_message": (
                "Please provide the " + " and ".join(needed) + "."
            ),
            "missing_fields": missing or [
                "application_url",
                "application_deadline",
            ],
            "posting": posting,
        }

    @staticmethod
    def _validate_deadline(deadline: date | None) -> None:
        if deadline is None:
            return
        if deadline < date.today():
            raise ValueError("Application deadline cannot be in the past")
