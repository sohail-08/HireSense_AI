# Candidate selection and interview invitations

This increment adds internal schedules and SMTP email with `.ics` attachments.
The subsequent [LiveKit interview-room increment](interview-rooms.md) adds secure
HireSense candidate links to invitation previews, SMTP email and ICS descriptions.
It still does not connect Google Calendar, Outlook, Meet, Teams or Zoom.
`interview_schedules.meeting_url` remains nullable; bearer links are never stored there.
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

1. On **Schedule Interviews**, select a job with a current saved CV ranking.
   The candidate list shows persisted **Interview status**, date/time and a link
   to the existing interview. Filter by **Not scheduled**, **Already scheduled**
   or **Completed**. Active bookings disable duplicate manual selection even if
   their email delivery failed; use **View scheduled interviews** to reschedule
   or retry notification. Cancelled bookings can be scheduled again. Statuses are
   keyed by application and the form's default stage, not candidate name or CV
   rank. Past timestamps alone never imply completion. Statuses refresh after
   confirmation, assistant updates, window focus and every 30 seconds while the
   page is visible/idle; failed status loading disables manual selection instead
   of incorrectly claiming a candidate is unscheduled. The existing authenticated
   schedules endpoint accepts optional `job_posting_id` for a job-scoped read.
2. Use row checkboxes, or choose **Highest-ranked
   candidates** or **Candidates above a score**. `Above` uses `>`; `At least` uses `>=`. Comparisons use saved,
   unrounded decimal scores. Selection previews filter candidates and list exclusions.
3. Select **Preview candidate selection** to review names, ranks, scores and full
   email addresses in a modal. Close it or choose **Continue to schedule** to return
   to the form; **Review selection** reopens it. These details are restricted to the
   authenticated interviewer. Top N examines
   the original first N saved ranking entries, then excludes ineligible applicants
   without backfilling from lower positions. Thus top 3 can yield fewer than 3
   invitations, but never select someone from position 6. Ties follow saved
   rank/application order and a boundary warning is shown. Historical/stale rankings
   must be refreshed.
4. Choose the date and start time using the styled calendar and time popups, then
   enter duration and buffer. The calendar supports keyboard navigation and an
   explicit YYYY-MM-DD entry; the time picker uses hour, minute and AM/PM choices.
   Saved values remain YYYY-MM-DD and 24-hour HH:mm. The form uses the default
   `technical` stage internally and `Asia/Dhaka` automatically; neither is an input.
   Every invitation and reschedule uses **sequential individual slots**. There is no
   scheduling-mode selector, and API/MCP requests for shared/group mode are rejected.
   A 30-minute duration and 10-minute buffer
   allocate 10:00, 10:40, 11:20, etc. UTC instants and original local times are saved.
5. Optionally add instructions. The form uses the default invitation template;
   there is no subject/body editor. Existing API/MCP template support is unchanged.
6. Select **Preview schedule & email** to open a modal showing full recipient
   emails, allocated times, sender/reply-to, subject, body and calendar attachment.
   Close it to adjust the schedule or reopen it using **Review schedule & email**.
   Nothing is sent during selection or preview.
7. Select **Confirm & send**. Schedules and delivery snapshots are committed first;
   background workers then send each email. The UI polls sent/failed/uncertain status.
8. **Interviews** lists candidates, readable dates/times, status badges and a dedicated
   **Actions** column. Button-styled links open the interview console, completed
   interview details and assessment reports. There is no Delivery column. Each row
   has a **Reschedule** button, disabled once the interview starts, finishes or is
   cancelled. Completed details and reports remain accessible; closed rooms are
   not presented as joinable consoles. Previous times remain expandable. Failed
   invitation retries appear with the row actions only when relevant, and are
   disabled for closed interviews. An email failure does not revert the schedule;
   uncertain/sent/superseded deliveries are never automatically retried.

