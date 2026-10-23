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
    practical_tasks: ToolCallback | None = None


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

    @tool("suggest_practical_tasks")
    def suggest_practical_tasks(message: str) -> str:
        """Suggest 2–3 short practical-task choices for this interview's job, each at most 15 minutes.

        Only suggestions: never shares, starts, scores or approves a task. The human must select a choice.
        """
        return json.dumps(callbacks.practical_tasks(user_message), ensure_ascii=False)

    return [suggest_interview_questions, interview_help] + ([interview_analysis] if callbacks.analysis else []) + ([suggest_practical_tasks] if callbacks.practical_tasks else [])


class ScreeningToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_posting_id: int | None = Field(default=None, gt=0)
    screening_scope: Literal["pending", "selected"] = "pending"
    needs_job_selection: bool = False


class ScreeningToolArguments(ScreeningToolRequest):
    message: str


class AssessmentToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["show", "generate", "compare", "rank"] = "show"
    application_ids: list[int] = Field(default_factory=list, max_length=4)


class AssessmentToolArguments(AssessmentToolRequest):
    message: str


@dataclass(frozen=True)
class SupervisorToolCallbacks:
    generate_job_description: ToolCallback
    edit_job_description: ToolCallback
    approve_job_description: ToolCallback
    job_posting: ToolCallback
    help: ToolCallback
    sync_responses: ToolCallback
    screen_candidates: Callable[[str, ScreeningToolRequest], dict[str, Any]]
    interviews: ToolCallback | None = None
    assessments: Callable[[str, AssessmentToolRequest], dict[str, Any]] | None = None


def build_supervisor_tools(
    callbacks: SupervisorToolCallbacks, *, user_message: str,
) -> list[BaseTool]:
    """Bind native tools to this request's services, user, session, and message."""

    def result(callback: ToolCallback) -> str:
        # Business services always receive the real message, never an LLM rewrite.
        return json.dumps(callback(user_message), ensure_ascii=False, default=str)

    @tool("generate_job_description")
    def generate_job_description(message: str) -> str:
        """Draft a JD directly from relevant knowledge-base sources and the user's details.

        Use immediately for 'I want to hire an X' and follow-up job details when
        there is no current JD. The service asks for details if knowledge is
        missing. No separate requirements proposal or confirmation is needed.
        Pass the complete interviewer message.
        """
        return result(callbacks.generate_job_description)

    @tool("edit_job_description")
    def edit_job_description(message: str) -> str:
        """Edit the active JD from the interviewer's complete edit instruction.

        Use for an existing JD. Before a JD exists, use generate_job_description
        for additional details. Editing an approved JD creates a new draft version.
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
        generate_job_description, edit_job_description,
        approve_job_description, job_posting, sync_responses,
        screen_candidates, help_tool,
    ]
    @tool("candidate_assessments", args_schema=AssessmentToolArguments)
    def candidate_assessments(message: str, operation: Literal["show", "generate", "compare", "rank"] = "show", application_ids: list[int] = []) -> str:
        """Show saved consolidated candidate reports, generate a report from saved sources, or compare 2–4 applications for the same job.

        Use rank only when asked to calculate final rankings for the selected job. It scores saved interview answers when needed and combines interview 60% + CV 30% + practical task 10%.
        Show/generate/compare use saved sources. Never re-screen CVs, email or invent scores or weights.
        """
        if not callbacks.assessments: raise ValueError("Candidate reports are unavailable")
        return json.dumps(callbacks.assessments(user_message, AssessmentToolRequest(operation=operation, application_ids=application_ids)), ensure_ascii=False)

    return tools + ([interviews] if callbacks.interviews else []) + ([candidate_assessments] if callbacks.assessments else [])
