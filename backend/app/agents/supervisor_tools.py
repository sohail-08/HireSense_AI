import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, ConfigDict, Field


ToolCallback = Callable[[str], dict[str, Any]]


@dataclass(frozen=True)
class InterviewRoomToolCallbacks:
    suggest_questions: ToolCallback
    help: ToolCallback
    analysis: ToolCallback | None = None


def build_interview_room_tools(callbacks: InterviewRoomToolCallbacks, *, user_message: str) -> list[BaseTool]:
    """A server-scoped allowlist, not the recruitment tools with a prompt warning."""

    @tool("suggest_interview_questions")
    def suggest_interview_questions(message: str) -> str:
        """Retrieve question-bank evidence and suggest JD-relevant questions or follow-ups.

        Uses only the interview authorized by the server. It cannot select a
        different candidate or job and cannot mutate recruitment business data.
        """
        return json.dumps(callbacks.suggest_questions(user_message), ensure_ascii=False)

    @tool("help")
    def interview_help(message: str) -> str:
        """Explain interview-room capabilities or decline unsupported business actions."""
        return json.dumps(callbacks.help(user_message), ensure_ascii=False)

    @tool("interview_analysis")
    def interview_analysis(message: str) -> str:
        """Score interview answers or read saved answer scores, assessments, requirement coverage and transcript evidence.

        Queue incremental analysis if missing or stale. Does not change rankings or contact candidates.
        """
        return json.dumps(callbacks.analysis(user_message), ensure_ascii=False)

    return [suggest_interview_questions, interview_help] + ([interview_analysis] if callbacks.analysis else [])


class ScreeningToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_posting_id: int | None = Field(default=None, gt=0)
    screening_scope: Literal["pending", "selected"] = "pending"
    needs_job_selection: bool = False


class ScreeningToolArguments(ScreeningToolRequest):
    message: str


@dataclass(frozen=True)
class SupervisorToolCallbacks:
    requirements: ToolCallback
    generate_job_description: ToolCallback
    edit_job_description: ToolCallback
    approve_job_description: ToolCallback
    job_posting: ToolCallback
    help: ToolCallback
    sync_responses: ToolCallback
    screen_candidates: Callable[[str, ScreeningToolRequest], dict[str, Any]]
    interviews: ToolCallback | None = None


def build_supervisor_tools(
    callbacks: SupervisorToolCallbacks, *, user_message: str,
) -> list[BaseTool]:
    """Bind native tools to this request's services, user, session, and message."""

    def result(callback: ToolCallback) -> str:
        # Business services always receive the real message, never an LLM rewrite.
        return json.dumps(callback(user_message), ensure_ascii=False, default=str)

    @tool("requirements")
    def requirements(message: str) -> str:
        """Discover, revise, or confirm hiring requirements using previous JDs.

        Use for role discovery, changes to requirements, or confirming the
        proposed requirement profile. Pass the complete interviewer message.
        """
        return result(callbacks.requirements)

    @tool("generate_job_description")
    def generate_job_description(message: str) -> str:
        """Generate a JD when the interviewer requests it after confirming requirements.

        Pass the complete interviewer message. Requirements must already be
        confirmed before the service can generate a job description.
        """
        return result(callbacks.generate_job_description)

    @tool("edit_job_description")
    def edit_job_description(message: str) -> str:
        """Edit the active JD from the interviewer's complete edit instruction.

        Use for an existing JD; use requirements for changing the requirement
        proposal. Editing an approved JD creates a new draft version.
        """
        return result(callbacks.edit_job_description)

    @tool("approve_job_description")
    def approve_job_description(message: str) -> str:
        """Approve the active JD draft only on explicit interviewer approval.

        Pass the complete interviewer message. To approve a Discord posting
        preview, use job_posting instead.
        """
        return result(callbacks.approve_job_description)

    @tool("job_posting")
    def job_posting(message: str) -> str:
        """Manage Discord posting: collect link/deadline, preview, revise, or approve.

        Pass the complete interviewer message. Publishing uses the existing
        approval workflow and Discord MCP server. Do not approve a JD here.
        """
        return result(callbacks.job_posting)

    @tool("sync_responses")
    def sync_responses(message: str) -> str:
        """Sync Google Form responses and download CVs into job-specific applications.

        Available in every phase and page. Sync only; this does not start
        candidate screening. Pass the complete interviewer message.
        """
        return result(callbacks.sync_responses)

    @tool("screen_candidates", args_schema=ScreeningToolArguments)
    def screen_candidates(
        message: str,
        job_posting_id: int | None = None,
        screening_scope: Literal["pending", "selected"] = "pending",
        needs_job_selection: bool = False,
    ) -> str:
        """Start CV parsing, requirement screening, and ranking for one job posting.

        Choose IDs only from available_screening_jobs. Use selected for checked
        applications and pending otherwise. Set needs_job_selection when a
        named job is ambiguous or absent. Leave job_posting_id null if no job
        was specified or selected. Pass the complete interviewer message.
        """
        request = ScreeningToolRequest(
            job_posting_id=job_posting_id,
            screening_scope=screening_scope,
            needs_job_selection=needs_job_selection,
        )
        return json.dumps(
            callbacks.screen_candidates(user_message, request),
            ensure_ascii=False, default=str,
        )

    @tool("help")
    def help_tool(message: str) -> str:
        """Explain valid next actions when no business tool applies to this request.

        Pass the complete interviewer message. Use for questions or requests
        outside the currently supported hiring workflows.
        """
        return result(callbacks.help)

    @tool("interviews")
    def interviews(message: str) -> str:
        """Select ranked candidates, collect interview times, preview invitations, explicitly confirm sending, or reschedule through MCP tools.

        Use at every page/phase for scheduling and invitation requests, or follow-ups
        while an interview selection/schedule/confirmation is pending. Pass the real
        interviewer message. Do not invent candidates, recipients or confirmation.
        """
        if not callbacks.interviews:
            raise ValueError("Interview scheduling is unavailable")
        return result(callbacks.interviews)

    tools = [
        requirements, generate_job_description, edit_job_description,
        approve_job_description, job_posting, sync_responses,
        screen_candidates, help_tool,
    ]
    return [*tools, interviews] if callbacks.interviews else tools
