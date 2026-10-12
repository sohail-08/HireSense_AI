# Candidate selection and interview invitations

This increment adds internal schedules and SMTP email with `.ics` attachments.
It does **not** generate meeting links or connect Google Calendar, Outlook, Meet,
Teams or Zoom. `interview_schedules.meeting_url` remains nullable for later work.
No real invitations were sent during implementation; automated delivery tests use mocks.

## Setup

Use the existing **repository-root `.env` only**. `.env.example` contains the new
settings. Never put credentials in frontend `VITE_*` variables or Git.

```dotenv
INTERVIEW_COMPANY_NAME=BJIT
SMTP_HOST=mailpit
SMTP_PORT=1025
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM_EMAIL=interviews@hiresense.test
SMTP_FROM_NAME=HireSense
SMTP_USE_TLS=false
SMTP_TIMEOUT_SECONDS=15
INTERVIEW_REPLY_TO_EMAIL=interviews@hiresense.test
```

For local mail testing:

```powershell
docker compose --profile mail-test up -d --build
```

Open Mailpit at http://localhost:8025. Messages are captured locally, not delivered
to candidate inboxes. Set `SMTP_HOST=mailpit` in `.env` before starting the backend;
the testing container is opt-in and credentials are not silently changed. If SMTP
is unconfigured, schedules are still persisted and delivery reports `failed` with
`smtp_not_configured`; configure SMTP and explicitly retry the failed notification.

For production, replace these settings with your SMTP provider's host, port,
credentials, sender and reply-to addresses. `SMTP_USE_TLS=true` enables verified
STARTTLS (commonly port 587). Implicit SMTPS/port 465 is not implemented. An SMTP
acceptance means **sent to the SMTP server**, not guaranteed delivery into an inbox.
The stored message identifier is the MIME Message-ID for correlation, not a provider
delivery receipt. Configure domain authentication and privacy policies separately.

## Manual interviewer flow

1. On **Assessments**, select a job and a current saved ranking.
2. Use row checkboxes, or expand **Schedule interview** and choose top N or a score
   threshold. `Greater than` uses `>`; `At least` uses `>=`. Comparisons use saved,
   unrounded decimal scores. Selection previews filter candidates and list exclusions.
3. Review selected names, ranks, display scores and masked emails. Top N selects
   exactly N eligible applications when available; ties follow saved rank/application
   order and a boundary warning is shown. Historical/stale rankings must be refreshed.
4. Choose the interview stage, date, local time, IANA zone, duration, mode and buffer.
   UI starts with `Asia/Dhaka`; you can change it. Multiple candidates require an
   explicit shared/group or sequential mode. A 30-minute duration and 10-minute buffer
   allocate 10:00, 10:40, 11:20, etc. UTC instants and original local times are saved.
5. Optionally edit instructions and subject/body templates. Supported fields are
   `{candidate_name}`, `{job_title}`, `{company_name}`, `{local_date}`,
   `{local_start_time}`, `{timezone}`, `{duration}`, `{stage}`, `{contact_email}`,
   `{instructions}` and `{old_schedule}`. Unsupported fields/header injection fail.
   Essential details omitted from a custom body are appended to the exact preview;
   optional instructions are omitted when empty.
6. Preview every recipient, complete time allocation, sender/reply-to, subject, body
   and calendar details. Nothing is sent during selection or preview.
7. Select **Confirm & send**. Schedules and delivery snapshots are committed first;
   background workers then send each email. The UI polls sent/failed/uncertain status.
8. **Interviews** lists schedules, delivery status and previous times. Check one or
   several interviews for the same job to preview and confirm rescheduling. An email
   failure does not revert the new schedule. Retry only the latest eligible failed
   delivery; uncertain/sent/superseded deliveries are never automatically retried.

Selection requires syntactically valid database emails, active/non-withdrawn applications,
usable processed CVs without unresolved extraction problems, and no active interview
for the same stage. This is **invitation eligibility**, not a return to a ranking review
queue: the three-outcome scoring/ranking policy remains unchanged. Recipients cannot
be arbitrary addresses supplied in a chat command. IANA-invalid, past, ambiguous and
nonexistent DST times are rejected. Conflicting interview slots must be changed;
there is no silent conflict override. Shared time is allowed only within the explicitly
chosen new group, not over another existing interview.

## Central chatbot and MCP

