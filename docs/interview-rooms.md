# Candidate interview rooms — self-hosted LiveKit

HireSense now has a public candidate device-check/waiting room and an authenticated,
assigned-interviewer console. Existing schedules, applications, JWT sign-in,
confirmed email previews, SMTP outbox and MCP tools are reused. No new LangGraph,
candidate account, OAuth flow, external calendar API, custom signaling server,
recording, transcription, screen sharing, chat or group interview was added.

## Architecture and credentials

```text
Existing scheduling UI / central assistant → existing interview MCP / FastAPI
  → invitation preview → explicit confirmation → schedule + SMTP outbox
  → email / ICS containing the same approved HireSense candidate link

Candidate link → FastAPI exchange → HTTP-only candidate session cookie
  → explicit device check → waiting + heartbeat polling
Assigned interviewer JWT → interview console → Admit
  → FastAPI issues two room-scoped participant JWTs
  → browser SDKs ↔ self-hosted LiveKit (signaling + WebRTC audio/video)
Interviewer confirms End → durable access barrier → LiveKit DeleteRoom → completed
```

MCP never carries media or LiveKit credentials. FastAPI provides authorization and
room lifecycle, while LiveKit carries real-time media. The interviewer console is
`/interviews/:interviewId/console`; candidates enter at `/interview/join/:token`.
Both are standalone pages; the candidate page has no account navigation or chatbot.

There are three distinct credentials:

| Credential | Storage and purpose | Default lifetime |
| --- | --- | --- |
| HireSense invitation token | SHA-256 hash in schedule; binds invitation ID and application; email contains the bearer URL | 30 days from issuance, independent of booked times |
| Candidate session | SHA-256 hash in `candidate_interview_sessions`; raw value only in HTTP-only, SameSite=Strict cookie | 120 minutes, additionally capped by invitation expiry |
| LiveKit participant JWT | Transient backend response and SDK memory only; opaque identity and exact room | At most 120 seconds for connection/reconnection authorization |

The invitation bearer is an HMAC-SHA256 value derived from an independent server
secret, a CSPRNG 32-byte nonce, invitation UUID and application ID. Only its hash
and **non-bearer derivation metadata** are persisted. The raw bearer is not stored
in schedules, outbox, calendar snapshots, confirmation payloads or chatbot history.
Persisted email text contains `[[HIRESENSE_CANDIDATE_JOIN_LINK]]`; the exact reviewed
link is reconstructed only in responses or a transient SMTP transport copy. This
allows preview/send/retrieve parity without plaintext credential persistence.
Keep `INTERVIEW_LINK_SECRET` private and stable; changing it requires link rotation.
Native tests/backward-compatible settings can fall back to the JWT secret; Compose
requires the independent invitation secret.

The candidate URL is removed from browser history before exchange. Candidate API
calls use the cookie, not the email token or interviewer JWT. No candidate bearer
or LiveKit credential is written to browser local/session storage. Device selections
are not persisted. Nginx disables candidate-link access logging and adds no-store
and no-referrer headers. SDK diagnostics are silenced; API errors do not echo tokens.
Do not add analytics, request-body logging or URL-based error tracking on these paths.

## Lifecycle, anytime joining and authorization

```text
scheduled → waiting → ready (admitted) → active (server-verified participants)
    └──────────────────────────────→ ending → ended
cancelled / revoked / expired → no candidate access or new participant JWT
```

`room_status` is separate from the pre-existing scheduling `status`. End sets
`room_status=ended` and `status=completed`, freeing the existing active-stage index.
Leaving/disconnecting does not complete the schedule or revoke admission; rejoin is
allowed while the link/session remain valid. An unadmitted waiting candidate
who leaves clears waiting state. Waiting heartbeats are fresh for 45 seconds.

Candidates and interviewers may join before or after the scheduled slot. Booked
times are displayed for planning only; there is no early/late admission or media
cutoff. Candidates still wait for interviewer admission. Secure links expire after
`INTERVIEW_LINK_MAX_DAYS` (30 days by default) and sessions/JWTs remain short-lived.
Expired, revoked, cancelled, ending and ended access remains blocked. For a booking
farther away than the link lifetime, the interviewer can issue a fresh link later
without rescheduling the interview just to obtain access.

