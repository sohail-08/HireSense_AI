# LiveKit Cloud interviews with local HireSense

HireSense's website, backend, PostgreSQL and private CV storage remain on your
laptop. Cloudflare exposes the HTTPS website. LiveKit Cloud handles WebRTC
signaling and audio/video using the existing official SDKs. Interviewer login,
private invitation exchange, waiting-room admission and confirmed End remain
enforced by HireSense; no new chatbot, calendar integration or media transport
is introduced.

## Get the three project values

1. Sign in to [LiveKit Cloud](https://cloud.livekit.io) and create/select a project
   such as **HireSense**. You do not need to create or deploy an AI agent.
2. Open **Settings → Project** and copy the **Project URL** (`wss://...livekit.cloud`).
3. Open **Settings → Keys**, create a key if needed, and copy its API key and
   API secret. All three values must belong to the same project.
4. Edit only the existing root `.env`. Fill the fields already added there:

```dotenv
LIVEKIT_CLOUD_URL=wss://your-project.livekit.cloud
LIVEKIT_CLOUD_API_KEY=your-project-api-key
LIVEKIT_CLOUD_API_SECRET=your-project-api-secret
```

The values above are placeholders, not usable credentials. Keep the exact `wss://`
URL from the dashboard. Do not paste credentials into chat, commit `.env`, create
another environment file, or use `VITE_*` for keys. The project is Cloud-only:
there is no local media server, local key pair or provider-selection setting.

## Start or refresh the demo

Finish/end any joined, admitted or active interview and resolve pending emails
before restarting services or switching providers. Do not change projects/keys
while rooms are in use: media state is not migrated between providers.

With the application already running:

```powershell
docker compose build backend frontend
./scripts/start-cloudflare-demo.ps1
docker compose exec -T backend python -m app.check_livekit --check-api
```

The start helper preserves the current tunnel hostname when its container is still
running, applies the public website/invitation origin and secure candidate cookies,
and loads the Cloud settings from the root `.env`. Its automatic frontend restart refreshes
the built assets and Nginx backend connection after a backend container replacement.
For a fresh local application, run `docker compose up -d --build` first, then start
the demo helper. That initial command can recover previously confirmed emails;
do not restart with pending deliveries just to configure media.

The check reports only sanitized configuration flags and a read-only authenticated
Cloud API probe. It does not create rooms, return candidate data, print keys or
send mail. `api_reachable=true` means the Cloud credentials worked, not that a
real RTC connection has been tested. `remote_media_verified` stays false in this
diagnostic; verify audio/video yourself with two devices.

Nginx uses Docker DNS dynamically, and the helper waits for website API health
after refreshing both web services. Backend restarts no longer require a separate
manual frontend restart. Neither PostgreSQL nor MCP containers are restarted.

## Test a call

1. Open the public URL printed by the helper and sign in as the interviewer.
2. Open the console for a fresh, non-ended interview. If its invitation uses
   localhost or an earlier tunnel address, choose **Update candidate link** and
   confirm the replacement. Share the copied link privately.
3. On another device, preferably mobile data or another Wi-Fi, open that link.
   Allow camera/microphone when requested and continue to the waiting room.
4. In the interviewer console, check devices and choose **Join interview room**.
   Admit the waiting candidate. Verify both directions of audio/video, mic/camera
   toggles, leave/rejoin, and **End interview for everyone**.
5. Confirm the candidate cannot rejoin after End. An ended interview is not
   reusable: use another fresh schedule rather than changing its database state.

No invitation email is sent automatically by Cloud setup. Existing email preview
and explicit confirmation rules are unchanged. Keep the laptop/Docker awake;
LiveKit Cloud does not host the website/backend. Quick Tunnel URLs are temporary.

## Security and privacy

- The adapter derives the HTTPS server API address from the validated WSS project
  URL; it never sends Cloud keys to a local media server or the browser.
- The backend issues short-lived JWTs for the exact room and opaque candidate or
  interviewer identity. Candidates still require a valid session and admission.
- End/link retirement revokes **both** Cloud participant identities with an explicit
  revocation cutoff before deleting the room, including identities that already
  disconnected. Failures leave the durable ending barrier for safe retry; cached
  or refreshed tokens must not recreate a retired room. Synchronize the host clock.
- Cloud configuration is checked before issuing media credentials. Missing or
  invalid settings disable joining with a clear warning; there is no fallback to
  another provider. Errors never echo secrets, tokens or raw response bodies.
- Transport encryption is provided by LiveKit. Optional end-to-end encryption is
  **not enabled by this change**. Do not claim the media is hidden from LiveKit.
  Recording, transcription and automatic agent dispatch are not enabled by
  HireSense; do not configure auto-egress/agent dispatch separately in the Cloud
  project without reviewing privacy requirements.
- Cloud usage is subject to the selected plan's participant-minute, concurrency
  and transfer limits. Use synthetic demo data and monitor the Cloud dashboard.

## Local website development

You can still develop the website at localhost while audio/video uses Cloud.
After ending active interviews, stop public website exposure and restore the root
localhost website settings:

```powershell
./scripts/stop-cloudflare-demo.ps1
```

This restores localhost website settings and refreshes the frontend proxy while
retaining LiveKit Cloud. No local media server or media ports are required.

## Verification

```powershell
./scripts/test-cloudflare-demo.ps1
docker compose run --rm --no-deps --entrypoint python backend -m pytest -q -p no:cacheprovider
cd frontend
npm run test:rooms
npm run build
```

Offline tests cover Cloud endpoint validation, private credential handling,
room-scoped grants, admission gates, missing settings, strict revocation ordering,
idempotent deletion, safe failure and read-only probes. Real Cloud media tests are
explicit opt-in and consume Cloud usage: see `backend/tests/test_livekit_integration.py`.

References: [Project URL](https://docs.livekit.io/intro/basics/connect/),
[API keys](https://community.livekit.io/t/where-to-find-the-livekit-api-key-and-secret/92),
[token revocation](https://docs.livekit.io/frontends/reference/tokens-grants/),
[Room Service API](https://docs.livekit.io/reference/other/roomservice-api/),
[pricing and usage](https://livekit.com/pricing).