Use the existing central assistant, including on Interviews:

- “Schedule interviews for the top 5 frontend engineer candidates.”
- “Send invitations to candidates who scored more than 70.”
- “Select candidates scoring at least 80.”
- “Use 15 October 2026, 10:00, Asia/Dhaka, 30 minutes, sequential, 10-minute buffer.”
- “Confirm.” (only after an exact invitation preview)
- “Reschedule Farhan Ahmed's interview to 15 October at 15:00.”

The native supervisor still uses `bind_tools()`, `@tool` and `ToolNode`. Its new
`interviews` tool delegates to a small command interpreter and deterministic services
through MCP. Persistent phases are `interview_selection`, `interview_schedule`,
`interview_approval`, `interview_sent` and `interview_reschedule`. Missing fields pause
the operation; a later message resumes the stored selection/schedule. The
date/time interpretation accepts explicit ISO/numeric dates, named months and
relative dates, with numeric clock times or AM/PM. Missing details are not silently
filled from model defaults. The actual
graph nodes/edges are unchanged (`supervisor_agent`, `tools`, `capture_tool_result`,
`handle_error`); these phases are workflow state, not invented graph nodes.

The SDK is pinned to **mcp 2.3.0**, using v2 `MCPServer`, `Client` and Streamable HTTP.
`interview-mcp` listens on container port **8002** and forwards to the authenticated
FastAPI APIs at `http://backend:8000/api/interviews`. Backend client URL in Compose:
`http://interview-mcp:8002/mcp`. For native development set `INTERVIEW_MCP_URL` and
`INTERVIEW_BACKEND_URL` appropriately. SMTP secrets exist only in the backend process;
the MCP container receives only the backend URL, not SMTP credentials or database access.

Tools:

- `preview_candidate_selection` — read-only selection and signed fingerprint.
- `prepare_interview_invites` — persists a draft, never sends mail.
- `confirm_and_send_interview_invites` — explicit confirmed revision and idempotency key.
- `preview_interview_reschedule` — read-only old/new-time preview.
- `confirm_interview_reschedule` — version-bound schedule update and notification queue.
- `list_interview_schedules` — authorized IDs/names for safe resolution.
- `get_interview_invitation_status` — read-only delivery results.

Delegated JWT authentication is forwarded through HTTP headers, not LLM tool arguments.
MCP middleware forwards that identity; **FastAPI rechecks active interviewer role and
ownership**. The MCP server is not an authorization boundary or OAuth identity provider.
It is internal-only in Compose. Sending cannot be triggered by the interpreter alone:
the original human message must explicitly approve the active interview preview.

## Reliability, calendars and persistence

Migration **0016_interview_scheduling** follows 0015. It adds `interview_batches`,
`interview_schedules` and `interview_deliveries`, without rebuilding existing tables.
Draft snapshots retain selection rule/run, recipients, slots, sender, templates and
confirmation hash. Schedules retain UTC/local times, stage, mode/buffer, UID, sequence,
version, creator and old-time history. Deliveries retain recipient, exact body, calendar
text/checksum, attempts, safe error category, Message-ID and sent timestamp.

Twenty-minute signed previews bind the interviewer, ranking inputs, recipients and
draft revision. Confirming revalidates current ranking, eligibility, future times and
conflicts. Expected schedule versions protect rescheduling. PostgreSQL locks the
interviewer row to serialize schedule conflict checks across jobs; unique active
application/stage, confirmation hash and idempotency-key constraints provide final guards.
Resending a consumed confirmation acknowledges the same operation without creating
more schedules, even after token expiry. Expired previews cannot start new operations.

An outbox record exists **before** SMTP contact. A claimed attempt is conservatively
marked uncertain and in-flight; disconnects during DATA stay uncertain. Definite
connection/envelope/DATA rejection is failed. A restart marks interrupted in-flight
attempts uncertain, never retries them, and resumes only previously confirmed pending
(never attempted) deliveries. Superseded sequences, past interviews and ineligible
recipients are not sent. This lightweight recovery assumes the existing single backend
worker; a multi-worker deployment should add a dedicated leased outbox worker.

Only current, future, active schedules with unchanged eligible recipients and a
definitely failed attempted delivery offer **Retry**. A superseded or skipped
notification is not shown as retryable; an active SMTP attempt displays **Sending**.