All controls are checked in FastAPI: active interviewer role **and schedule owner**.
The existing single-interviewer account constraint is preserved. Candidate bodies
cannot supply a different interview ID, application ID or role. Candidate JWTs are
not issued before admission. Participant identities are opaque room UUID + role
suffix; names are only `Candidate` and `Interviewer`. Tokens allow exact-room join,
subscribe and camera/microphone publish; data, screen sharing, administration,
recording, room creation/listing and own metadata changes are disabled. Maximum
room size is two. A second browser using the same role reconnects/replaces that
identity; it does not create a third participant.

Admission, token issuance and End use PostgreSQL row locks. End first commits an
`ending` barrier and revokes candidate sessions, then deletes the LiveKit room,
then records end time/actor and completion. If LiveKit is unavailable, the room
remains `ending`, new credentials are denied, and **Retry ending interview** is safe.
Startup retries only these previously authorized incomplete endings.

Self-hosted LiveKit cannot revoke a previously issued participant JWT in the same
way as LiveKit Cloud. Therefore `room.auto_create: false` is mandatory here: the
backend explicitly creates rooms, and a cached JWT cannot recreate one after End.
Rotation creates a new opaque media room. Rescheduling preserves a still-valid
HireSense invitation identity but always retires the previous media room, invalidates
candidate sessions and refreshes the link's credential lifetime. Pending old rooms are deleted before
any new media credential is issued or when End/revoke/rotation runs. Rescheduling
an admitted/active interview is rejected. Do not enable automatic room creation.
See [LiveKit token/revocation behavior](https://docs.livekit.io/frontends/reference/tokens-grants/)
and the [server configuration](https://github.com/livekit/livekit/blob/v1.13.9/config-sample.yaml).

## Environment and local startup

Use the **root `.env` only**. `.env.example` is a tracked template, not another active
environment file. Existing database/Gemini/Discord/Gmail settings are unchanged.
Never put server secrets in `VITE_*` settings or commit `.env`.

| Variable | Local/default setting or purpose |
| --- | --- |
| `LIVEKIT_API_KEY` | Private key identifier; generate a unique value |
| `LIVEKIT_API_SECRET` | Random secret, at least 32 characters |
| `INTERVIEW_LINK_SECRET` | Separate random secret, at least 32 characters; preserve across restart |
| `LIVEKIT_API_URL` | Native backend/test HTTP address: `http://localhost:7880`; Compose overrides with `http://livekit:7880` |
| `LIVEKIT_PUBLIC_URL` | Browser signaling URL: `ws://localhost:7880` locally; `wss://` in production |
| `LIVEKIT_NODE_IP` | `127.0.0.1` for same-computer Docker Desktop tests; real advertised media IP in deployment |
| `INTERVIEW_JOIN_BASE_URL` | `http://localhost:5173` locally; public HTTPS HireSense origin in deployment |
| `FRONTEND_URL` | Same origin as the browser app; used for CORS and candidate POST origin checks |
| `LIVEKIT_TOKEN_TTL_SECONDS` | `120`, bounded 30–300 |
| `LIVEKIT_API_TIMEOUT_SECONDS` | `5` |
| `INTERVIEW_LINK_MAX_DAYS` | `30` days of credential validity from issuance/renewal, not a scheduled-time restriction |
| `CANDIDATE_SESSION_MINUTES` | `120` |
| `CANDIDATE_COOKIE_SECURE` | `false` **only for localhost development**; `true` in production |
| `CANDIDATE_PUBLIC_RATE_LIMIT` | `20` invitation exchanges per source per minute |
| `CANDIDATE_WAITING_HEARTBEAT_SECONDS` | `45` |

Generate independent strong secrets using your password manager or a cryptographic
random generator. Existing secrets in your `.env` were retained; new LiveKit and
invitation keys were generated privately during implementation.

From the repository root:

```powershell
docker compose config -q
docker compose up -d --build
docker compose ps
```

The backend entrypoint runs Alembic `upgrade head` before starting FastAPI. Migration
`0017_interview_rooms` extends existing schedules/deliveries and adds the candidate
session table; it does not delete or replace users, candidates, scores or schedules.
Migration `0018_anytime_interview_access` removes the legacy schedule-based expiry
cap from still-valid, unrevoked links on open interviews, preserving their URL and
hash. It never reactivates expired/revoked links or ended/cancelled rooms. Old
unconfirmed previews must be recreated under the new access policy. Downgrade does
not guess or shorten original expirations; the previous application version itself
enforces its original scheduled-window policy.
Existing schedules have no new link automatically; use their console's **Generate
candidate link** and share privately, or review/confirm a reschedule notification.
Historical sent emails are not rewritten or resent automatically.

Pinned media versions: server `v1.13.9`, Python server SDK `livekit-api==1.2.1`,
browser `livekit-client==2.22.4`, React components `2.9.24`, styles `1.2.0`.
Optional synthetic RTC test SDK: `livekit==1.1.20`; not installed in production images.

## Local reviewer test — two browser sessions

This configuration is **same-computer localhost testing**, not a remote candidate
deployment. A `localhost` invitation received on another computer points to that
computer, not HireSense. Do not send such links to real remote applicants.

1. Sign in as the interviewer at `http://localhost:5173`. Use a test application
   whose email you control. Choose it from an existing ranking and schedule a slot
   at any future date/time. Joining can be tested immediately, regardless of the slot.
2. Preview the invitation. Confirm the HireSense URL is present. Confirm & send
   only if actual delivery is intended; delivery tests use mocks, not Gmail.
   For mail-only local capture, deliberately configure the existing Mailpit profile
   as described in `interview-scheduling.md` instead of Gmail. No SMTP settings are
   changed automatically.
3. On **Interviews**, choose **Open console**. **Copy candidate link** provides the
   private URL without sending email. Paste it into an incognito window or another
   browser profile. No candidate login is required. The token disappears from the
   address bar after validation; refreshing uses the session cookie.
4. The candidate clicks **Check devices**. Preview/select the camera/microphone,
   verify the microphone level, try camera/mic off, then **Continue to waiting room**.
   Grant permissions only when asked after the explicit click. No LiveKit connection
   is created while waiting.
5. The interviewer sees **Candidate is waiting**, clicks **Admit candidate**, checks
   their devices, then **Join interview room**. Both see two safe-labelled video tiles.
   If autoplay is blocked, click **Enable interview audio**. Avoid audio feedback
   when both sessions are on one computer; use headphones/mute one microphone.
6. Test microphone mute/unmute and camera on/off independently. Leave/rejoin from
   either side: the schedule must remain open, not become completed.
7. The interviewer clicks **End interview for everyone**, then **Confirm end interview**.
   Both disconnect; the candidate sees ended/closing status; the schedule is completed.
   Reopen the original invitation: it cannot re-enter or obtain a new media JWT.
8. Test joining well before and after the booked slot, plus invalid/replaced/revoked
   links and permission denial. No candidate details should appear in link errors.
   After session expiry, reopen a still-valid invitation to establish a new session.
   For a fresh future schedule, preview
   rescheduling, verify link preservation when valid, then confirm the updated email.

## Automated checks

Normal CI-safe tests use a fake media administration client and fake email transport.
Frontend state tests mock the official components; they are not media/browser E2E.

```powershell
# Repository root — synthetic data, no migrations of the business database
docker compose run --rm --no-deps backend python -m pytest -q -p no:cacheprovider

# Frontend directory
npm ci
npm run test:rooms
npm run test:interviews
npm run test:scoring
npm run build
npm audit
```

`npm run build` includes TypeScript checking. There is no separate existing lint
script. The browser media SDK is lazy-loaded only for interview pages; its ~565 KB
chunk produces Vite's standard size warning, not a build/type-check failure.

Actual PostgreSQL row-lock test (creates/removes only a randomly named test database):

```powershell
# Root; credentials are taken internally, not printed or placed in the command
docker compose run --rm --no-deps backend python -c "import os, pytest; from app.config import get_settings; os.environ['PGVECTOR_TEST_SERVER_URL']=get_settings().database_url; raise SystemExit(pytest.main(['-q','-p','no:cacheprovider','tests/test_interview_room_postgres.py']))"
```

Separate **real local LiveKit integration command**, run in `backend` on the Docker
host (not inside the backend container, because local advertised RTC IP is loopback):

```powershell
# Install the application's requirements in your local venv if not already present
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-room-test.txt
$env:LIVEKIT_INTEGRATION = '1'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_livekit_integration.py
Remove-Item Env:LIVEKIT_INTEGRATION
```

This creates only UUID-named `hs-test-*` rooms, checks real Room Service creation,
list/delete/idempotence, connects two isolated RTC clients, publishes/receives
synthetic video and audio, checks mute/unmute, deletes the room, observes both
disconnects and verifies a cached JWT cannot recreate it. Synthetic frames live in
memory only, not files or PostgreSQL. It needs no physical devices, candidate emails,
cloud account or paid service. Normal tests skip this unless explicitly enabled.
The SDK may print a harmless v1-to-v0 signaling fallback warning against the pinned
server, including when testing a denied join after deletion; it contains no token.

The repository had no Playwright suite, so no full two-browser media E2E was added
or claimed. Use the local RTC integration plus the manual two-browser checklist
to verify the actual browser permissions, layout and media controls.

### Anytime joining update — 13 October 2026

Backend regression suite: **188 passed, 9 opt-in tests skipped**. Frontend room
tests: **16 passed** (the obsolete too-early error case was removed); TypeScript
and local/Docker builds passed. The separate PostgreSQL concurrency check passed.
Migration `0018_anytime_interview_access` is applied in the running app. Existing
invitation identity checksums and schedule count are unchanged; a private backup
was saved before migration. HTTP health checks and Docker service health passed.
No real invitation emails were sent during this update.

After an earlier too-early error, **reopen the original emailed/copied invitation**
instead of refreshing the bare `/interview/join` page: the old flow removed the token
from the address bar before that failed exchange had established a session cookie.

### Initial feature verification — 13 October 2026 (before anytime joining update)

- Deployed backend image: **180 passed, 9 opt-in tests skipped**. One existing
  LangGraph pending-deprecation warning remains; it is not a failed test.
- Separate PostgreSQL admission/End concurrency check: passed on a disposable
  database, together with the complete interview security/scheduling subset
  (**36 passed**). The temporary database was removed by the test fixture.
- Real local LiveKit Room Service and two synthetic audio/video clients: **2 passed**.
- Frontend room states/security/control tests: **17 passed**; existing interview
  scheduling tests: **2 passed**; existing scoring-display tests: **7 passed**.
- TypeScript/Vite local and Docker builds: passed. The lazy SDK chunk size warning
  remains informational. Dependency audit: **0 vulnerabilities**.
- Compose validation and backend/MCP/LiveKit health checks: passed. Frontend HTTP
  health and candidate-page checks: 200; protected unauthenticated room API: 401;
  invalid invitation: generic 403. Candidate page returned no-referrer/no-store.
- Actual PostgreSQL migration: head is `0017_interview_rooms`. All previous business
  table value checksums and row counts match the pre-migration snapshot; interviewer
  login and all existing records were preserved. New candidate-session table is empty.
  A private pre-migration dump is in ignored `backend/storage/backups/`.
- No actual invitation email was sent during these checks. No full browser media
  E2E/physical-device or remote public TLS/TURN test was run; those need the manual
  checklist and a separately configured production network.

## Production networking and security

The checked-in Compose ports are deliberately bound to loopback. Production needs
an explicit networking deployment, not just sending the localhost invitation.

- Serve HireSense on trusted **HTTPS** and use a public HTTPS join base. Camera and
  microphone APIs require a secure context outside localhost. Keep the same origin
  for frontend and `/api` so Strict candidate cookies work. Set cookie Secure=true.
- Give LiveKit a public domain and trusted TLS; browser URL must be `wss://`.
  The backend's private HTTP Room Service address is independent of that public URL.
- Publicly route HTTP/WebSocket signaling (typically TLS 443 to internal 7880).
  Configure the correct public/advertised RTC IP and supported external-IP discovery.
  `127.0.0.1` and `use_external_ip:false` are development-only settings.
- Open and map media separately: this local config uses TCP 7881 and multiplexed
  UDP 7882. A production port-range deployment needs the range configured on both
  LiveKit and its firewall/load balancer. Ordinary Nginx HTTP proxying does not
  carry RTC UDP media. Validate actual reachability from outside the host.
- Configure TURN/TLS fallback for restrictive networks, trusted TURN TLS/domain,
  appropriate TURN UDP/TCP/TLS ports and deployment-specific firewall rules. TURN
  is **not** bundled/enabled by this local config. See [LiveKit ports/firewall](https://docs.livekit.io/transport/self-hosting/ports-firewall/)
  and [self-hosting deployment](https://docs.livekit.io/oss/test-monitor/).
- Preserve `room.auto_create:false`, unique secrets, room limit two and participant
  permission restrictions. No egress/recording/ingress service is deployed.
- Preserve no-referrer/no-store and sensitive-path logging suppression in every
  outer proxy/CDN. Do not log WebSocket query credentials, bodies or cookies.
- The built-in bounded rate limiter is for the current single-worker app. It keys
  by the actual connection peer, not untrusted forwarded headers; behind the current
  Nginx proxy the source bucket is conservatively shared. Multiple replicas/public
  deployments need shared edge/Redis rate limiting and a deliberately trusted proxy
  configuration. Do not trust arbitrary `X-Forwarded-For`.
- Monitor failures using interview IDs, not bearer URLs or candidate media. Failed
  deletion leaves durable `ending`; restart recovery or explicit End retries it.
  Keep private database backups and secrets protected. Expired session hashes can
  be pruned under a retention policy; no media is retained by this implementation.

## Affected folder structure and complete file manifest

`+` created; `~` modified. Paths are repository-relative. Runtime `.env` and all
existing private storage/backups remain ignored. Unrelated files are omitted.

```text
hiresense/
├── ~ .env                              (private, ignored)
├── ~ .env.example
├── ~ docker-compose.yml
├── ~ README.md
├── livekit/
│   └── + livekit.yaml
├── docs/
│   ├── + interview-rooms.md
│   └── ~ interview-scheduling.md
├── backend/
│   ├── ~ requirements.txt
│   ├── + requirements-room-test.txt
│   ├── alembic/versions/+ 0017_interview_rooms.py, + 0018_anytime_interview_access.py
│   ├── app/
│   │   ├── ~ config.py
│   │   ├── ~ main.py
│   │   ├── integrations/+ livekit_media.py
│   │   ├── models/~ __init__.py, ~ interview.py
│   │   ├── schemas/~ interview.py, + interview_room.py
│   │   ├── routes/+ interview_rooms.py
│   │   └── services/
│   │       ├── + interview_links.py
│   │       ├── + interview_rooms.py
│   │       ├── ~ interview_service.py
│   │       ├── ~ interview_assistant_service.py
│   │       ├── ~ supervisor_service.py
│   │       └── ~ candidate_application_service.py
│   └── tests/
│       ├── + test_interview_rooms.py
│       ├── + test_interview_room_postgres.py
│       └── + test_livekit_integration.py
└── frontend/
    ├── ~ nginx.conf
    ├── ~ package.json, ~ package-lock.json
    ├── ~ vite.config.ts
    ├── + vitest.rooms.config.ts
    ├── src/
    │   ├── ~ App.tsx, ~ index.css
    │   ├── api/~ apiClient.ts
    │   ├── components/interviews/
    │   │   ├── + DeviceCheck.tsx
    │   │   ├── + InterviewMediaRoom.tsx
    │   │   ├── + roomApi.ts
    │   │   └── + roomState.ts
    │   └── pages/
    │       ├── + CandidateInterviewPage.tsx
    │       ├── + InterviewerConsolePage.tsx
    │       └── ~ InterviewsPage.tsx
    └── tests/rooms/
        ├── + setup.tsx
        ├── + candidate.test.tsx
        ├── + console.test.tsx
        └── + media.test.tsx
```

| File(s) | Purpose |
| --- | --- |
| `.env`, `.env.example` | Private local keys/settings and safe public template |
| `docker-compose.yml`, `livekit/livekit.yaml` | Pinned local server, health/networking, keys from environment, no auto-create |
| `README.md`, `docs/interview-scheduling.md`, `docs/interview-rooms.md` | Current milestone, scheduling cross-reference, full setup/test/security/file guide |
| `backend/requirements.txt` | Official server SDK |
| `backend/requirements-room-test.txt` | Optional host-only RTC integration dependencies |
| `backend/alembic/versions/0017_interview_rooms.py` | Additive migration, session table, constraints/indexes and legacy-state backfill |
| `backend/alembic/versions/0018_anytime_interview_access.py` | Extend still-valid open-interview invitations without changing their bearer identity or reviving denied access |
| `backend/app/config.py` | Typed settings, bounds and invitation-secret validation |
| `backend/app/main.py` | Room routes, credentialed exact-origin CORS, safe validation errors and ending recovery |
| `backend/app/models/interview.py`, `backend/app/models/__init__.py` | Extend schedules/deliveries, define/export hash-only sessions |
| `backend/app/schemas/interview.py` | Join URL preview and room-status schedule response fields |
| `backend/app/schemas/interview_room.py` | Strict room request/response models; reject forged extra fields |
| `backend/app/routes/interview_rooms.py` | Interviewer APIs, cookie exchange/session APIs, rate/origin boundaries and safe errors |
| `backend/app/integrations/livekit_media.py` | Restricted official JWTs and Room Service operations with injected/fake boundary |
| `backend/app/services/interview_links.py` | HMAC/hash generation, redaction and transient email/ICS reconstruction |
| `backend/app/services/interview_rooms.py` | Authorization, credential expiry, admission, verified presence, rotation, durable End/recovery |
| `backend/app/services/interview_service.py` | Links in exact previews/outbox, current-link delivery checks and secure rescheduling |
| `backend/app/services/interview_assistant_service.py`, `backend/app/services/supervisor_service.py` | Redact raw join URLs before persisted chat/workflow snapshots |
| `backend/app/services/candidate_application_service.py` | Remove candidate session rows with application/schedule deletion |
| `backend/tests/test_interview_rooms.py` | Hash/session, grants, lifecycle, APIs, reschedule/recovery and migration preservation |
| `backend/tests/test_interview_room_postgres.py` | Real concurrent admission/End row-lock checks on disposable database |
| `backend/tests/test_livekit_integration.py` | Opt-in real Room Service and two synthetic RTC clients |
| `frontend/nginx.conf` | Candidate-route privacy headers and URL-log suppression; media remains separate |
| `frontend/package.json`, `frontend/package-lock.json` | Pinned SDK/test dependencies and test script |
| `frontend/vite.config.ts`, `frontend/src/App.tsx` | Split SDK bundle, lazy public and protected room routes |
| `frontend/vitest.rooms.config.ts` | Isolated JSDOM room-test configuration |
| `frontend/src/api/apiClient.ts` | Export existing API base for candidate cookie client |
| `frontend/src/index.css` | Hide irrelevant PreJoin username input |
| `frontend/src/components/interviews/roomApi.ts` | Typed room APIs; candidate cookie requests do not send interviewer JWT |
| `frontend/src/components/interviews/roomState.ts` | Safe link/device errors and explicit-zone time display |
| `frontend/src/components/interviews/DeviceCheck.tsx` | Explicit-action official PreJoin and unsupported-browser guidance |
| `frontend/src/components/interviews/InterviewMediaRoom.tsx` | Two tiles, remote audio/autoplay, camera/mic, leave and owner End callback |
| `frontend/src/pages/CandidateInterviewPage.tsx` | Validation, URL scrub, waiting polling, admission, leave/rejoin and closure |
| `frontend/src/pages/InterviewerConsolePage.tsx` | Assigned interviewer summary/control, private link clipboard, admission and confirmed End |
| `frontend/src/pages/InterviewsPage.tsx` | Open-console entry from existing schedules |
| `frontend/tests/rooms/setup.tsx` | Fake official components/media states and cleanup |
| `frontend/tests/rooms/candidate.test.tsx` | Link states, permissions, waiting/admission, leave and late-response safety |
| `frontend/tests/rooms/console.test.tsx` | Authorization, admission and confirmed/ended UI |
| `frontend/tests/rooms/media.test.tsx` | Track states, audio renderer, reconnection/device errors and leave vs deletion |

## Suggested Git checkpoints

No Git add/commit/push is performed by the implementation. Changes are delivered
together and tests run against the integrated working tree. These are suggested
logical review boundaries, not claims that every possible partial staging order
has been independently tested. Keep dependent pieces together to remain runnable:

1. `chore: configure self-hosted LiveKit and private interview settings` — settings,
   dependency, template, Compose and server config; never stage the real `.env`.
2. `feat: add interview room lifecycle and hashed candidate-session schema` — model,
   exports and migration together.
3. `feat: secure candidate interview access and LiveKit room lifecycle` — link/media/
   room services, schemas, APIs, main recovery, chat redaction and deletion cleanup
   together. Apply redaction before any invitation credential can enter chat state.
   This safely introduces backend controls before frontend routes are available.
4. `feat: add candidate waiting room and assigned interviewer LiveKit console`
   — frontend dependencies, routes, device/media/pages, privacy Nginx and bundle config.
5. `feat: include private interview links in confirmed invitations and reschedules`
   — scheduling previews, transient outbox rendering and version/lock safeguards;
   candidate pages are available before new invitations start including their links.
6. `test: cover interview security lifecycle UI and local LiveKit media` — backend,
   PostgreSQL, frontend and optional real RTC tests plus test dependency/config.
7. `docs: document interview room setup privacy testing and production networking`
   — README and both guides.

If staging incrementally, move the frontend Vitest dev dependencies and `test:rooms`
script with checkpoint 6, or include its configuration/tests with checkpoint 4.
Run migrations/tests/build after each staged checkpoint before committing/pushing.
