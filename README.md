# HireSense

## Current milestone

- Candidate-only registration
- Email/password sign-in
- JWT authentication
- One seeded Interviewer account
- Role-based dashboards and navigation
- Persistent PostgreSQL storage
- Alembic-managed database migrations
- Private named-volume foundation for candidate documents
- Semantic company-knowledge ingestion using Ollama embeddings
- Gemini-powered, RAG-backed requirement discovery and JD generation
- Interviewer UI for previous-JD knowledge, requirement review and JD approval
- Reviewed Discord job-post previews with persistent publication status

## Requirements

Docker Desktop running with Linux containers.

## Startup

1. Copy `.env.example` to `.env`.
2. Set your own database password, JWT secret, interviewer password and
   `GEMINI_API_KEY` in the root `.env` file.
3. Run:

```powershell
docker compose up --build
```

Application: http://localhost:5173
API documentation: http://localhost:8000/docs
Health check: http://localhost:8000/api/health

The backend runs migrations and seeds the Interviewer automatically.
All public registrations create Candidates.

Requirement extraction and job-description generation use the Gemini API.
Create a key in Google AI Studio and place it only in the root `.env` file:

```dotenv
GEMINI_API_KEY=your-real-api-key
GEMINI_CHAT_MODEL=gemini-3.5-flash-lite
```

Do not put the key in `frontend/.env`, source code, or any variable beginning
with `VITE_`; those values can be exposed to the browser. After changing the
key, recreate the backend container:

```powershell
docker compose up -d --build --force-recreate backend
```

Semantic knowledge embeddings remain local through Ollama. Start Ollama and
pull the embedding model before ingesting or retrieving previous job descriptions:

```powershell
ollama serve
ollama pull nomic-embed-text
```

When the backend runs in Docker, `OLLAMA_DOCKER_BASE_URL` must point to the
host service. The default is `http://host.docker.internal:11434`; local
non-Docker backend runs continue to use `OLLAMA_BASE_URL`.

The Gemini unpaid tier should be used only with synthetic or non-sensitive
demo content. Do not submit real CVs, candidate personal information, or
confidential company material through the unpaid tier.

## Job-description workflow

1. Sign in as the Interviewer and open **Jobs**.
2. Expand **Add previous job description** and add one or more approved
   historical job descriptions.
3. Start a new chat and describe the role, for example: `I want to hire a
   backend engineer.`
4. HireSense retrieves related previous job descriptions and proposes a complete
   requirement profile. Choose **Use previous JD defaults** or describe changes.
5. Generate the job description, edit it if needed, and approve the draft.
6. Use **Created job descriptions** to reopen saved records after a reload.
   Drafts can be edited directly; editing an approved JD creates a new draft
   version so the approved version remains unchanged.

## Discord job posting

Create an incoming webhook for the standard Discord text channel that should
receive job posts. Put the URL only in the root `.env` file:

```dotenv
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/your-id/your-token
DISCORD_DEFAULT_HEADING=BJIT is Hiring!
JOB_POST_DEFAULT_APPLICATION_URL=
JOB_POST_DEFAULT_CONTACT_EMAIL=
JOB_POST_DEFAULT_LOCATION=
JOB_POST_DEFAULT_APPLICATION_DEADLINE=
JOB_POST_DEFAULT_INSTRUCTIONS=
```

The webhook is a backend secret. Do not place it in `frontend/.env`, a
`VITE_*` variable, source code, screenshots, or logs. Recreate the backend
after changing it:

```powershell
docker compose up -d --build --force-recreate backend
```

To publish:

1. Open an approved job description under **Jobs**.
2. Choose **Prepare job post**.
3. Edit the heading, manual application link, contact email, location,
   deadline, and instructions. Empty optional fields are omitted.
4. Review the Discord preview and choose **Save reviewed preview**.
5. Choose **Publish to Discord** and confirm the publication.
6. Review the saved `published`, `failed`, or `uncertain` status after the
   request or after refreshing the page.

HireSense publishes one message using Discord content plus one embed, sends
`allowed_mentions.parse` as an empty list, and requests confirmation with
`wait=true`. It rejects oversized posts rather than truncating the approved job
description. Discord currently limits message content to 2,000 characters,
embed titles to 256, embed descriptions to 4,096, individual field values to
1,024, and combined embed text to 6,000 characters. See Discord's official
[webhook](https://docs.discord.com/developers/resources/webhook) and
[message](https://docs.discord.com/developers/resources/message) documentation.

Known limitations: this increment targets one standard text-channel webhook.
It does not create Google Forms, collect responses or CVs, parse documents, or
rank candidates. A network timeout after sending is recorded as `uncertain`;
check Discord before explicitly preparing another publication. A Discord link
is shown only when Discord returns server, channel, and message identifiers.

For a repeatable local demo, load the six clearly labelled fictional Northstar
Digital documents included with the project:

```powershell
docker compose exec backend python -m app.seed_knowledge
```

The command is idempotent: rerunning it reports the documents as already
present instead of creating duplicates. The dataset contains six historical
engineering job descriptions. It is development/demo data only and must not be
represented as real company information.

The chatbot does not treat the LLM's own completeness claim as authoritative.
The backend checks required skills, qualifications, experience and selection
criteria before confirmation is enabled. Confirmed profiles retain source
references, model metadata and interviewer overrides for traceability.

On startup, the backend runs `alembic upgrade head` before starting FastAPI.
The first migration creates the existing authentication schema on a clean
database and adopts the existing `users` table when upgrading a database that
was created by the original development milestone.

## Tests

```powershell
docker compose exec backend python -m pytest -q
```

The migration and storage tests also run against isolated SQLite databases.

Tests use isolated SQLite databases and do not modify PostgreSQL.

## Stop

```powershell
docker compose down
```

Database data persists in the named Docker volume.

Do not use `docker compose down -v` unless you intend to delete the database.

## Notes

- Changing INTERVIEWER_PASSWORD after the first startup does not change
  the existing account's password.
- Database changes must be introduced through Alembic migrations.
- Offline tests use deterministic embeddings; the running application uses
  `nomic-embed-text` through Ollama for semantic retrieval.
- Candidate documents will be stored under the private `private_storage`
  Docker volume. Do not place CVs, credentials or exported candidate data in
  the repository.
- JWTs use sessionStorage for this local milestone.
- Logout removes the browser session but does not revoke a previously
  issued token. Tokens expire after their configured lifetime.
- Before public deployment, add HTTPS, rate limiting, password reset
  and a reviewed session/token-revocation design.
- Copilot and recruitment features are deferred.