Selection requires syntactically valid database emails, active/non-withdrawn applications,
usable processed CVs without unresolved extraction problems, and no active interview
for the same stage. This is **invitation eligibility**, not a return to a ranking review
queue: the three-outcome scoring/ranking policy remains unchanged. Recipients cannot
be arbitrary addresses supplied in a chat command. IANA-invalid, past, ambiguous and
nonexistent DST times are rejected. Conflicting interview slots must be changed;
there is no silent conflict override. Older shared/group schedules remain readable;
their history is preserved, but new previews and reschedules are sequential-only.

## Readable time display

App screens use dates such as **22 Oct 2026** and 12-hour times such as **8:00 AM**
or **5:05 PM**, without seconds or ISO offsets. Interview schedules, previews and
history use their saved time zone; other app timestamps use **Dhaka time**. The
candidate room, interviewer console, candidate details, job update times, CV ranking
updates and notification checks share this format. New invitation/reschedule email,
chat previews and HTML/PDF report timestamps use the same readable style. Overnight
ranges include both dates. Transcript positions remain elapsed minutes/seconds,
not wall-clock times. Invalid or missing dates do not crash pages.

Only presentation changes: API timestamps, YYYY-MM-DD/HH:mm form values, UTC
calendar events, saved invitation bodies, prior messages and existing report files
are preserved. New report requests use a new template version rather than silently
reusing old-format exports. No existing emails are resent by this change.

## Central chatbot and MCP

Use the existing central assistant, including on Interviews:

The assistant automatically uses sequential slots and defaults to `Asia/Dhaka`;
it asks for date, start time and duration, not scheduling mode or a missing time zone.
An existing choice such as “top 3” or “candidates above 70” stays in persistent
workflow state through date/time follow-ups and reloads, even if the command
interpreter mislabels a follow-up as selection. The user need not repeat it.
Without a choice, it asks “How many candidates from the top should I select, or
above which score should I select candidates?” Technical selection names are
kept internal. Supplying the date/time prepares an exact email preview; explicit
confirmation is still required before sending. Changing the selection invalidates
the old preview rather than sending to its previous recipients.

- “Schedule interviews for the top 5 frontend engineer candidates.”
- “Send invitations to candidates who scored more than 70.”
- “Select candidates scoring at least 80.”
- “Use 15 October 2026 at 10:00, 30 minutes, with a 10-minute buffer.”
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
`http://interview-mcp:8002/mcp`, resolved from root `mcp.json`. The registry also
contains native `localUrl` addresses; see [MCP configuration](mcp-configuration.md).
`INTERVIEW_BACKEND_URL` still configures where the scheduling server forwards
backend API calls, not the MCP client connection. SMTP secrets exist only in the backend process;
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
npm run test:interviews
```

Real PostgreSQL tests use `PGVECTOR_TEST_SERVER_URL` to create/drop **only disposable
test databases**. They verify concurrent confirmation/delivery and fresh-session persistence.
SMTP/MCP tests cover masking, threshold operators, ties, wrong-job rejection, missing
email, stale previews, sequential slots/group rejection/DST times, MIME and parsed ICS, partial failure,
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

Sequential-only simplification verified on 13 October 2026: 161 backend tests,
2 scheduling-default frontend tests and 7 scoring display tests passed, along with
the production build. Stage/time-zone/mode controls are removed from the form;
date, start time, duration and buffer remain. No migration or historical-record
rewrite is required. Delivery tests remained mocked.

Top-N selection correction: eligibility filtering now occurs **after** restricting
the candidate pool to the first N saved ranking entries. Existing active interviews
or invalid addresses reduce the invitation count rather than pulling candidates
from lower positions. A regression test reproduces top 3 incorrectly including
rank 6, and the backend suite now passes 162 tests. Existing schedules are not
changed; obtain a fresh selection preview before confirming an older workflow.

Conversation follow-up correction: candidate rules are no longer cleared solely
because the interpreter returns `selection` for a scheduling detail. Rules persist
through database reloads, and explicit rule changes receive a new preview. Tests
cover omitted choices, misclassified date/time messages, ordinal dates such as
“14th October”, and confirmation that attempts to change recipients. All 166
backend tests, 9 frontend tests and the production build passed; email tests were mocked.

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
