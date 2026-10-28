import re
import unicodedata
from uuid import uuid4
from app.agents.approval import is_explicit_approval
from app.agents.interview_commands import GeminiInterviewCommandModel
from app.integrations.interview_mcp import InterviewMCPClient
from app.schemas.interview import SelectionRequest, PrepareInvites, RescheduleRequest
from app.services.interview_links import redact_join_links
from app.services.date_time_display import format_time_range
from app.services.scoring_service import ScoringService


class InterviewAssistantService:
    def __init__(self, model=None, client_factory=None):
        self.model = model or GeminiInterviewCommandModel()
        self.client_factory = client_factory or InterviewMCPClient

    def handle(self, db, supervisor, user_id, message, jobs, selected_job_id, selected_ids):
        state = dict(supervisor.state_json or {})
        workflow = dict(state.get("interview_workflow") or {})
        client = self.client_factory(user_id)
        schedules = client.call("list_interview_schedules", {})
        public_context = {"jobs": jobs, "selected_job_posting_id": selected_job_id,
            "selected_application_ids": selected_ids, "schedules": schedules,
            "selection_rule": workflow.get("rule", {}),
            "selection": workflow.get("selection_preview"), "schedule": workflow.get("schedule", {}),
            "awaiting_confirmation": bool(workflow.get("preview"))}
        command = self.model.interpret(message, public_context)
        self.ground_selection(command, message)
        if command.intent == "cancel":
            workflow = {}
            text, phase, outcome = "Unconfirmed workflow cancelled. No additional emails were sent; existing interview schedules are unchanged. Scheduled-interview cancellation is not supported in this increment.", "interview_selection", "info"
        elif command.intent == "approve":
            wrong_object = re.search(r"\b(?:job description|job post|publish|requirements)\b", message.casefold())
            if wrong_object or supervisor.phase != "interview_approval" or not is_explicit_approval(message) or not workflow.get("preview"):
                raise ValueError("Prepare a preview, then explicitly confirm sending invitations.")
            if "@" in message:
                raise ValueError("Recipients must come from the database selection preview. Confirm without adding email addresses, or change the selection and preview again.")
            if command.candidate_names or command.application_ids:
                raise ValueError("Candidate selection changes need a new preview before confirmation.")
            for source, target in (("job_posting_id", "job_posting_id"), ("selection_mode", "mode"),
                ("top_n", "top_n"), ("threshold", "threshold"), ("operator", "operator"), ("stage", "stage")):
                value = getattr(command, source)
                if value is not None and value != workflow.get("rule", {}).get(target):
                    raise ValueError("Candidate selection changes need a new preview before confirmation.")
            for key in ("date", "start_time", "timezone", "duration_minutes", "mode", "buffer_minutes", "instructions", "subject_template", "body_template"):
                value = getattr(command, key)
                if value is not None and value != workflow.get("schedule", {}).get(key):
                    raise ValueError("Scheduling changes need a new preview before confirmation.")
            if workflow.get("rule", {}).get("mode") == "manual" and workflow.get("selection_source") != "named" and state.get("page_context") == "assessments" and set(selected_ids) != set(workflow["rule"].get("application_ids", [])):
                workflow.pop("preview", None)
                return self.save(supervisor, state, workflow, "interview_selection", "Checked candidates changed. Preview the new selection before sending.")
            preview = workflow["preview"]
            if any(item.get("mode") != "sequential" for item in preview["recipients"]):
                raise ValueError("This preview uses the old scheduling mode. Prepare a new sequential interview preview before confirming.")
            arguments = {"data": {"confirmed": True, "confirmation_token": preview["confirmation_token"],
                "idempotency_key": workflow["idempotency_key"]}}
            tool = "confirm_interview_reschedule" if workflow.get("rescheduling") else "confirm_and_send_interview_invites"
            if not workflow.get("rescheduling"):
                arguments["batch_id"] = preview["id"]
            result = client.call(tool, arguments)
            workflow["last_batch_id"] = result["id"]
            workflow.pop("preview", None)
            phase, outcome = "interview_sent", "success"
            text = f"Confirmed {result['recipient_count']} invitations. Delivery is queued; sent, failed and uncertain results will appear after processing."
        else:
            updates = command.model_dump(exclude_none=True)
            # An interpreter's "selection" label is not a new-workflow command.
            # Date/time follow-ups must retain the previously chosen candidates.
            if command.intent == "selection" and command.selection_mode and workflow.get("rescheduling"):
                workflow = {}
            if command.intent == "reschedule":
                if command.needs_schedule_selection:
                    return self.save(supervisor, state, workflow, "interview_reschedule", "Several interviews may match. Specify the interview ID(s) and stage to reschedule.")
                ids = command.schedule_ids
                if not ids and command.candidate_name:
                    matching = [item for item in schedules if item["candidate_name"].casefold() == command.candidate_name.strip().casefold()
                        and item["status"] in {"scheduled", "rescheduled"}]
                    if len(matching) == 1:
                        ids = [matching[0]["id"]]
                if not ids or not set(ids).issubset({item["id"] for item in schedules}):
                    return self.save(supervisor, state, workflow, "interview_reschedule", "Specify one authorized interview ID, or an unambiguous candidate name.")
                workflow["rescheduling"], workflow["schedule_ids"] = True, ids
                first = next(item for item in schedules if item["id"] == ids[0])
                workflow.setdefault("schedule", {}).update({"timezone": first["timezone"], "duration_minutes": first["duration_minutes"]})
            schedule = dict(workflow.get("schedule", {}))
            for key in ("date", "start_time", "timezone", "duration_minutes", "mode", "buffer_minutes", "instructions", "subject_template", "body_template", "reason"):
                if key in updates:
                    schedule[key] = updates[key]
            workflow["schedule"] = schedule
            workflow.pop("preview", None)  # Every edit invalidates the old confirmation.
            state["interview_workflow"] = workflow
            supervisor.state_json = redact_join_links(state)  # Persist invalidation, never raw links.
            if command.mode == "shared":
                raise ValueError("All interviews use sequential individual slots; shared/group interviews are not supported.")
            schedule["mode"] = "sequential"
            schedule.setdefault("timezone", "Asia/Dhaka")
            if not workflow.get("rescheduling"):
                rule = dict(workflow.get("rule", {}))
                for target, source in (("job_posting_id", "job_posting_id"), ("mode", "selection_mode"), ("top_n", "top_n"),
                    ("threshold", "threshold"), ("operator", "operator"), ("stage", "stage")):
                    if source in updates:
                        rule[target] = updates[source]
                if not rule.get("job_posting_id") and selected_job_id:
                    rule["job_posting_id"] = selected_job_id
                if command.needs_job_selection:
                    rule.pop("job_posting_id", None)
                    workflow["rule"] = rule
                    return self.save(supervisor, state, workflow, "interview_selection", "Choose a job posting by ID: " + ", ".join(f"#{job['id']} {job['title']}" for job in jobs) + ".")
                if command.selection_mode == "threshold" or command.threshold is not None:
                    lowered = message.casefold()
                    if re.search(r"at least|greater than or equal|more than or equal|no less than|>=", lowered):
                        rule["operator"] = "gte"
                    elif re.search(r"more than|greater than|above|(?<!>)>(?!=)", lowered):
                        rule["operator"] = "gt"
                if command.candidate_names or command.application_ids:
                    workflow["selection_source"] = "named"
                    rule["mode"] = "manual"
                    rule.pop("application_ids", None)
                    workflow.pop("selection_preview", None)
                    workflow.pop("selection_token", None)
                    if rule.get("job_posting_id") in {job["id"] for job in jobs}:
                        ids, question = self.resolve_candidates(db, user_id, rule["job_posting_id"], command)
                        if question:
                            workflow["rule"] = rule
                            return self.save(supervisor, state, workflow, "interview_selection", question)
                        rule["application_ids"] = ids
                elif command.selection_mode:
                    workflow.pop("selection_source", None)
                if rule.get("mode") == "manual" and workflow.get("selection_source") != "named" and (selected_ids or not rule.get("application_ids")):
                    rule["application_ids"] = selected_ids
                irrelevant = {"top_n": ("threshold", "operator", "application_ids"),
                    "threshold": ("top_n", "application_ids"), "manual": ("top_n", "threshold", "operator")}
                for key in irrelevant.get(rule.get("mode"), ()):
                    rule.pop(key, None)
                workflow["rule"] = rule
                questions = []
                if not rule.get("job_posting_id"):
                    questions.append("Which job posting should I use?")
                if not rule.get("mode"):
                    questions.append("Name the candidate(s), or choose by ranking. How many candidates from the top should I select, or above which score should I select candidates?")
                if rule.get("mode") == "manual" and not rule.get("application_ids"):
                    questions.append("Name the candidate(s) again or select their checkboxes for this job.")
                if rule.get("mode") == "top_n" and not rule.get("top_n"):
                    questions.append("How many candidates from the top should I select?")
                if rule.get("mode") == "threshold" and rule.get("threshold") is None:
                    questions.append("Candidates above which score should I select?")
                elif rule.get("mode") == "threshold" and not rule.get("operator"):
                    questions.append(f"Should candidates score more than {rule['threshold']}%, or is exactly {rule['threshold']}% also acceptable?")
                if questions:
                    return self.save(supervisor, state, workflow, "interview_selection", "\n".join(questions))
                if rule["job_posting_id"] not in {job["id"] for job in jobs}:
                    raise ValueError("Select a job from the authorized job postings")
                selection = client.call("preview_candidate_selection", {"data": SelectionRequest.model_validate(rule).model_dump(mode="json")})
                workflow["selection_token"] = selection.pop("selection_token")
                workflow["selection_preview"] = selection
                count = selection["recipient_count"]
                prefix = self.selection_text(selection)
                if not count:
                    return self.save(supervisor, state, workflow, "interview_selection", prefix + "\nNo eligible recipients; change the selection or resolve the listed exclusions.")
            else:
                count, prefix = len(workflow["schedule_ids"]), "Rescheduling " + str(len(workflow["schedule_ids"])) + " interview(s)."
            missing = [key for key in ("date", "start_time", "duration_minutes") if schedule.get(key) in (None, "")]
            if missing:
                labels = {"date": "date", "start_time": "local start time", "duration_minutes": "duration in minutes"}
                return self.save(supervisor, state, workflow, "interview_schedule", prefix + "\nPlease provide: " + ", ".join(labels[key] for key in missing) + ".")
            if workflow.get("rescheduling"):
                data = RescheduleRequest.model_validate({**schedule, "schedule_ids": workflow["schedule_ids"]})
                preview = client.call("preview_interview_reschedule", {"data": data.model_dump(mode="json")})
            else:
                clean = {key: value for key, value in schedule.items() if key != "reason"}
                data = PrepareInvites.model_validate({**clean, "selection_token": workflow["selection_token"]})
                preview = client.call("prepare_interview_invites", {"data": data.model_dump(mode="json")})
            workflow["preview"], workflow["idempotency_key"] = preview, str(uuid4())
            phase, outcome = "interview_approval", "info"
            text = prefix + "\n\n" + self.preview_text(preview) + "\n\nReply ‘confirm’ to send, or tell me what to change. No email has been sent."
        return self.save(supervisor, state, workflow, phase, text, outcome)

    @staticmethod
    def ground_selection(command, message):
        """Do not let schedule-only follow-ups overwrite a known candidate rule."""
        text = message.casefold()
        numbers = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
        top = re.search(r"\b(?:top|best|first|highest(?:[- ]ranked)?)\s+(\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten)\b", text)
        cue = re.search(r"\b(?:top|best|highest|first|scores?|scored|threshold|checkboxes?)\b|\b(?:checked|selected)\s+candidates\b", text)
        bare_score = re.fullmatch(r"\s*(?:above|over|more than|at least|greater than(?: or equal to)?|[<>]=?)\s*\d+(?:\.\d+)?\s*%?[.!]?\s*", text)
        score = re.search(r"(>=|>|\b(?:greater than or equal(?: to)?|more than or equal(?: to)?|at least|no less than|more than|greater than|above|over)\b)\s*(\d+(?:\.\d+)?)\s*%?", text)
        score_context = bool(re.search(r"\b(?:candidates?|applicants?|scores?|scored)\b", text) or bare_score)
        score_units = bool(score and re.match(r"(?:minutes?|mins?|hours?|hrs?|days?)\b", text[score.end():].lstrip()))
        names = [*(command.candidate_names or []), *([command.candidate_name] if command.candidate_name else [])]
        # Names must be present in the human's latest message, never copied from
        # workflow context. Normalize case/spacing, not spelling or identity.
        normalized_message = InterviewAssistantService.normalize_name(message)
        command.candidate_names = list(dict.fromkeys(name.strip() for name in names if name.strip()
            and re.search(r"(?<!\w)" + re.escape(InterviewAssistantService.normalize_name(name)) + r"(?!\w)", normalized_message)))
        explicit_ids = {int(value) for value in re.findall(r"\bapplication\s*#?\s*(\d+)\b", text)}
        command.application_ids = [value for value in command.application_ids if value in explicit_ids]
        if (command.candidate_names or command.application_ids) and command.intent != "reschedule":
            command.selection_mode = "manual"
            command.top_n = command.threshold = command.operator = None
        elif not cue and not bare_score and not (score and score_context and not score_units):
            command.selection_mode = command.top_n = command.threshold = command.operator = None
        elif top:
            value = top.group(1)
            command.selection_mode = "top_n"
            command.top_n = int(value) if value.isdigit() else numbers[value]
            command.threshold = command.operator = None
        elif score and score_context and not score_units:
            command.selection_mode, command.threshold = "threshold", score.group(2)
            command.operator = "gte" if score.group(1) in {">=", "at least", "no less than"} or "equal" in score.group(1) else "gt"
            command.top_n = None

    @staticmethod
    def normalize_name(value):
        return " ".join(unicodedata.normalize("NFKC", value).casefold().split()).strip(" .,!?\"'“”‘’")

    @staticmethod
    def resolve_candidates(db, user_id, job_id, command):
        """Read only the authorized job's latest saved ranking. Never fuzzy-pick a person."""
        scoring = ScoringService()
        runs = scoring.list_runs(db, user_id=user_id, job_id=job_id)
        if not runs or runs[0]["status"] not in {"completed", "completed_with_review"}:
            return [], "Rank the CVs for this job first, then name the candidate to schedule."
        candidates = scoring.detail(db, user_id=user_id, run_id=runs[0]["id"])["results"]
        authorized_ids = {item["application_id"] for item in candidates}
        if not set(command.application_ids).issubset(authorized_ids):
            return [], "Those application IDs are not in this job's saved ranking. Select candidates from this job."
        selected = list(command.application_ids)
        for name in command.candidate_names:
            normalized = InterviewAssistantService.normalize_name(name)
            exact = [item for item in candidates if InterviewAssistantService.normalize_name(item["candidate_name"]) == normalized]
            matches = exact or [item for item in candidates if " " + normalized + " " in " " + InterviewAssistantService.normalize_name(item["candidate_name"]) + " "]
            if not matches:
                return [], f'No candidate named “{name}” was found in this job’s saved ranking. Check the name or choose another job.'
            if len(matches) > 1:
                choices = "; ".join(f'{item["candidate_name"]} (application #{item["application_id"]})' for item in matches)
                return [], f'“{name}” matches more than one candidate: {choices}. Specify an application #ID or select the correct checkbox.'
            selected.append(matches[0]["application_id"])
        return list(dict.fromkeys(selected)), None

    @staticmethod
    def save(supervisor, state, workflow, phase, text, outcome="info"):
        state["interview_workflow"] = workflow
        supervisor.state_json = redact_join_links(state)
        return {"phase": phase, "outcome": outcome, "assistant_message": text, "refresh_required": outcome == "success"}

    @staticmethod
    def selection_text(preview):
        rows = [f"Selected {preview['recipient_count']} candidate(s) for {preview['job_title']}:"]
        rows += [f"• {item['name']} (application #{item['application_id']}): rank {item['rank']}, score {item['score']}%, {item['masked_email']}" for item in preview["selected"]]
        rows += [f"Excluded {item['name']}: {', '.join(item['reasons'])}" for item in preview["excluded"]]
        rows += preview.get("warnings", [])
        return "\n".join(rows)

    @staticmethod
    def preview_text(preview):
        rows = [f"Exact invitation preview — {preview['recipient_count']} recipient(s).",
            f"From: {preview['sender']['from_email']} | Reply-to: {preview['sender']['reply_to']}"]
        for item in preview["recipients"]:
            rows.append(f"\n{item['name']} — {item['masked_email']}\n{format_time_range(item['local_start'], item['local_end'], item['timezone'])}\nSubject: {item['subject']}\n{item['body']}\nAttachment: interview.ics (METHOD:REQUEST)")
        return "\n".join(rows)
