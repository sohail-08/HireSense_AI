# Candidate interview rooms — LiveKit Cloud

HireSense uses LiveKit Cloud for one-to-one camera/microphone interviews.
The website, backend, PostgreSQL and CV storage remain on the developer's laptop.
See [Cloud credentials and demo setup](livekit-cloud.md) and
[Cloudflare website access](cloudflare-demo.md).

## Workflow

```text
Existing scheduling UI / assistant → interview MCP / FastAPI
  → invitation preview → explicit confirmation → schedule + SMTP outbox
  → approved email/ICS with a private HireSense candidate link

Candidate link → FastAPI exchange → HTTP-only session cookie
  → explicit device check → waiting room + heartbeat
Assigned interviewer login → interview console → Admit
  → room-scoped participant JWTs → LiveKit Cloud audio/video
Confirmed End → durable access barrier → revoke both Cloud identities
  → delete Cloud room → completed interview
```

MCP carries authorized business operations, never media or LiveKit API secrets.
Candidates use `/interview/join/:token`; assigned interviewers use
`/interviews/:interviewId/console`. Neither room page has a central chatbot.

## Credentials and privacy

- Cloud API key/secret live only in the single root `.env` and backend process.
  Never put them in `VITE_*`, commit them, or send them to the browser.
- Private invitation bearers are HMAC-derived from a separate server secret,
  random nonce, invitation ID and application ID. Only their hashes and
  non-bearer derivation metadata are persisted. Outbox/calendar snapshots use
  `[[HIRESENSE_CANDIDATE_JOIN_LINK]]`; the reviewed URL is reconstructed transiently.
- Candidate sessions are hash-only in PostgreSQL. Raw values are HTTP-only,
  SameSite=Strict cookies; public HTTPS uses Secure cookies. Candidate requests
  do not carry an interviewer JWT and writes must match the frontend Origin.
- The invitation token is scrubbed from the address bar before exchange. Private
  link paths are not logged/cached by Nginx; SDK diagnostics are silenced. Do not
  add analytics, URL/body logging or token-bearing screenshots to these pages.
- Participant JWTs authorize only an exact room and opaque role identity, camera,
  microphone and subscription. Data, screen sharing, admin, recording and own
  metadata updates are disabled. Rooms have two participants maximum and names
  containing no candidate PII.
- Transport encryption is provided by LiveKit. Additional end-to-end encryption
  is not currently enabled. No recording, transcription or agent dispatch is
  enabled by HireSense. Do not add automatic egress/dispatch in the Cloud project
  without reviewing privacy requirements.

## Lifecycle and access

```text
scheduled → waiting → ready (admitted) → active (verified participants)
    └──────────────────────────────→ ending → ended/completed
cancelled / revoked / expired → no new candidate or media access
```

Scheduled times are informational, not join restrictions. Links expire after
30 days from issuance by default, sessions after 120 minutes (capped by invitation
expiry), and initial media JWTs after at most 120 seconds. LiveKit may refresh
tokens for connected clients, so server-side revocation—not initial expiry alone—
is essential when ending a room.

The backend requires an active interviewer role and the exact schedule owner.
Candidates require a valid invitation/session and explicit admission before media
access. Admission, token issuance and End use PostgreSQL row locks.

End first commits an `ending` barrier, revokes sessions and stops issuing tokens.
It then revokes both Cloud role identities with an explicit cutoff (including
disconnected participants), deletes the room and marks the interview completed.
A failed Cloud cleanup leaves `ending` for safe retry. Startup retries only
previously authorized incomplete endings. The host clock must be synchronized.

Leaving does not complete an interview. Rejoin remains permitted while access is
open. Candidate link replacement requires confirmation, invalidates old sessions
and retires the old Cloud room. It is blocked for admitted/active interviews.
Rescheduling reuses preview/confirmation and optimistic-lock rules; any obsolete
media room is retired before new credentials are issued.

## Files

| Area | Files |
| --- | --- |
| Cloud configuration and diagnostic | `backend/app/config.py`, `backend/app/check_livekit.py` |
| Official server SDK adapter | `backend/app/integrations/livekit_media.py` |
| Authorization, invitation and lifecycle | `backend/app/services/interview_rooms.py`, `interview_links.py` |
| Persistent state/API | `backend/app/models/interview.py`, `routes/interview_rooms.py`, `schemas/interview_room.py` |
| Interview pages | `frontend/src/pages/CandidateInterviewPage.tsx`, `InterviewerConsolePage.tsx` |
| Devices, media and typed requests | `frontend/src/components/interviews/DeviceCheck.tsx`, `InterviewMediaRoom.tsx`, `roomApi.ts`, `roomState.ts` |
| Website proxy/tunnel helpers | `frontend/nginx.conf`, `scripts/*cloudflare-demo*.ps1` |

Existing Alembic room/session migrations remain required. Removing a local media
server does not remove schedules, invitation state or database schema. Tests and
LiveKit SDK dependencies are not obsolete local-server files.

## Verification

Normal tests use mocked Cloud APIs/isolated databases and send no real emails:

```powershell
docker compose run --rm --no-deps --entrypoint python backend -m pytest -q -p no:cacheprovider
./scripts/test-cloudflare-demo.ps1
cd frontend
npm run test:rooms
npm run test:scoring
npm run test:interviews
npm run build
```

The read-only `python -m app.check_livekit --check-api` diagnostic verifies Cloud
configuration/authentication, not real media. Real synthetic RTC tests are opt-in
with `LIVEKIT_CLOUD_INTEGRATION=1` and `backend/requirements-room-test.txt`; they
consume Cloud usage but use no candidate data or business database. Before the
supervisor demo, test two devices on different networks, both directions of
audio/video, mic/camera controls, leave/rejoin, and rejection after End.

References: [Room Service API](https://docs.livekit.io/reference/other/roomservice-api/),
[token revocation](https://docs.livekit.io/frontends/reference/tokens-grants/),
[encryption](https://docs.livekit.io/transport/encryption/).
