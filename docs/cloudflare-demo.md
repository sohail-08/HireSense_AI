# Cloudflare website demo (self-hosted LiveKit retained)

This optional setup exposes HireSense's website and `/api` through a temporary
HTTPS Quick Tunnel. The frontend proxies API requests to the private backend.
PostgreSQL, MCP services, CV storage and LiveKit ports are not directly exposed.
Authenticated features still require the existing interviewer login. Candidates
still need a valid private invitation and interviewer admission.

**This is website-only, not a working remote audio/video meeting.** LiveKit stays
self-hosted on localhost. The room pages display a clear warning and do not issue
media credentials or attempt a localhost connection in public demo mode. A
separately reachable self-hosted LiveKit signaling/media endpoint, with appropriate
TLS, RTC firewall rules and usually TURN, is a later networking task. Do not change
LiveKit keys or switch providers for this milestone.

## Start

From the project root in PowerShell, with Docker Desktop running:

```powershell
docker compose up -d --build
./scripts/start-cloudflare-demo.ps1
```

The script prints the public `https://….trycloudflare.com` URL. Open that URL on
another device. Keep the laptop awake, Docker running and the internet connected.
No Cloudflare account, domain, local cloudflared installation or tunnel token is
required. The pinned cloudflared image is downloaded on first use.

Finish/end existing admitted or active interviews and resolve pending email
deliveries before starting or restoring demo mode: the scripts refuse to restart
the backend while these are present. They never end interviews or send invitations
on your behalf. Only the backend is restarted to apply its public origin; the
database, LiveKit and MCP containers are not restarted.

The normal configuration remains in the **single root `.env`**. The helper reads
the public hostname from a localhost-only control endpoint, validates it, passes
`DEMO_PUBLIC_URL` temporarily to the Compose overlay, and restores the calling
process environment. It does not write another `.env` or alter the root `.env`.
The overlay configures `FRONTEND_URL`, `INTERVIEW_JOIN_BASE_URL`, and secure
candidate cookies. The optional `CLOUDFLARE_METRICS_PORT` setting defaults to 20241.

For URL discovery only, without configuring the backend, use:

```powershell
./scripts/start-cloudflare-demo.ps1 -UrlOnly
```

That diagnostic mode is not sufficient for complete candidate-link/cookie use.
Run the normal script afterward. When demo mode is active, avoid starting the
backend with plain base Compose commands: these restore its localhost origin.
If rebuilding during a demo, stop the demo, rebuild locally, then start it again.

## Candidate invitation links

New invitation previews and explicitly confirmed emails use the active public
origin. Existing invitations retain their original origin so previews and emails
remain consistent. They are **not** automatically rewritten or emailed again.

In the interviewer console, a localhost-origin invitation is flagged. Choose
**Update candidate link**, then confirm the replacement, and share the newly
copied link privately. Link replacement invalidates the old link/session and is
not permitted during an admitted/active interview. Use a fresh, unadmitted
interview for a waiting-room demo. Do not share private invitation URLs in Git,
screenshots, chat history or logs.

Candidate invitation validation, device checks, waiting status and admission can
be demonstrated. After admission the candidate sees **Admitted — website-only
demo**, rather than an endless failed media connection. Audio/video is unavailable
in this mode, including for an interviewer using the website on the host laptop.

## Stop and restore localhost

```powershell
./scripts/stop-cloudflare-demo.ps1
```

This stops only the tunnel, then restores backend configuration from the root
`.env`. It retains the database and all storage; it never runs `compose down` or
deletes volumes. If the restart safety check fails, the public tunnel is still
stopped, but backend origin restoration waits until you resolve that condition
and run the stop script again. Replace public-origin candidate links before
reusing them locally.

The Quick Tunnel hostname may change when its process/container is recreated.
Use the latest printed URL and explicitly replace old invitation links. A normal
`docker compose up` does not stop an already running optional tunnel: always use
the stop helper when finished.

## Privacy and troubleshooting

- This is a temporary supervisor demo, not production hosting. Use synthetic
  candidate data. Anyone with the public website URL can reach its login and
  public endpoints; the app does not yet have production-grade rate limiting.
- Cloudflare terminates public HTTPS and forwards requests to your local origin.
  This places Cloudflare in the request path; review that before using real data.
- The tunnel's control port is bound to `127.0.0.1` only. Its `/ready` endpoint
  checks connectivity and `/quicktunnel` returns the hostname. Cloudflared uses
  fatal-only logging to avoid request diagnostics containing invitation URLs.
  Do not enable debug logs or dump full environment/Compose configuration.
- If startup reports that the tunnel is not ready, check DNS and outbound TCP
  port 7844. The helper uses HTTP/2 transport. It waits with bounded retries.
- If startup fails after the container starts, stop it with the stop helper;
  do not leave a public tunnel unattended. Resolve the error and retry.
- Quick Tunnels have no uptime guarantee, a 200 concurrent request limit, and no
  SSE support. They are appropriate for temporary demos, not stable invitations.

## Verification

```powershell
./scripts/test-cloudflare-demo.ps1
docker compose exec -T backend python -m pytest -q
cd frontend
npm run test:rooms
npm run build
```

Helper tests run offline with mocked Docker and check hostname validation,
temporary environment restoration, scoped restarts and restart safeguards.
Backend/UI tests cover demo media warnings, refusal to issue unreachable media
credentials, explicit link replacement and no-media admission. Public smoke checks
should cover the website and `/api/health`, plus denial of unauthenticated room
access. These checks do not prove remote LiveKit media connectivity.

References: [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/),
[Cloudflare tunnel protocols](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/protocols/),
[LiveKit ports and firewall](https://docs.livekit.io/transport/self-hosting/ports-firewall/).
