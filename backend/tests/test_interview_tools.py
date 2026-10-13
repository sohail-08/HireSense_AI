import asyncio
from types import SimpleNamespace
from datetime import date, timedelta
import pytest
from sqlalchemy import select, func
from app.models.interview import InterviewBatch, InterviewSchedule, InterviewDelivery
from app.schemas.interview import PrepareInvites, ConfirmInvites, SelectionRequest
from app.services.interview_assistant_service import InterviewAssistantService
from app.agents.interview_commands import InterviewCommand
from app.agents.supervisor_tools import SupervisorToolCallbacks, build_supervisor_tools
from app.agents.supervisor import HireSenseSupervisorGraph
from app.services.interview_content import SMTPInvitationSender, render_email, allocate_slots
from supervisor_fakes import QueueToolModel
from test_interviews import setup, records, select_preview, prepared, confirm_data, schedule_data


def test_smtp_acceptance_failures_calendar_mime_and_no_secret_leak(setup, monkeypatch):
    db, owner, _, _, _, _, service, _ = setup
    preview = prepared(setup, count=1)
    service.confirm(db, owner.id, preview["id"], confirm_data(preview))
    delivery = db.scalar(select(InterviewDelivery))
    captured = []
    class SMTPFake:
        def __init__(self, *args, **kwargs): pass
        def ehlo(self): return (250, b"ok")
        def mail(self, address): return (250, b"ok")
        def rcpt(self, address): return (250, b"ok")
        def data(self, message): captured.append(message); return (250, b"accepted")
        def close(self): pass
    import app.services.interview_content as content
    monkeypatch.setattr(content.smtplib, "SMTP", SMTPFake)
    settings = service.settings.model_copy(update={"smtp_host": "mock-only", "smtp_username": "", "smtp_use_tls": False})
    sender = SMTPInvitationSender(settings)
    assert sender.send(delivery)["status"] == "sent"
    from email import message_from_bytes, policy
    message = message_from_bytes(captured[0], policy=policy.default)
    attachment = next(message.iter_attachments())
    assert attachment.get_filename() == "interview.ics"
    assert attachment.get_content_type() == "text/calendar"
    assert attachment.get_param("method") == "REQUEST"
    class ConnectionFailure(SMTPFake):
        def __init__(self, *args, **kwargs): raise OSError("private-credential-must-not-appear")
    monkeypatch.setattr(content.smtplib, "SMTP", ConnectionFailure)
    outcome = sender.send(delivery)
    assert outcome["status"] == "failed" and "private" not in str(outcome)
    class AcceptanceUnknown(SMTPFake):
        def data(self, message): raise OSError("SMTP accepted but response disconnected")
    monkeypatch.setattr(content.smtplib, "SMTP", AcceptanceUnknown)
    assert sender.send(delivery)["status"] == "uncertain"
    class RecipientRejected(SMTPFake):
        def rcpt(self, address): return (550, b"rejected")
    monkeypatch.setattr(content.smtplib, "SMTP", RecipientRejected)
    assert sender.send(delivery)["status"] == "failed"


def test_email_template_validation_and_omission_of_meeting_links(setup):
    _, _, _, _, _, _, service, _ = setup
    data = schedule_data("placeholder-token")
    slot = allocate_slots(data, 1)[0]
    assert "meeting" not in render_email(service.settings, {"name": "A"}, "Backend", "technical", slot, data)["body"].lower()
    for template in ("{candidate_name.__class__}", "{unknown}", "{candidate_name!r}"):
        with pytest.raises(ValueError):
            render_email(service.settings, {"name": "A"}, "Backend", "technical", slot, data.model_copy(update={"body_template": template}))
    with pytest.raises(ValueError):
        render_email(service.settings, {"name": "A"}, "Backend", "technical", slot, data.model_copy(update={"subject_template": "a\nb"}))
    custom = render_email(service.settings, {"name": "A"}, "Backend", "technical", slot,
        data.model_copy(update={"body_template": "Hello {candidate_name}!", "instructions": "Bring a laptop."}))
    assert "Hello A!" in custom["body"] and "Asia/Dhaka" in custom["body"]
    assert "Bring a laptop." in custom["body"] and "Stage: technical" in custom["body"]