Calendar objects are built with **icalendar 6.3.2**. Invitations and reschedules use
`METHOD:REQUEST`, UTC `DTSTART`/`DTEND`, `DTSTAMP`, organizer and attendee. Initial
`SEQUENCE=0`; rescheduling keeps the UID/organizer and increments sequence. No placeholder
meeting URLs are included. Email attaches `text/calendar; method=REQUEST` as `interview.ics`.

Deleting an application removes its schedule/delivery records and redacts it from
batch snapshots; unconfirmed drafts become invalid. Existing published emails cannot
be recalled by database deletion. Conversation messages remain subject to the app's
existing retention policy. Cancellation/completion controls, meeting integration,
attendee RSVP processing, inbox-delivery tracking and implicit SMTPS are future work.

## Checks and reviewable increments

Use mocks; do not send real candidate invitations as a test.

```powershell
docker compose exec backend python -m pytest -q -p no:cacheprovider
cd frontend
npm run build
npm run test:scoring
```

Real PostgreSQL tests use `PGVECTOR_TEST_SERVER_URL` to create/drop **only disposable
test databases**. They verify concurrent confirmation/delivery and fresh-session persistence.
SMTP/MCP tests cover masking, threshold operators, ties, wrong-job rejection, missing
email, stale previews, shared/sequential/DST times, MIME and parsed ICS, partial failure,
safe retry, rescheduling history, restart recovery, native ToolNode and manual/MCP parity.

Verified on 12 October 2026:

- 159 backend tests passed, including disposable PostgreSQL concurrency tests; SMTP
  was mocked. One upstream LangChain pending-deprecation warning remains.
- Frontend TypeScript/production build and all 7 scoring display tests passed.
- Backend, interview MCP and frontend images were rebuilt and started successfully.
- Migration 0016 is applied; all existing table counts match the pre-migration
  snapshot. All three new interview tables are empty. No candidate email was sent.
- Actual Streamable HTTP tool discovery returned all 7 tools; an authenticated
  `list_interview_schedules` call succeeded. Unauthenticated schedule access returned 401.
- Backend health, frontend API proxy and Interviews page HTML returned 200.
- Browser visual/interaction QA was not performed. Root `.env` is unchanged; SMTP
  is currently unconfigured and needs the local Mailpit or provider setup above.
- A pre-migration PostgreSQL backup is saved under ignored
  `backend/storage/backups/hiresense-before-interviews-20261012-0016.dump`.

Suggested commits (you perform Git operations):

1. `feat(interviews): add schedule persistence, SMTP templates and calendar invitations`
2. `feat(interviews): add ranked selection, confirmed invitations and rescheduling APIs`
3. `feat(agent): coordinate interview workflows through authenticated MCP tools`
4. `feat(ui): add candidate selection and interview scheduling interface`
5. `test(interviews): cover delivery safety, concurrency and scheduling workflows`

File map:

- Foundation: `backend/app/models/interview.py`, `backend/app/schemas/interview.py`,
  `backend/app/services/interview_content.py`, migration 0016, config and requirements.
- Services/API: `backend/app/services/interview_service.py`, `backend/app/routes/interviews.py`,
  `backend/app/main.py`, deletion integration and model registration.
- Agent/MCP: `backend/app/agents/interview_commands.py`,
  `backend/app/services/interview_assistant_service.py`, `backend/app/interview_mcp/`,
  `backend/app/integrations/interview_mcp.py`, supervisor tools/service/routes/schemas,
  Docker Compose and `.env.example`.
- Container compatibility: `backend/Dockerfile` normalizes Windows CRLF in the
  startup script during Linux image builds.
- UI: `frontend/src/components/interviews/InterviewSchedulingPanel.tsx`,
  `frontend/src/pages/InterviewsPage.tsx`, ranking checkboxes, shared assistant, types and App routes.
- Verification: `backend/tests/test_interviews.py`, `test_interview_tools.py`,
  `test_interview_postgres.py`, migration test updates, this guide and README.

References: [MCP SDK v2 documentation](https://py.sdk.modelcontextprotocol.io/),
[MCP tools specification](https://modelcontextprotocol.io/specification/2026-07-28/server/tools),
[RFC 5545](https://www.rfc-editor.org/rfc/rfc5545),
[RFC 5546](https://www.rfc-editor.org/rfc/rfc5546),
[RFC 6047](https://www.rfc-editor.org/rfc/rfc6047).
