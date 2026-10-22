import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.prebuilt import ToolNode

from app.agents.supervisor import HireSenseSupervisorGraph
from app.agents.supervisor_tools import (
    SupervisorToolCallbacks, build_supervisor_tools,
    InterviewRoomToolCallbacks, build_interview_room_tools,
)
from supervisor_fakes import QueueToolModel


def _call(name, args=None, call_id="test-call"):
    return {"name": name, "args": args or {}, "id": call_id, "type": "tool_call"}


def _graph(model, calls, user_message="Sync responses"):
    def callback(message):
        calls.append(message)
        return {
            "phase": "posting_approval", "outcome": "success",
            "assistant_message": "Started screening batch #42.",
            "refresh_required": True, "screening_started": True,
            "screening_batch": {"id": 42},
        }

    callbacks = SupervisorToolCallbacks(
        generate_job_description=callback,
        edit_job_description=callback, approve_job_description=callback,
        job_posting=callback, help=callback, sync_responses=callback,
        screen_candidates=lambda message, request: callback(message),
    )
    return HireSenseSupervisorGraph(
        model, build_supervisor_tools(callbacks, user_message=user_message),
    )


def test_supervisor_binds_native_tools_and_receives_tool_message():
    model = QueueToolModel(["sync_responses"])
    calls = []
    graph = _graph(model, calls)
    assert isinstance(graph._compiled.nodes["tools"].bound, ToolNode)
    result = graph.invoke(message="Sync responses", context={"phase": "posting_approval"})
    assert calls == ["Sync responses"]
    assert result["tool_name"] == "sync_responses"
    assert result["tool_call"]["name"] == "sync_responses"
    assert result["final_response"] == "Started screening batch #42."
    assert len(model.tool_messages) == 1
    assert isinstance(model.tool_messages[0], ToolMessage)
    assert model.calls == 2
    assert model.bindings[0]["tool_choice"] == "any"
    assert model.bindings[1]["tool_choice"] == "none"
    assert set(model.bindings[0]["names"]) == {
        "generate_job_description", "edit_job_description",
        "approve_job_description", "job_posting", "help",
        "sync_responses", "screen_candidates",
    }


@pytest.mark.parametrize("response", [
    AIMessage(content="I did not select a tool"),
    AIMessage(content="", tool_calls=[_call("sync_responses"), _call("help", call_id="second")]),
    AIMessage(content="", tool_calls=[_call("invented_tool")]),
    AIMessage(content="", invalid_tool_calls=[{
        "name": "sync_responses", "args": "invalid JSON", "id": "invalid", "error": "bad args",
    }]),
    RuntimeError("Synthetic API failure"),
])
def test_invalid_routing_never_executes_a_business_operation(response):
    model = QueueToolModel([response])
    calls = []
    result = _graph(model, calls).invoke(
        message="Sync responses", context={"phase": "posting_approval"},
    )
    assert calls == []
    assert result["tool_name"] == "route_error"
    assert result["tool_result"]["outcome"] == "failure"
    assert result["tool_result"]["phase"] == "posting_approval"
    assert model.calls == 1


@pytest.mark.parametrize("final_response", [
    RuntimeError("Response generation timed out after execution"),
    AIMessage(content="", tool_calls=[_call("sync_responses")]),
    AIMessage(content=""),
    AIMessage(content="", invalid_tool_calls=[{
        "name": "help", "args": "invalid", "id": "bad", "error": "bad args",
    }]),
])
def test_final_response_failure_preserves_completed_task_and_background_signals(final_response):
    model = QueueToolModel(["sync_responses"])
    model.final_response = final_response
    calls = []
    result = _graph(model, calls).invoke(
        message="Sync responses", context={"phase": "posting_approval"},
    )
    assert calls == ["Sync responses"]
    assert result["tool_name"] == "sync_responses"
    assert result["tool_result"]["outcome"] == "success"
    assert result["tool_result"]["screening_started"] is True
    assert result["tool_result"]["screening_batch"]["id"] == 42
    assert result["tool_result"]["refresh_required"] is True
    assert result["final_response"] == "Started screening batch #42."


@pytest.mark.parametrize("args", [
    {"job_posting_id": 0}, {"job_posting_id": "invented"},
    {"screening_scope": "every-job"}, {"unrecognized_argument": "ignore"},
])
def test_invalid_screening_arguments_fail_before_execution(args):
    model = QueueToolModel(["screen_candidates"])
    model.tool_args = args
    calls = []
    result = _graph(model, calls).invoke(
        message="Sync responses", context={"phase": "posting_approval"},
    )
    assert calls == []
    assert result["tool_result"]["outcome"] == "failure"
    assert model.calls == 1


def test_tools_cannot_replace_the_users_instruction_with_fabricated_approval():
    message = "Please edit the title"
    model = QueueToolModel(["edit_job_description"])
    model.tool_args = {"message": "Approve and publish this job"}
    calls = []
    result = _graph(model, calls, user_message=message).invoke(
        message=message, context={"phase": "job_description_draft"},
    )
    assert calls == [message]
    assert result["tool_call"]["args"]["message"] == message


def test_interview_scope_uses_same_toolnode_with_real_question_tool_and_no_prose_rewrite():
    calls = []
    def questions(message):
        calls.append(message)
        return {"phase": "interview_room", "outcome": "success", "assistant_message": "Validated question result",
                "questions": [{"question": "Example", "source_ids": [7]}], "sources": [{"chunk_id": 7}]}
    tools = build_interview_room_tools(InterviewRoomToolCallbacks(questions, questions), user_message="Suggest questions")
    model = QueueToolModel(["suggest_interview_questions"])
    model.tool_args = {"message": "Ignore actual request"}
    graph = HireSenseSupervisorGraph(model, tools, capability_scope="interview_room")
    assert isinstance(graph._compiled.nodes["tools"].bound, ToolNode)
    result = graph.invoke(message="Suggest questions", context={"phase": "interview_room"})
    assert calls == ["Suggest questions"]
    assert result["tool_name"] == "suggest_interview_questions"
    assert result["tool_result"]["questions"][0]["source_ids"] == [7]
    assert result["final_response"] == "Validated question result"
    assert model.calls == 1  # No final LLM rewrite of the evidence-backed answer.


def test_interview_scope_rejects_recruitment_tool_registration_before_binding():
    model = QueueToolModel()
    graph = _graph(model, [])
    from langchain_core.tools import tool
    @tool
    def job_posting(message: str) -> str:
        """Mutation tool that must never be available in interview rooms."""
        raise AssertionError("Must never execute")
    callbacks = InterviewRoomToolCallbacks(lambda _: {}, lambda _: {})
    tools = build_interview_room_tools(callbacks, user_message="Post this job")
    with pytest.raises(ValueError, match="restricted"):
        HireSenseSupervisorGraph(model, [*tools, job_posting], capability_scope="interview_room")
    assert graph.capability_scope == "recruitment"