def test_restart_recovery_never_retries_uncertain_attempts(setup):
    db, owner, _, _, _, _, service, sender = setup
    preview = prepared(setup)
    service.confirm(db, owner.id, preview["id"], confirm_data(preview))
    first = db.scalar(select(InterviewDelivery).order_by(InterviewDelivery.id))
    first.status, first.in_flight, first.attempts = "uncertain", True, 1
    db.commit()
    assert service.recover_interrupted(db) == [preview["id"]]
    service.deliver_pending(db, preview["id"])
    assert len(sender.calls) == 1
    assert service.batch(db, owner.id, preview["id"])["uncertain"] == 1


class LocalMCP:
    def __init__(self, db, owner, service): self.db, self.owner, self.service, self.calls = db, owner, service, []
    def call(self, name, arguments):
        self.calls.append(name)
        if name == "list_interview_schedules": return self.service.schedules(self.db, self.owner)
        if name == "preview_candidate_selection": return self.service.preview_selection(self.db, self.owner, SelectionRequest.model_validate(arguments["data"]))
        if name == "prepare_interview_invites": return self.service.prepare(self.db, self.owner, PrepareInvites.model_validate(arguments["data"]))
        if name == "confirm_and_send_interview_invites": return self.service.confirm(self.db, self.owner, arguments["batch_id"], ConfirmInvites.model_validate(arguments["data"]))
        raise AssertionError("Unexpected tool")


def test_chat_collects_details_previews_and_requires_real_user_confirmation(setup):
    db, owner, _, posting, apps, _, service, sender = setup
    client = LocalMCP(db, owner.id, service)
    class Commands:
        command = InterviewCommand(intent="selection", job_posting_id=posting.id, selection_mode="top_n", top_n=2)
        def interpret(self, message, context): return self.command
    model = Commands()
    assistant = InterviewAssistantService(model, lambda user_id: client)
    supervisor = SimpleNamespace(state_json={}, phase="published")
    def run(message):
        result = assistant.handle(db, supervisor, owner.id, message, [{"id": posting.id}], posting.id, [])
        supervisor.phase = result["phase"]
        return result
    result = run("Schedule interviews for the top 2 candidates")
    assert result["phase"] == "interview_schedule"
    assert "time zone" not in result["assistant_message"] and "shared/group" not in result["assistant_message"]
    assert "preview_candidate_selection" in client.calls and not sender.calls
    model.command = InterviewCommand(intent="details", date=(date.today() + timedelta(days=20)).isoformat(), start_time="10:00", duration_minutes=30)
    assert run("20 days later at 10:00, 30 minutes")["phase"] == "interview_approval"
    assert supervisor.state_json["interview_workflow"]["schedule"]["timezone"] == "Asia/Dhaka"
    assert supervisor.state_json["interview_workflow"]["schedule"]["mode"] == "sequential"
    assert db.scalar(select(func.count(InterviewSchedule.id))) == 0
    model.command = InterviewCommand(intent="approve")
    with pytest.raises(ValueError): run("not approved")
    with pytest.raises(ValueError): run("approve the job description")
    model.command = InterviewCommand(intent="approve", start_time="11:00")
    with pytest.raises(ValueError, match="new preview"): run("confirm but use 11:00")
    model.command = InterviewCommand(intent="approve")
    assert db.scalar(select(func.count(InterviewSchedule.id))) == 0
    assert run("confirm")["outcome"] == "success"
    assert "confirm_and_send_interview_invites" in client.calls
    assert db.scalar(select(func.count(InterviewSchedule.id))) == 2
    assert sender.calls == []  # Confirmation persists outbox; SMTP worker runs separately.


