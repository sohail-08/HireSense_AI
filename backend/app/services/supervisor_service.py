from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.job_description import JobDescriptionEditModel
from app.agents.supervisor import (
    HireSenseSupervisorGraph,
    SupervisorRouterModel,
    SupervisorTools,
)
from app.models.job import (
    JobDescription,
    JobDescriptionStatus,
    JobPosting,
    JobPostingStatus,
    RequirementProfile,
)
from app.models.supervisor import SupervisorSession
from app.schemas.job import JobDescriptionUpdateRequest
from app.schemas.requirements import RequirementProfileDraft
from app.services.job_description_service import JobDescriptionService
from app.services.job_posting_assistant_service import JobPostingAssistantService
from app.services.requirement_discovery_service import RequirementDiscoveryService


ToolMethod = Callable[[str], dict[str, Any]]


class SupervisorService:
    def __init__(
        self,
        *,
        router: SupervisorRouterModel,
        requirement_service: RequirementDiscoveryService,
        job_description_service: JobDescriptionService,
        job_edit_model: JobDescriptionEditModel,
        job_posting_service: JobPostingAssistantService,
    ):
        self.router = router
        self.requirement_service = requirement_service
        self.job_description_service = job_description_service
        self.job_edit_model = job_edit_model
        self.job_posting_service = job_posting_service

    def chat(
        self,
        db: Session,
        *,
        interviewer_user_id: int,
        message: str,
        session_id: str | None = None,
        selected_job_description_id: int | None = None,
    ) -> dict[str, Any]:
        supervisor = self._get_or_create_session(
            db,
            interviewer_user_id=interviewer_user_id,
            session_id=session_id,
        )
        if selected_job_description_id is not None:
            self._select_job_description(
                db,
                supervisor=supervisor,
                interviewer_user_id=interviewer_user_id,
                job_description_id=selected_job_description_id,
            )

        state_json = dict(supervisor.state_json or {})
        messages = list(state_json.get("messages", []))
        messages.append(
            {"role": "user", "content": message.strip(), "outcome": "info"}
        )

        tools = SupervisorTools(
            requirements=self._safe_tool(
                supervisor,
                lambda text: self._requirements_tool(
                    db,
                    supervisor,
                    interviewer_user_id,
                    text,
                ),
            ),
            generate_job_description=self._safe_tool(
                supervisor,
                lambda text: self._generate_tool(
                    db,
                    supervisor,
                    interviewer_user_id,
                    text,
                ),
            ),
            edit_job_description=self._safe_tool(
                supervisor,
                lambda text: self._edit_tool(
                    db,
                    supervisor,
                    interviewer_user_id,
                    text,
                ),
            ),
            approve_job_description=self._safe_tool(
                supervisor,
                lambda text: self._approve_job_description_tool(
                    db,
                    supervisor,
                    interviewer_user_id,
                    text,
                ),
            ),
            job_posting=self._safe_tool(
                supervisor,
                lambda text: self._posting_tool(
                    db,
                    supervisor,
                    interviewer_user_id,
                    text,
                ),
            ),
            help=self._safe_tool(
                supervisor,
                lambda text: self._help_tool(supervisor, text),
            ),
        )
        graph_state = HireSenseSupervisorGraph(self.router, tools).invoke(
            message=message,
            context=self._routing_context(db, supervisor, messages),
        )
        result = graph_state.get("tool_result") or {
            "phase": "error",
            "outcome": "failure",
            "assistant_message": "The supervisor produced no result.",
            "refresh_required": False,
        }

        supervisor.phase = result.get("phase", supervisor.phase)
        requirement_state = result.get("requirement_state")
        if requirement_state is not None:
            state_json["requirement_state"] = requirement_state
        state_json["last_route"] = graph_state.get("action", "route_error")
        state_json["last_route_reason"] = graph_state.get("route_reason")
        messages.append(
            {
                "role": "assistant",
                "content": result["assistant_message"],
                "outcome": result.get("outcome", "info"),
            }
        )
        state_json["messages"] = messages[-100:]
        supervisor.state_json = state_json
        db.commit()
        db.refresh(supervisor)

        return self._response(
            db,
            supervisor=supervisor,
            route=state_json["last_route"],
            assistant_message=result["assistant_message"],
            outcome=result.get("outcome", "info"),
            refresh_required=result.get("refresh_required", False),
        )

    def get_session(
        self,
        db: Session,
        *,
        interviewer_user_id: int,
        session_id: str,
    ) -> dict[str, Any]:
        supervisor = db.get(SupervisorSession, session_id)
        if (
            supervisor is None
            or supervisor.interviewer_user_id != interviewer_user_id
        ):
            raise LookupError("Supervisor session not found")
        messages = list((supervisor.state_json or {}).get("messages", []))
        assistant_message = (
            messages[-1]["content"]
            if messages and messages[-1].get("role") == "assistant"
            else "Supervisor session restored."
        )
        return self._response(
            db,
            supervisor=supervisor,
            route="restore",
            assistant_message=assistant_message,
            outcome="info",
            refresh_required=True,
        )

    @staticmethod
    def _get_or_create_session(
        db: Session,
        *,
        interviewer_user_id: int,
        session_id: str | None,
    ) -> SupervisorSession:
        supervisor = db.get(SupervisorSession, session_id) if session_id else None
        if supervisor is not None:
            if supervisor.interviewer_user_id != interviewer_user_id:
                raise PermissionError("Supervisor session belongs to another interviewer")
            return supervisor
        if session_id is not None:
            raise LookupError("Supervisor session not found")

        supervisor = SupervisorSession(
            interviewer_user_id=interviewer_user_id,
            phase="requirements",
            state_json={"messages": []},
        )
        db.add(supervisor)
        db.flush()
        return supervisor

    def _select_job_description(
        self,
        db: Session,
        *,
        supervisor: SupervisorSession,
        interviewer_user_id: int,
        job_description_id: int,
    ) -> None:
        job = self.job_description_service.get_for_interviewer(
            db,
            job_description_id=job_description_id,
            interviewer_user_id=interviewer_user_id,
        )
        if supervisor.job_description_id != job.id:
            supervisor.job_posting_id = None
        supervisor.job_description_id = job.id
        supervisor.requirement_profile_id = job.requirement_profile_id

        if job.status is JobDescriptionStatus.DRAFT:
            supervisor.phase = "job_description_draft"
            return

        latest_posting = db.scalar(
            select(JobPosting)
            .where(
                JobPosting.job_description_id == job.id,
                JobPosting.platform == "discord",
            )
            .order_by(JobPosting.created_at.desc(), JobPosting.id.desc())
        )
        supervisor.job_posting_id = latest_posting.id if latest_posting else None
        if latest_posting is None:
            supervisor.phase = "job_description_approved"
        elif latest_posting.status is JobPostingStatus.DRAFT:
            supervisor.phase = (
                "posting_approval"
                if latest_posting.application_url
                and latest_posting.application_deadline
                else "posting_details"
            )
        elif latest_posting.status is JobPostingStatus.PUBLISHED:
            supervisor.phase = "published"
        else:
            supervisor.phase = "job_description_approved"

    def _requirements_tool(
        self,
        db: Session,
        supervisor: SupervisorSession,
        interviewer_user_id: int,
        message: str,
    ) -> dict[str, Any]:
        requirement_session, result = self.requirement_service.chat(
            db,
            interviewer_user_id=interviewer_user_id,
            message=message,
            session_id=supervisor.requirement_session_id,
        )
        supervisor.requirement_session_id = requirement_session.id
        supervisor.requirement_profile_id = requirement_session.requirement_profile_id

        status = result["status"]
        if status == "confirmed":
            phase = "requirement_confirmed"
        elif status == "awaiting_confirmation":
            phase = "requirement_confirmation"
        elif status == "error":
            phase = "error"
        else:
            phase = "requirements"

        return {
            "phase": phase,
            "outcome": "failure" if status == "error" else "info",
            "assistant_message": result["assistant_message"],
            "requirement_state": self._requirement_result(result),
            "refresh_required": bool(requirement_session.requirement_profile_id),
        }

    def _generate_tool(
        self,
        db: Session,
        supervisor: SupervisorSession,
        interviewer_user_id: int,
        _message: str,
    ) -> dict[str, Any]:
        if supervisor.requirement_profile_id is None:
            return self._failure(
                supervisor,
                "Confirm the job requirements before generating a job description.",
            )

        current = self._current_job(db, supervisor, interviewer_user_id)
        if current is not None and current.requirement_profile_id == (
            supervisor.requirement_profile_id
        ):
            return self._failure(
                supervisor,
                "A job description already exists for these requirements. "
                "Ask me to edit it or approve the current draft.",
            )

        job = self.job_description_service.generate(
            db,
            requirement_profile_id=supervisor.requirement_profile_id,
            interviewer_user_id=interviewer_user_id,
        )
        supervisor.job_description_id = job.id
        supervisor.job_posting_id = None
        return {
            "phase": "job_description_draft",
            "outcome": "success",
            "assistant_message": (
                f"Generated job description “{job.title}” version {job.version}. "
                "Review it, ask me for edits, or tell me to approve it."
            ),
            "refresh_required": True,
        }

    def _edit_tool(
        self,
        db: Session,
        supervisor: SupervisorSession,
        interviewer_user_id: int,
        message: str,
    ) -> dict[str, Any]:
        job = self._current_job(db, supervisor, interviewer_user_id)
        if job is None:
            return self._failure(
                supervisor,
                "Generate or select a job description before requesting edits.",
            )
        if job.status is JobDescriptionStatus.APPROVED:
            job = self.job_description_service.revise(
                db,
                job_description_id=job.id,
                interviewer_user_id=interviewer_user_id,
            )
            supervisor.job_description_id = job.id
            supervisor.job_posting_id = None

        revised = self.job_edit_model.edit(
            current_title=job.title,
            current_content=job.content,
            current_structured_content=dict(job.structured_content),
            instruction=message,
        )
        job = self.job_description_service.update_draft(
            db,
            job_description_id=job.id,
            interviewer_user_id=interviewer_user_id,
            update=JobDescriptionUpdateRequest(structured_content=revised),
        )
        return {
            "phase": "job_description_draft",
            "outcome": "success",
            "assistant_message": (
                f"Updated “{job.title}” version {job.version}. "
                "Review the refreshed draft before approval."
            ),
            "refresh_required": True,
        }

    def _approve_job_description_tool(
        self,
        db: Session,
        supervisor: SupervisorSession,
        interviewer_user_id: int,
        _message: str,
    ) -> dict[str, Any]:
        job = self._current_job(db, supervisor, interviewer_user_id)
        if job is None:
            return self._failure(
                supervisor,
                "Generate or select a draft job description before approval.",
            )
        if job.status is JobDescriptionStatus.APPROVED:
            return {
                "phase": "job_description_approved",
                "outcome": "info",
                "assistant_message": (
                    f"“{job.title}” is already approved. Tell me to post the job "
                    "when you are ready."
                ),
                "refresh_required": False,
            }
        job = self.job_description_service.approve(
            db,
            job_description_id=job.id,
            interviewer_user_id=interviewer_user_id,
        )
        return {
            "phase": "job_description_approved",
            "outcome": "success",
            "assistant_message": (
                f"Approved “{job.title}” version {job.version}. "
                "Tell me to post the job when you are ready."
            ),
            "refresh_required": True,
        }

    def _posting_tool(
        self,
        db: Session,
        supervisor: SupervisorSession,
        interviewer_user_id: int,
        message: str,
    ) -> dict[str, Any]:
        job = self._current_job(db, supervisor, interviewer_user_id)
        if job is None or job.status is not JobDescriptionStatus.APPROVED:
            return self._failure(
                supervisor,
                "Approve a job description before preparing a job post.",
            )
        posting = self._current_posting(db, supervisor)
        posting_id = (
            posting.id
            if posting is not None and posting.status is JobPostingStatus.DRAFT
            else None
        )
        result = self.job_posting_service.chat(
            db,
            job_description_id=job.id,
            interviewer_user_id=interviewer_user_id,
            message=message,
            posting_id=posting_id,
        )
        posting = result.get("posting")
        if posting is not None:
            supervisor.job_posting_id = posting.id
        phase_by_status = {
            "awaiting_details": "posting_details",
            "awaiting_approval": "posting_approval",
            "awaiting_changes": "posting_approval",
            "published": "published",
        }
        return {
            "phase": phase_by_status[result["status"]],
            "outcome": "success" if result["status"] == "published" else "info",
            "assistant_message": result["assistant_message"],
            "refresh_required": posting is not None,
        }

    @staticmethod
    def _help_tool(
        supervisor: SupervisorSession,
        _message: str,
    ) -> dict[str, Any]:
        guidance = {
            "requirements": "Tell me the role you want to hire for.",
            "requirement_confirmation": (
                "Review the proposed requirements, request changes, or confirm them."
            ),
            "requirement_confirmed": (
                "Ask me to generate the job description."
            ),
            "job_description_draft": (
                "Ask me to edit the current draft or approve it."
            ),
            "job_description_approved": (
                "Ask me to post the approved job to Discord."
            ),
            "posting_details": (
                "Provide the application link and application deadline."
            ),
            "posting_approval": (
                "Review the post preview, then approve it or request a change."
            ),
            "published": (
                "The current post is published. Start a new hiring workflow "
                "for another role or explicitly prepare another publication."
            ),
            "error": "Retry the last request or start a new workflow.",
        }
        return {
            "phase": supervisor.phase,
            "outcome": "info",
            "assistant_message": guidance.get(
                supervisor.phase,
                "Tell me what hiring task you want to perform.",
            ),
            "refresh_required": False,
        }

    @staticmethod
    def _safe_tool(
        supervisor: SupervisorSession,
        callback: ToolMethod,
    ) -> ToolMethod:
        def invoke(message: str) -> dict[str, Any]:
            try:
                return callback(message)
            except (LookupError, PermissionError, RuntimeError, ValueError) as exc:
                return {
                    "phase": "error",
                    "outcome": "failure",
                    "assistant_message": f"The task failed: {exc}",
                    "refresh_required": True,
                }

        return invoke

    def _routing_context(
        self,
        db: Session,
        supervisor: SupervisorSession,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        job = self._current_job(
            db,
            supervisor,
            supervisor.interviewer_user_id,
        )
        posting = self._current_posting(db, supervisor)
        requirement_state = (supervisor.state_json or {}).get(
            "requirement_state",
            {},
        )
        return {
            "phase": supervisor.phase,
            "requirement_profile_confirmed": (
                supervisor.requirement_profile_id is not None
            ),
            "missing_requirement_fields": requirement_state.get(
                "missing_fields",
                [],
            ),
            "job_description": (
                {
                    "id": job.id,
                    "title": job.title,
                    "status": job.status.value,
                    "version": job.version,
                }
                if job
                else None
            ),
            "job_posting": (
                {
                    "id": posting.id,
                    "status": posting.status.value,
                    "has_application_url": bool(posting.application_url),
                    "has_application_deadline": bool(
                        posting.application_deadline
                    ),
                }
                if posting
                else None
            ),
            "recent_messages": messages[-8:],
        }

    def _response(
        self,
        db: Session,
        *,
        supervisor: SupervisorSession,
        route: str,
        assistant_message: str,
        outcome: str,
        refresh_required: bool,
    ) -> dict[str, Any]:
        state_json = supervisor.state_json or {}
        return {
            "session_id": supervisor.id,
            "phase": supervisor.phase,
            "route": route,
            "assistant_message": assistant_message,
            "outcome": outcome,
            "messages": state_json.get("messages", []),
            "requirement_profile_id": supervisor.requirement_profile_id,
            "requirement_state": self._requirement_state(db, supervisor),
            "job_description": self._current_job(
                db,
                supervisor,
                supervisor.interviewer_user_id,
            ),
            "job_posting": self._current_posting(db, supervisor),
            "refresh_required": refresh_required,
        }

    def _requirement_state(
        self,
        db: Session,
        supervisor: SupervisorSession,
    ) -> dict[str, Any]:
        saved = (supervisor.state_json or {}).get("requirement_state")
        if saved is not None:
            return saved
        if supervisor.requirement_profile_id is None:
            return self._empty_requirement_state()
        profile = db.get(RequirementProfile, supervisor.requirement_profile_id)
        if profile is None:
            return self._empty_requirement_state()
        return {
            "profile": {
                "title": profile.title,
                "summary": profile.summary,
                "required_skills": profile.required_skills,
                "preferred_skills": profile.preferred_skills,
                "qualifications": profile.qualifications,
                "min_years_experience": profile.min_years_experience,
                "selection_criteria": profile.selection_criteria,
            },
            "missing_fields": [],
            "knowledge_status": profile.generation_metadata.get(
                "knowledge_status",
                "not_searched",
            ),
            "proposal_ready": True,
            "source_references": profile.source_references,
        }

    @staticmethod
    def _requirement_result(result: dict[str, Any]) -> dict[str, Any]:
        profile = result["profile"]
        if isinstance(profile, RequirementProfileDraft):
            profile = profile.model_dump(mode="json")
        return {
            "profile": profile,
            "missing_fields": result["missing_fields"],
            "knowledge_status": result["knowledge_status"],
            "proposal_ready": result["proposal_ready"],
            "source_references": result["source_references"],
        }

    @staticmethod
    def _empty_requirement_state() -> dict[str, Any]:
        return {
            "profile": RequirementProfileDraft().model_dump(mode="json"),
            "missing_fields": [
                "title",
                "required_skills",
                "qualifications",
                "experience",
                "selection_criteria",
            ],
            "knowledge_status": "not_searched",
            "proposal_ready": False,
            "source_references": [],
        }

    def _current_job(
        self,
        db: Session,
        supervisor: SupervisorSession,
        interviewer_user_id: int,
    ) -> JobDescription | None:
        if supervisor.job_description_id is None:
            return None
        try:
            return self.job_description_service.get_for_interviewer(
                db,
                job_description_id=supervisor.job_description_id,
                interviewer_user_id=interviewer_user_id,
            )
        except LookupError:
            return None

    @staticmethod
    def _current_posting(
        db: Session,
        supervisor: SupervisorSession,
    ) -> JobPosting | None:
        if supervisor.job_posting_id is None:
            return None
        return db.get(JobPosting, supervisor.job_posting_id)

    @staticmethod
    def _failure(
        supervisor: SupervisorSession,
        message: str,
    ) -> dict[str, Any]:
        return {
            "phase": supervisor.phase,
            "outcome": "failure",
            "assistant_message": message,
            "refresh_required": False,
        }
