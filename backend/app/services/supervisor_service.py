from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.job_description import JobDescriptionEditModel
from app.agents.approval import is_explicit_approval
from app.agents.supervisor import (
    HireSenseSupervisorGraph,
    SupervisorChatModel,
)
from app.agents.supervisor_tools import (
    ScreeningToolRequest,
    SupervisorToolCallbacks,
    build_supervisor_tools,
)
from app.models.job import (
    JobDescription,
    JobDescriptionStatus,
    JobPosting,
    JobPostingStatus,
    RequirementProfile,
)
from app.models.supervisor import SupervisorSession
from app.models.screening import ScreeningBatch, ScreeningBatchStatus
from app.schemas.job import JobDescriptionUpdateRequest
from app.schemas.requirements import RequirementProfileDraft
from app.services.job_description_service import JobDescriptionService
from app.services.job_posting_assistant_service import JobPostingAssistantService
from app.services.requirement_discovery_service import RequirementDiscoveryService
from app.services.google_forms_intake_service import GoogleFormsIntakeService
from app.services.screening_service import ScreeningService


ToolMethod = Callable[[str], dict[str, Any]]


class SupervisorService:
    def __init__(
        self,
        *,
        model: SupervisorChatModel,
        requirement_service: RequirementDiscoveryService,
        job_description_service: JobDescriptionService,
        job_edit_model: JobDescriptionEditModel,
        job_posting_service: JobPostingAssistantService,
        candidate_intake_service: GoogleFormsIntakeService | None = None,
        candidate_intake_factory: Callable[[], GoogleFormsIntakeService] | None = None,
        screening_service: ScreeningService | None = None,
    ):
        self.model = model
        self.requirement_service = requirement_service
        self.job_description_service = job_description_service
        self.job_edit_model = job_edit_model
        self.job_posting_service = job_posting_service
        self.candidate_intake_service = candidate_intake_service
        self.candidate_intake_factory = candidate_intake_factory
        self.screening_service = screening_service

    def chat(
        self,
        db: Session,
        *,
        interviewer_user_id: int,
        message: str,
        session_id: str | None = None,
        selected_job_description_id: int | None = None,
        page_context: str = "jobs",
        selected_job_posting_id: int | None = None,
        selected_application_ids: list[int] | None = None,
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
        state_json["page_context"] = page_context
        state_json["selected_screening_job_posting_id"] = selected_job_posting_id
        state_json["selected_application_ids"] = selected_application_ids or []
        supervisor.state_json = state_json
        messages = list(state_json.get("messages", []))
        messages.append(
            {"role": "user", "content": message.strip(), "outcome": "info"}
        )

        callbacks = SupervisorToolCallbacks(
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
            sync_responses=self._safe_tool(
                supervisor,
                lambda text: self._sync_tool(db, supervisor, interviewer_user_id),
                preserve_phase=True,
            ),
            screen_candidates=lambda text, decision: self._safe_tool(
                supervisor,
                lambda _: self._screening_tool(
                    db, supervisor, interviewer_user_id, decision,
                ),
                preserve_phase=True,
            )(text),
        )
        tools = build_supervisor_tools(callbacks, user_message=message.strip())
        graph_state = HireSenseSupervisorGraph(self.model, tools).invoke(
            message=message,
            context=self._routing_context(db, supervisor, messages),
        )
        result = graph_state.get("tool_result") or {
            "phase": "error",
            "outcome": "failure",
            "assistant_message": "The supervisor produced no result.",
            "refresh_required": False,
        }
        assistant_message = graph_state.get("final_response") or result["assistant_message"]

        supervisor.phase = result.get("phase", supervisor.phase)
        state_json = dict(supervisor.state_json or {})
        requirement_state = result.get("requirement_state")
        if requirement_state is not None:
            state_json["requirement_state"] = requirement_state
        state_json["last_route"] = graph_state.get("tool_name", "route_error")
        state_json["last_route_reason"] = "Gemini native tool calling with ToolNode execution"
        state_json["last_tool_call"] = graph_state.get("tool_call")
        messages.append(
            {
                "role": "assistant",
                "content": assistant_message,
                "outcome": result.get("outcome", "info"),
            }
        )
        state_json["messages"] = messages[-100:]
        supervisor.state_json = state_json
        db.commit()
        db.refresh(supervisor)

        response = self._response(
            db,
            supervisor=supervisor,
            route=state_json["last_route"],
            assistant_message=assistant_message,
            outcome=result.get("outcome", "info"),
            refresh_required=result.get("refresh_required", False),
        )
        response["sync_result"] = result.get("sync_result")
        response["screening_batch"] = result.get("screening_batch") or response.get("screening_batch")
        # Internal signal: the HTTP route queues work only for a newly created batch.
        response["screening_started"] = result.get("screening_started", False)
        return response

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
        message: str,
    ) -> dict[str, Any]:
        if not is_explicit_approval(message):
            return self._failure(
                supervisor,
                "Please explicitly approve the job description before I approve it.",
            )
        if supervisor.phase in {"posting_details", "posting_approval", "published"}:
            return self._failure(
                supervisor,
                "The current confirmation belongs to job posting, not JD approval.",
            )
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
            ) + " You can also ask me to sync responses or screen candidates for a job posting.",
            "refresh_required": False,
        }

    def _sync_tool(
        self, db: Session, supervisor: SupervisorSession, interviewer_user_id: int,
    ) -> dict[str, Any]:
        service = self.candidate_intake_service
        if service is None and self.candidate_intake_factory:
            service = self.candidate_intake_factory()
        if service is None:
            raise RuntimeError("Candidate response sync is unavailable")
        result = service.sync(
            db, interviewer_user_id=interviewer_user_id,
        )
        warnings = result["issues"]
        message = (
            f"Synced responses: imported {result['imported_applications']} application(s), "
            f"downloaded {result['downloaded_cvs']} CV(s), reassigned "
            f"{result['reassigned_applications']} application(s), and skipped "
            f"{result['skipped_existing']} unchanged and {result['skipped_deleted']} "
            "previously deleted response(s)."
        )
        if warnings:
            message += f" {len(warnings)} warning(s): " + "; ".join(
                f"Row {item['row_number']}: {item['message']}" for item in warnings[:5]
            )
        return {
            "phase": supervisor.phase,
            "outcome": "failure" if warnings and not result["imported_applications"] else "success",
            "assistant_message": message,
            "refresh_required": True,
            "sync_result": result,
        }

    def _screening_tool(
        self, db: Session, supervisor: SupervisorSession,
        interviewer_user_id: int, decision: ScreeningToolRequest,
    ) -> dict[str, Any]:
        if self.screening_service is None:
            raise RuntimeError("Candidate screening is unavailable")
        jobs = self.screening_service.list_jobs(db, interviewer_user_id=interviewer_user_id)
        state = dict(supervisor.state_json or {})
        posting_id = decision.job_posting_id or state.get("selected_screening_job_posting_id")
        if posting_id is None and len(jobs) == 1 and not decision.needs_job_selection:
            posting_id = jobs[0]["id"]
        job = next((item for item in jobs if item["id"] == posting_id), None)
        if decision.needs_job_selection or job is None:
            state["pending_screening_selection"] = True
            supervisor.state_json = state
            choices = "; ".join(f"{item['title']} (Post #{item['id']})" for item in jobs)
            return {
                "phase": supervisor.phase,
                "outcome": "info",
                "assistant_message": (
                    "Which job posting should I screen? " + choices
                    if jobs else "Create a job posting and collect applications before screening."
                ),
                "refresh_required": False,
            }
        application_ids = None
        if decision.screening_scope == "selected":
            # Checked applications only belong to the job currently shown in the UI.
            if state.get("selected_screening_job_posting_id") != posting_id:
                raise ValueError("Select that job on Assessments and check the applications to screen")
            application_ids = state.get("selected_application_ids", [])
            if not application_ids:
                raise ValueError("Check at least one application on Assessments, or ask to screen all pending candidates")
        active = db.scalar(select(ScreeningBatch).where(
            ScreeningBatch.job_posting_id == posting_id,
            ScreeningBatch.created_by_user_id == interviewer_user_id,
            ScreeningBatch.status.in_([ScreeningBatchStatus.QUEUED, ScreeningBatchStatus.PROCESSING]),
        ))
        if active:
            raise ValueError(f"Screening batch #{active.id} is already running for this job")
        batch = self.screening_service.create_batch(
            db, interviewer_user_id=interviewer_user_id,
            job_posting_id=posting_id, application_ids=application_ids,
        )
        state["pending_screening_selection"] = False
        state["last_screening_batch_id"] = batch.id
        supervisor.state_json = state
        return {
            "phase": supervisor.phase,
            "outcome": "success",
            "assistant_message": (
                f"Started screening batch #{batch.id} for {batch.total_applications} "
                f"application(s) under “{job['title']}” (Post #{posting_id}). "
                "I’ll refresh the requirement matches and ranking when processing finishes."
            ),
            "refresh_required": True,
            "screening_started": True,
            "screening_batch": self.screening_service.get_batch(
                db, interviewer_user_id=interviewer_user_id, batch_id=batch.id,
            ),
        }

    @staticmethod
    def _safe_tool(
        supervisor: SupervisorSession,
        callback: ToolMethod,
        *,
        preserve_phase: bool = False,
    ) -> ToolMethod:
        def invoke(message: str) -> dict[str, Any]:
            try:
                return callback(message)
            except (LookupError, PermissionError, RuntimeError, ValueError) as exc:
                return {
                    "phase": supervisor.phase if preserve_phase else "error",
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
            "page_context": (supervisor.state_json or {}).get("page_context", "jobs"),
            "selected_screening_job_posting_id": (supervisor.state_json or {}).get("selected_screening_job_posting_id"),
            "selected_application_ids": (supervisor.state_json or {}).get("selected_application_ids", []),
            "pending_screening_selection": (supervisor.state_json or {}).get("pending_screening_selection", False),
            "available_screening_jobs": self.screening_service.list_jobs(
                db, interviewer_user_id=supervisor.interviewer_user_id,
            ) if self.screening_service else [],
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
        screening_batch = None
        if self.screening_service and state_json.get("last_screening_batch_id"):
            try:
                screening_batch = self.screening_service.get_batch(
                    db, interviewer_user_id=supervisor.interviewer_user_id,
                    batch_id=state_json["last_screening_batch_id"],
                )
            except LookupError:
                pass
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
            "screening_batch": screening_batch,
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