def test_chat_rejects_group_mode_without_preparing_or_sending(setup):
    db, owner, _, posting, _, _, service, sender = setup
    client = LocalMCP(db, owner.id, service)
    class Commands:
        def interpret(self, message, context):
            return InterviewCommand(intent="selection", job_posting_id=posting.id, selection_mode="top_n", top_n=2, mode="shared")
    assistant = InterviewAssistantService(Commands(), lambda user_id: client)
    supervisor = SimpleNamespace(state_json={}, phase="published")
    with pytest.raises(ValueError, match="sequential individual"):
        assistant.handle(db, supervisor, owner.id, "Schedule a group interview for top 2", [{"id": posting.id}], posting.id, [])
    assert not sender.calls and "prepare_interview_invites" not in client.calls


@pytest.mark.parametrize("user_text,mode,value", [
    ("schedule interview with top 3 candidates", "top_n", 3),
    ("select candidates above 0", "threshold", "0"),
])
def test_chat_keeps_selection_across_reload_and_misclassified_schedule_followup(setup, user_text, mode, value):
    from app.models.supervisor import SupervisorSession
    db, owner, _, posting, _, _, service, sender = setup
    client = LocalMCP(db, owner.id, service)
    class Commands:
        command = InterviewCommand(intent="selection", job_posting_id=posting.id)
        def interpret(self, message, context):
            self.context = context
            return self.command.model_copy()
    model = Commands()
    assistant = InterviewAssistantService(model, lambda user_id: client)
    supervisor = SupervisorSession(interviewer_user_id=owner.id, state_json={}, phase="published")
    db.add(supervisor)
    db.flush()
    result = assistant.handle(db, supervisor, owner.id, user_text, [{"id": posting.id}], posting.id, [])
    supervisor.phase = result["phase"]
    assert result["phase"] == "interview_schedule"
    db.commit()
    session_id = supervisor.id
    db.expunge(supervisor)
    supervisor = db.get(SupervisorSession, session_id)
    # Reproduce the LLM error from the screenshot: date/time marked "selection",
    # plus an invented different method that the human never requested.
    model.command = InterviewCommand(intent="selection", selection_mode="manual", date=(date.today() + timedelta(days=20)).isoformat(), start_time="08:00", duration_minutes=30)
    result = assistant.handle(db, supervisor, owner.id, "date: 20 days later\ntime: 8.00 am\nduration: 30 minutes", [{"id": posting.id}], posting.id, [])
    assert model.context["selection_rule"]["mode"] == mode
    rule = supervisor.state_json["interview_workflow"]["rule"]
    assert rule["mode"] == mode and rule["top_n" if mode == "top_n" else "threshold"] == value
    assert result["phase"] == "interview_approval"
    assert "Reply ‘confirm’" in result["assistant_message"]
    assert "selection method" not in result["assistant_message"]
    assert not sender.calls and db.scalar(select(func.count(InterviewSchedule.id))) == 0


def test_chat_asks_for_candidate_choice_in_plain_language_when_missing(setup):
    db, owner, _, posting, _, _, service, _ = setup
    client = LocalMCP(db, owner.id, service)
    class Commands:
        def interpret(self, message, context):
            return InterviewCommand(intent="selection", job_posting_id=posting.id, selection_mode="top_n", top_n=5)
    supervisor = SimpleNamespace(state_json={}, phase="published")
    assistant = InterviewAssistantService(Commands(), lambda user_id: client)
    result = assistant.handle(db, supervisor, owner.id, "schedule interviews", [{"id": posting.id}], posting.id, [])
    assert result["phase"] == "interview_selection"
    assert "How many candidates from the top" in result["assistant_message"]
    assert "above which score" in result["assistant_message"]
    assert "top N" not in result["assistant_message"] and "threshold" not in result["assistant_message"]
    assert "preview_candidate_selection" not in client.calls


