# Live interview transcription

## Transcript presentation

Captions are interviewer-only and use a two-sided messenger layout: the interviewer's speech appears on the
right in dark blue; the other participant's speech appears on the left in soft
mint. Candidates have no transcript panel or caption subscription.
Exact elapsed timestamps sit below the bubbles. Repeated initial badges and
visible role labels are omitted; accessible article names still identify the
speaker, elapsed time and draft/final state. Close consecutive segments from the
same speaker have tighter spacing but are never merged or rewritten.

Long messages wrap within the bubble, including unbroken text, with wider bubble
limits on mobile. Live drafts retain their explicit marker. Consent, saved-text
access, failure notices, source data and manual-scroll/auto-follow behavior are
unchanged. Closed interviews still use page scrolling; live panels retain their
existing bounded scrolling. Tests are synthetic; no interview is started for UI checks.

## Scope and trust boundaries

The existing LiveKit Cloud video interview remains unchanged. A separately deployed,
hidden LiveKit Agents participant subscribes only to the two trusted microphone
identities after both participants explicitly consent and the owner starts STT.
No recording, evaluation, summarization, translation or mixed-speaker diarization is
implemented. The feature is disabled by default and the worker is an opt-in Compose profile.

Microphone tracks -> Agents worker -> separate Nova-3 WebSockets -> LiveKit text
streams addressed only to the assigned interviewer -> React captions. An empty
recipient list fails closed and never becomes a broadcast. Final text also goes through an authenticated, text-only
FastAPI repository boundary to PostgreSQL. The Nginx public site blocks the internal
worker API; its bearer authentication remains mandatory even on the Docker network.
The worker gets no candidate-login, JWT-signing, Google, Gemini or SMTP credentials.

SDKs verified for this implementation: existing `livekit-api==1.2.1`, browser
`livekit-client==2.22.4`; new `livekit-agents==1.8.8`,
`livekit-plugins-deepgram==1.8.8`, Python RTC `livekit==1.1.20`.
The official plugin exposes `SpeechData.start_time/end_time/confidence/words` and
`SpeechEvent.request_id`, so a second provider SDK is unnecessary. `AgentSession`
(which would introduce a voice assistant) is deliberately not used.

Official references checked:

- [Deepgram plugin](https://docs.livekit.io/agents/models/stt/deepgram/)
- [Explicit agent dispatch](https://docs.livekit.io/agents/server/agent-dispatch/)
- [Text streams](https://docs.livekit.io/transport/data/text-streams/)
- [Deepgram keyterm limits](https://developers.deepgram.com/docs/keyterm)

## Configuration and manual setup

1. Create a Deepgram project/API key with streaming speech recognition permission
   in the Deepgram console. Check that the account has quota/credit; real streaming
   can incur charges. Normal tests use mocks and do not contact Deepgram.
2. Add the values below to the **single root `.env`**. Generate a separate random
   worker secret, for example `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
   Never send any secret to a browser, chat, source control or a LiveKit participant token.
3. Retain your existing LiveKit Cloud URL/key/secret. The worker registers itself
   under `hiresense-transcriber`; no Cloud voice-agent deployment is required.
4. End any existing interview before rebuilding/restarting backend or frontend.
   Preserve the current public Cloudflare origin when applying Compose overrides;
   do not accidentally switch invitations back to localhost.
5. Build images and start the worker with the `transcription` profile, as below.

Required/new settings (no actual secret values are shown):

```ini
TRANSCRIPTION_ENABLED=true
TRANSCRIPTION_WORKER_SECRET=<separate-random-secret-at-least-32-characters>
DEEPGRAM_API_KEY=<private-deepgram-key>
DEEPGRAM_MODEL=nova-3
DEEPGRAM_LANGUAGE=en-US
DEEPGRAM_ENDPOINTING_MS=300
DEEPGRAM_UTTERANCE_END_MS=1000
TRANSCRIPTION_INTERIM_RESULTS=true
TRANSCRIPTION_AGENT_NAME=hiresense-transcriber
TRANSCRIPTION_RETENTION_DAYS=30
TRANSCRIPTION_QUEUE_SIZE=128
TRANSCRIPTION_MAX_RETRIES=3
TRANSCRIPTION_FLUSH_SECONDS=4
```

Existing required media settings: `LIVEKIT_CLOUD_URL`, `LIVEKIT_CLOUD_API_KEY`,
`LIVEKIT_CLOUD_API_SECRET`. The Deepgram key is injected only into the worker.
Model/language/timing settings are snapshotted by the backend and sent to the worker
at claim time, preventing backend/worker configuration drift.

```powershell
docker compose --profile transcription build backend frontend transcription-worker
# Local website only; Cloudflare users should preserve their existing overlay/origin.
docker compose --profile transcription up -d backend frontend transcription-worker
docker compose --profile transcription ps
```

The existing backend entrypoint runs `alembic upgrade head` (new revision `0020`).
No production `create_all()` is used. The worker health endpoint is container-local
port 8081, and reflects Agents connectivity, not a successful Deepgram recognition.
There is no worker port exposed publicly. Missing Deepgram credentials fail a claimed
session safely with `missing_deepgram_key`; they never fall back to another provider.

Initial endpointing is 300ms of silence and utterance-end is 1000ms. These are starting
settings, not benchmark winners. Nova-3 uses explicit English, punctuation, smart
formatting, interim results, and VAD events. Diarization and language detection are off.
Keyterms are deterministic short ASCII title/technical-skill hints from the approved
profile, not instructions. They have a conservative 200-character total budget,
below the provider's 500-token limit. No candidate names/CV prose are sent as hints.
On an options rejection (HTTP 400), one bounded retry omits hints and records that
they were not applied; the original hint snapshot remains available for audit.

## Lifecycle and permissions

`not_started -> starting -> active -> stopping -> completed`; failures become
`failed`. A retry after failure creates a fresh session, preserving earlier final
text. Refresh never starts an agent. Duplicate start requests under the locked
interview row return the existing open session. An atomic worker claim prevents
duplicate dispatches from opening streams. A worker that loses its lease cannot
write or reactivate the session. Missing heartbeats/startup expire safely on status
checks; they do not silently restart STT or send more audio.

Both participants may explicitly consent/revoke their own consent. The candidate
uses their existing HttpOnly interview-session cookie, not an interviewer JWT.
Revocation requests stop; the worker checks the shared state on each heartbeat.
Already queued speech may finalize during the bounded stop interval. Only the
assigned active interviewer can start/stop, access persisted history or delete it.
Candidate access is scoped to that candidate session and exposes no saved transcript
history, CV, metrics, caption verification keys or provider credentials. The
candidate's compact permissions checkbox records consent without exposing the
transcript. Only the assigned interviewer receives live captions, addressed by
server-provided participant identity. Rejoining does not delete final text.

Endpoints follow `/api/interview-rooms/{id}/transcription/{status,consent,start,stop}`
and `/api/interview-rooms/{id}/transcript` (GET paginated, DELETE after stop).
Candidates have only `/api/interview-rooms/candidate/transcription/{status,consent}`.
Worker POST operations are `/api/internal/transcription/{session_id}/{claim,update,streams,segments}`;
they require both the shared backend/worker secret and an exclusive session claim.
The claim is stored as a hash and never appears in live caption events.

Ending the interview requests stop before deleting the LiveKit room, allows a bounded
12-second drain, and records shutdown failure if needed. Transcription failure never
ends the video interview. A stopped transcription can be restarted as a new session
without ending the call. Provider retries have backoff/jitter and a fixed budget.
New provider connections get new IDs and server-issued timeline anchors. Only
trusted exact identities (`<room>-i`, `<room>-c`) supply speaker mapping, never display
names or client-provided roles. Normal users cannot publish LiveKit data streams;
LiveKit omits the wire sender identity for a hidden participant. Each worker therefore
generates an ephemeral P-256 signing key and binds its public JWK to its exclusive
session claim through the authenticated worker API. React verifies every current-worker
caption with WebCrypto against that backend-provided public key, then checks consent,
session, role, timing and stable final ID. The private key never leaves worker memory.
Unsigned empty-sender messages, altered captions, another session's signatures and
unexpected nonempty sender identities are rejected. React renders plain text, not HTML.

## Persistence, privacy, retention and deletion

- HireSense stores only final text, role/reference, opaque identity, track SID,
  provider request ID, stable segment key/sequence, confidence, UTC and millisecond
  offsets, optional word timing JSONB, configuration/keyterms, consent and metrics.
- Interim revisions are transient, coalesced per speaker; they are not DB rows.
- Final events use a bounded queue (default 128), small transactions, finite retry
  backoff, uniqueness constraints and conflict detection. A final is advertised as
  saved only after persistence succeeds. A queue overflow/DB failure stops STT with
  an explicit failure, not a fabricated saved result. Some unsaved text can be lost
  on exhausted retries or abrupt machine failure; no raw audio replay exists.
- Deepgram receives microphone audio and the minimal technical hints. HireSense
  neither records nor stores raw audio/video. This does **not** assert that the
  external provider retains no data: review the account's Deepgram processing,
  retention and model-improvement settings before using real candidate data.
- Application/SDK logging is filtered; application metrics log only opaque IDs,
  status and numeric measurements, never transcript text or credentials.
- Final history expires from API access after `TRANSCRIPTION_RETENTION_DAYS`.
  Physical deletion is explicit maintenance, not a hidden background scheduler:
  `docker compose exec backend python -m app.purge_transcripts --purge-expired`.
  This preserves interview schedules and consent records. Arrange regular execution
  according to your retention policy; until then expired rows remain physically
  stored. Database backups require their own retention/deletion policy.
- An interviewer can DELETE `/api/interview-rooms/{id}/transcript` after STT ends;
  it removes all sessions, streams, segments and consent for that interview.
  Application/job deletion also removes related transcript data. No new delete
  button was added to the live controls to avoid accidental in-interview deletion.

## Timestamp and latency meaning

Each session has a backend UTC start. Each microphone connection obtains a backend
offset anchor; provider-relative word/segment times are added to this anchor.
Interviewer and candidate run independently, so overlapping timestamps are valid.
Within a speaker, finals are monotonic; original provider timing is retained. New
connections never reuse an old provider clock. The UI uses MM:SS or HH:MM:SS and
restores saved finals in UTC timestamp order, deduplicating LiveKit/API copies.
Each restart has a new session-local timeline; UTC fields order sessions correctly.

Runtime metrics include audio frames, latest observed interim/final audio-frame-to-
text latency, persistence latency, connection duration, reconnects, low-confidence
and empty results. These are operational samples, not an accuracy benchmark or proof
of end-of-speech latency. Frame delivery/network jitter and server anchor round trips
can affect alignment. SDK-internal dropped-frame counts are not exposed, so no zero
drop guarantee or invented count is reported. RTC input is bounded to 100 frames;
the provider SDK has its own internal buffering.

## Automated and manual tests

```powershell
cd backend
.venv/Scripts/python.exe -m pytest -q tests --ignore=tests/transcription_worker
.venv/Scripts/python.exe -m pytest -q tests/transcription_worker
cd ../frontend
npm.cmd run test:rooms
npm.cmd run test:scoring
npm.cmd run test:interviews
npm.cmd run build
```

Worker contract tests use only mock backends/providers. For SDK-backed worker tests,
build its image and override the command with
`docker compose --profile transcription run --rm --no-deps transcription-worker python -m pytest -q tests/transcription_worker`.
No automatic test invokes a real STT provider. There is no configured general-purpose
lint command in this repository. The implementation was additionally checked with
Ruff's syntax/undefined-name/unused-import rules on the new Python files; Python
syntax, TS compilation and tests remain separate checks.

Microphone lifecycle regression: LiveKit RTC emits `track_muted` and
`track_unmuted` as `(participant, publication)`, while publish/unpublish callbacks
use `(publication, participant)`. The worker adapts these argument orders before
stopping or resuming a microphone pipeline. Without this adapter, a microphone
subscribed while muted never starts transcription after unmuting. Tests exercise
the SDK event emitter for either speaker, both initially muted and muted during
an active session, and verify both speakers' final captions arrive before stopping.

Manual two-device acceptance (explicit real-provider opt-in):

1. Configure keys and start the worker, then join one interview from two distinct
   devices/networks. Ensure only the two humans have video tiles.
2. Before consent, Start must be disabled. Consent on one device: still disabled.
   Consent on both and join the active room: owner can start.
3. Say distinct synthetic English question/answer sentences, then speak concurrently.
   Verify role labels from each microphone, interim revision, stable final text,
   visible status on both devices and final rows in the interviewer history.
4. Refresh/reconnect the interviewer: previous final text returns without duplicates.
   Refresh/reconnect the candidate: no complete history API is available. Unmute,
   switch microphone, temporarily disconnect, and verify the new track gets a new
   timestamp anchor without restarting the whole session.
   Also start transcription with either microphone muted, unmute it, and verify
   both speakers appear. Mute/unmute each person again while the other continues
   speaking; the other microphone pipeline must remain active.
5. Stop transcription: video must continue. Revoke consent: STT must stop. End the
   interview: the worker drains/closes and no further finals are accepted.
6. In a synthetic session only, test bad key, worker disconnect, provider rate/error,
   DB unavailability and retries. Confirm safe failures without losing video.

No local LiveKit service is added back to this Cloud-only project. A fully automated
two-browser/fake-microphone Cloud test is not included; the manual procedure covers
this paid/external boundary. Do not confuse unit mocks or API connectivity with a
successful real audio test.

## Benchmark procedure (results must be measured)

Use synthetic or explicitly consented English speech with a known reference and
speaker/timing annotations. Include technical names, pauses, accents representative
of intended users, interruptions, microphone changes and simultaneous speech.
Run identical samples/settings for each English locale under comparison. Record
CPU/OS, worker/browser/SDK versions, provider model/locale, network/region, endpointing,
and audio sample rate/device. Exclude warm-up separately rather than hiding it.

Collect per-utterance first interim receipt minus the relevant audio-frame receipt,
final receipt minus annotated speech end, and reference versus actual start offsets.
Keep diagnostic reference/hypothesis files private; never add real candidate speech
or text to Git. Feed observations to the offline utility:

```powershell
python -m transcription_worker.benchmark path/to/private-observations.json
```

Input shape:

```json
{
  "environment": {"model": "nova-3", "language": "en-US", "notes": "fill with measured environment"},
  "technical_terms": ["React", "PostgreSQL"],
  "observations": [{
    "reference": "known reference sentence", "hypothesis": "actual recognized text",
    "expected_speaker": "CANDIDATE", "actual_speaker": "CANDIDATE",
    "reference_start_ms": 0, "actual_start_ms": 0,
    "interim_latency_ms": null, "finalization_latency_ms": null, "overlap": false
  }]
}
```

The utility calculates median/P95 latency, normalized WER, exact technical-term
occurrence miss rate, role accuracy, timestamp absolute error and overlapping sample
count. This shape is illustrative, **not measured data**. Real benchmark results,
locale comparisons and Deepgram end-to-end verification remain unmeasured until
that explicit test is performed. No accuracy or latency numbers are claimed here.

## Suggested Git boundaries

1. `feat: add consented interview transcript persistence and lifecycle APIs`
2. `feat: add Deepgram Nova-3 LiveKit transcription worker`
3. `feat: show role-attributed live captions and transcript controls`
4. `test: cover transcription boundaries and document deployment and benchmarks`

Keep the feature disabled while reviewing individual commits. The worker/UI need
the schema and API increment before enabling the integration. You perform add,
commit and push; no Git changes are committed automatically.

## Affected files and folder structure

New files are marked `+`; other listed files are modified. Unrelated candidate
identity/import behavior is not changed by this feature.

```text
hiresense/
  .env.example
  README.md
  docker-compose.yml
  backend/
    .dockerignore
    + Dockerfile.transcription
    + requirements-transcription.txt
    + caption_protocol.py
    alembic/versions/
      + 0020_interview_transcription.py
    app/
      config.py
      main.py
      + purge_transcripts.py
      integrations/livekit_media.py
      models/
        __init__.py
        + transcription.py
      routes/
        + transcription.py
      schemas/
        + transcription.py
      services/
        candidate_application_service.py
        interview_rooms.py
        + transcription_service.py
    + transcription_worker/
        __init__.py
        config.py
        main.py
        provider.py
        runner.py
        transport.py
        benchmark.py
        check_caption_transport.py
    tests/
      test_mcp_config.py
      + test_transcription.py
      + transcription_worker/test_worker.py
  frontend/
    nginx.conf
    src/
      components/interviews/
        InterviewMediaRoom.tsx
        + TranscriptionPanel.tsx
        + transcriptionApi.ts
      pages/
        CandidateInterviewPage.tsx
        InterviewerConsolePage.tsx
    tests/rooms/
      setup.tsx
      + transcription.test.tsx
  docs/
    + live-transcription.md
```

`test_mcp_config.py` has only shorter parameter IDs: the pre-existing oversized
JSON test generated an invalid/overlong Windows temporary path. Its test inputs and
assertions are unchanged. `.dockerignore` excludes nested worker virtual environments.

## Verification record — 16 October 2026

Executed locally without paid API calls:

- Backend full suite: **268 passed, 9 skipped**. One existing LangGraph pending
  deprecation warning remains. Skipped tests include external/integration checks.
- Worker suite with the pinned SDKs installed: **11 passed**, including independent
  microphone streams, duplicate track events, mute/unmute restart and final flush.
- Frontend room/UI suite: **39 passed**; scoring: **7 passed**; scheduling: **2 passed**.
- `npm run build`: passed (TypeScript and Vite). The existing large-bundle warning remains.
- New Python files: Ruff critical-error/unused-import checks and syntax compilation passed.
- Worker `pip check`: passed.
- SQLite revision upgrade/downgrade and PostgreSQL SQL generation passed; Alembic
  reports a single head, `0020_interview_transcription`.
- `docker compose --profile transcription config --quiet`: passed.

Not executed: Docker image builds/container startup, migration on PostgreSQL,
real two-browser media/STT integration, visual browser verification, and latency/WER
benchmark. Docker Desktop's Linux engine was unavailable during this verification;
no service was restarted and no live email, room or transcription was created.
Deepgram credentials and an explicit real-provider test are still needed for actual
accuracy/latency measurements. The root private `.env` was not edited.

## Live-caption delivery fix

The initial sender-identity check rejected legitimate messages from the hidden
worker because their LiveKit wire sender is an empty string. Text was already
recognized/persisted, but appeared only when Stop caused history restoration.
This was reproduced in an isolated Cloud room using synthetic text, not interview
audio or Deepgram. Both compressed/uncompressed messages arrived without an identity.

The fix keeps the worker hidden and binds signed caption envelopes to its session.
`caption_protocol.py` uses the maintained `cryptography` library's P-256/SHA-256
implementation and IEEE-P1363 signatures compatible with browser WebCrypto. No
signing secret is returned to clients or added to a LiveKit token. Public-key binding
uses the existing JSONB configuration snapshot, so no extra migration is required.
Small caption messages explicitly disable compression. Interim revisions appear
during speech; final notifications remain separate from persistence. Sequence/timing
guards prevent late interim verification from resurrecting finalized text.

Numeric `caption_messages_sent` and `caption_publish_failures` metrics replace silent
publisher failures. Neither includes caption text, signatures or credentials.
Browser verification requires HTTPS (Cloudflare) or localhost. After applying the
fix, refresh both participants' pages and start a new transcription session; an
already-running older worker cannot acquire a new key midway through its session.

An optional text-only Cloud probe is available with
`python -m transcription_worker.check_caption_transport --run-cloud-probe` in the
worker environment. It creates and deletes only its own fresh `hs-caption-check-*`
room, verifies hidden-sender signatures, and never calls Deepgram or reads candidate
data. It is never run automatically in CI.

Fix verification and activation (16 October 2026):

- Backend: 269 passed, 9 skipped locally and in the built Linux image.
- Worker: 13 passed locally and in the final built Linux image.
- Frontend: 41 room/UI tests, 7 scoring tests and 2 scheduling tests passed.
- Regression coverage includes unsigned/forged hidden-sender rejection, session-key
  binding, captions before Stop, late-interim suppression, and a real Python-signed
  envelope verified by the frontend's WebCrypto implementation.
- TypeScript/Vite build, Python lint checks and all three Docker image builds passed.
- After the user ended the active interview, backend/frontend/worker were updated.
  Backend and worker are healthy; public website health returns 200 and the existing
  Cloudflare address is preserved. PostgreSQL remains at revision 0020 (no extra migration).
- A fresh, disposable LiveKit Cloud text room confirmed signed messages arrive from
  a hidden sender and their signatures verify, with and without compression. The
  room was deleted by the probe. No Deepgram request or interview audio was used.
- A new live two-person speech test is still a manual check; no accuracy/latency
  benchmark or end-to-end browser speech result is claimed by these checks.