def test_explicit_changed_candidate_choice_replaces_rule_but_keeps_schedule(setup):
    db, owner, _, posting, _, _, service, _ = setup
    client = LocalMCP(db, owner.id, service)
    class Commands:
        command = InterviewCommand(intent="selection", job_posting_id=posting.id, date=(date.today() + timedelta(days=20)).isoformat(), start_time="10:00", duration_minutes=30)
        def interpret(self, message, context): return self.command.model_copy()
    model = Commands()
    assistant = InterviewAssistantService(model, lambda user_id: client)
    supervisor = SimpleNamespace(state_json={}, phase="published")
    result = assistant.handle(db, supervisor, owner.id, "top 3, 20 days later at 10:00, 30 minutes", [{"id": posting.id}], posting.id, [])
    first_id = supervisor.state_json["interview_workflow"]["preview"]["id"]
    model.command = InterviewCommand(intent="selection")
    result = assistant.handle(db, supervisor, owner.id, "make it top 2 instead", [{"id": posting.id}], posting.id, [])
    workflow = supervisor.state_json["interview_workflow"]
    assert workflow["rule"]["top_n"] == 2 and workflow["schedule"]["start_time"] == "10:00"
    assert result["phase"] == "interview_approval" and workflow["preview"]["id"] != first_id
    supervisor.phase = result["phase"]
    model.command = InterviewCommand(intent="approve")
    with pytest.raises(ValueError, match="selection changes need a new preview"):
        assistant.handle(db, supervisor, owner.id, "confirm but select top 1", [{"id": posting.id}], posting.id, [])
    assert "confirm_and_send_interview_invites" not in client.calls


def test_command_interpretation_does_not_invent_missing_schedule_fields(monkeypatch):
    from app.agents.interview_commands import GeminiInterviewCommandModel
    import app.agents.interview_commands as commands
    invented = InterviewCommand(date="2030-01-01", start_time="10:00", timezone="Asia/Dhaka",
        duration_minutes=30, mode="shared", buffer_minutes=10).model_dump()
    monkeypatch.setattr(commands.GeminiStructuredClient, "generate_json", lambda self, **kwargs: invented)
    parsed = GeminiInterviewCommandModel().interpret("schedule top 5", {})
    assert all(getattr(parsed, key) is None for key in ("date", "start_time", "timezone", "duration_minutes", "mode", "buffer_minutes"))
    parsed = GeminiInterviewCommandModel().interpret("2030-01-01 at 10:00 Asia/Dhaka, 30 minutes, shared, 10 minute buffer", {})
    assert parsed.date == "2030-01-01" and parsed.mode == "shared" and parsed.buffer_minutes == 10
    invented.update({"date": "2030-10-14", "start_time": "08:00"})
    parsed = GeminiInterviewCommandModel().interpret("date: 14th October, 2030\ntime: 8.00 am\nduration: 30 minutes", {})
    assert parsed.date == "2030-10-14" and parsed.start_time == "08:00"


def test_chat_threshold_operator_and_named_job_are_grounded(setup):
    db, owner, _, posting, _, _, service, _ = setup
    client = LocalMCP(db, owner.id, service)
    class Commands:
        command = InterviewCommand(intent="selection", job_posting_id=posting.id,
            selection_mode="threshold", threshold="0", operator="gt")
        def interpret(self, message, context): return self.command
    model = Commands()
    assistant = InterviewAssistantService(model, lambda user_id: client)
    supervisor = SimpleNamespace(state_json={}, phase="published")
    result = assistant.handle(db, supervisor, owner.id, "Select candidates scoring at least 0", [{"id": posting.id, "title": "Backend"}], posting.id, [])
    assert supervisor.state_json["interview_workflow"]["rule"]["operator"] == "gte"
    assert result["phase"] == "interview_schedule"
    model.command = InterviewCommand(intent="selection", needs_job_selection=True, selection_mode="top_n", top_n=2)
    result = assistant.handle(db, supervisor, owner.id, "Schedule top 2 accountants", [{"id": posting.id, "title": "Backend"}], posting.id, [])
    assert result["phase"] == "interview_selection"
    assert "job_posting_id" not in supervisor.state_json["interview_workflow"]["rule"]


def test_native_toolnode_binds_interview_workflow_without_recipient_or_identity_arguments():
    callback = lambda message: {"phase": "interview_selection", "outcome": "info", "assistant_message": "Please select a job.", "refresh_required": False}
    callbacks = SupervisorToolCallbacks(callback, callback, callback, callback, callback, callback, callback, lambda m, d: callback(m), interviews=callback)
    tools = build_supervisor_tools(callbacks, user_message="schedule top 5")
    tool = next(item for item in tools if item.name == "interviews")
    assert set(tool.args) == {"message"}
    model = QueueToolModel(["interviews"])
    result = HireSenseSupervisorGraph(model, tools).invoke(message="schedule top 5", context={"phase": "published"})
    assert result["tool_name"] == "interviews" and model.tool_messages
    assert model.bindings[0]["tool_choice"] == "any"


def test_mcp_wrappers_use_same_services_and_auth_is_not_a_model_argument(setup, monkeypatch):
    db, owner, _, posting, _, _, service, _ = setup
    from app.interview_mcp import server
    async def forwarding(method, path, data=None):
        if path == "/selection/preview": return service.preview_selection(db, owner.id, SelectionRequest.model_validate(data))
        if path == "/invitations/prepare": return service.prepare(db, owner.id, PrepareInvites.model_validate(data))
        raise AssertionError("Unexpected request")
    monkeypatch.setattr(server, "forward", forwarding)
    from mcp import Client
    async def exercise():
        async with Client(server.mcp, cache=None) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            assert {"preview_candidate_selection", "prepare_interview_invites", "confirm_and_send_interview_invites", "preview_interview_reschedule", "confirm_interview_reschedule"}.issubset(names)
            selection = await client.call_tool("preview_candidate_selection", {"data": {"job_posting_id": posting.id, "mode": "top_n", "top_n": 1}})
            assert not selection.is_error
            result = selection.structured_content
            preview = await client.call_tool("prepare_interview_invites", {"data": schedule_data(result["selection_token"]).model_dump(mode="json")})
            assert not preview.is_error
            assert preview.structured_content["recipient_count"] == 1
            assert all("jwt" not in tool.input_schema.get("properties", {}) for tool in tools.tools)
    asyncio.run(exercise())


def test_mcp_forwarding_requires_authorization_header(monkeypatch):
    from app.interview_mcp import server
    token = server.authorization.set("")
    try:
        with pytest.raises(ValueError, match="Authenticated"):
            asyncio.run(server.forward("GET", "/schedules"))
    finally:
        server.authorization.reset(token)


def test_superseded_calendar_notifications_are_not_sent(setup):
    from app.schemas.interview import RescheduleRequest
    db, owner, _, _, _, _, service, sender = setup
    preview = prepared(setup, count=1)
    first = service.confirm(db, owner.id, preview["id"], confirm_data(preview))
    schedule = db.scalar(select(InterviewSchedule))
    request = RescheduleRequest.model_validate({**schedule_data("placeholder-token").model_dump(exclude={"selection_token"}),
        "date": date.today() + timedelta(days=21), "schedule_ids": [schedule.id]})
    moved = service.preview_reschedule(db, owner.id, request)
    result = service.confirm_reschedule(db, owner.id, confirm_data(moved, "reschedule-supersedes-pending"))
    service.deliver_pending(db, first["id"])
    assert sender.calls == []
    service.deliver_pending(db, result["id"])
    assert len(sender.calls) == 1
    assert "SEQUENCE:1" in sender.calls[0][3]
