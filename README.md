# HireSense

Evidence-grounded semantic CV matching, private pgvector passages, stable result
reuse, and calibration checks are described in [robust CV screening](docs/robust-cv-screening.md).

Final candidate rankings (interview 60% + CV 30% + practical task 10%), question scores, optional evidence,
and private HTML/PDF reports are documented in [Feature 6](docs/consolidated-assessments.md).

Interview answer analysis, evidence citations, requirement coverage, follow-up suggestions,
and interviewer correction/version history are documented in [Feature 5](docs/interview-analysis.md).

## Current milestone

Optional [candidate photo verification and profile overview](docs/candidate-identification.md)
uses local models with explicit consent inside the app before the interview.
It is separate from assessment scores and supports manual verification.
An opt-in [local recruitment example loader](docs/recruitment-examples.md) fills
the existing screens with complete, privately traceable recruitment scenarios.

### Innovation Feature — Live Work-Sample Studio

The interview console includes a practical-exercise workspace for technical and
nontechnical roles: assistant-suggested or manual task preparation, reusable private
templates, candidate readiness, a maximum 15-minute working period, live read-only
work, autosave and one immutable submission. The LLM verifies the saved work and
proposes a correctness score (0–100); the interviewer only approves that score.
Unverified or unapproved scores remain pending. Final ranking uses
60% interview, 30% CV and 10% practical; pending decisions remain unranked.
No candidate code is executed and no AI-use
or cheating detection is performed. See [setup and safeguards](docs/live-work-samples.md).

Candidate selection, interview scheduling, confirmed SMTP invitations, `.ics`
calendar attachments and rescheduling are implemented. Both the central assistant
(via authenticated MCP) and manual UI use the same services. See
[setup, workflow, tools, delivery safeguards and commit increments](docs/interview-scheduling.md).
Candidate waiting rooms and assigned interviewer consoles use LiveKit for
one-to-one camera/microphone interviews. LiveKit Cloud handles remote calls;
no local LiveKit media server is required. See
[Cloud setup and remote demo steps](docs/livekit-cloud.md). Secure HireSense join links
are included in confirmed invitations. See [interview room setup, tests, security,
file manifest and Git checkpoints](docs/interview-rooms.md).

The interviewer console also includes [private candidate information and a RAG question assistant](docs/interview-copilot.md), backed by a separately indexed synthetic interview question bank.
The interviewer navigation bar shows [new application notifications](docs/application-notifications.md), including per-job counts of Google Form responses waiting to be synced.
Configure SMTP and LiveKit in the root `.env`; local Mailpit testing is opt-in.
No external calendar API or recording is connected. Consented Deepgram transcription
and LiveKit captions are documented in [live transcription](docs/live-transcription.md).

- Candidate-only registration
- Email/password sign-in
- JWT authentication
- One seeded Interviewer account
- Role-based dashboards and navigation
- Persistent PostgreSQL storage
- Alembic-managed database migrations
- Private named-volume foundation for candidate documents
- Semantic company-knowledge ingestion using Ollama embeddings
- pgvector storage and database-side cosine similarity search with an HNSW index
- Gemini-powered, RAG-backed requirement discovery and JD generation
- Persisted LangGraph supervisor with native Gemini tool calling and shared workflow state
- Interviewer UI for previous-JD knowledge, requirement review and JD approval
- Reviewed Discord job-post previews with persistent publication status
- Job-scoped PDF/DOCX CV parsing, requirement screening and semantic ranking

## Requirements

Deterministic technical/experience/qualification scoring is available on CV Screening.
Select a job, set three category weights, and choose **Rank candidates**.
Pending CVs are processed automatically; evidence is available only when requested.
See [scoring formulas, immutable snapshots and reviewer steps](docs/deterministic-candidate-scoring.md).

Docker Desktop running with Linux containers.

## Startup

1. Copy `.env.example` to `.env`.
2. Set your own database password, JWT secret, interviewer password and
   `GEMINI_API_KEY` and a separate `INTERVIEW_LINK_SECRET` in the root `.env`.
   For interviews, fill `LIVEKIT_CLOUD_URL`,
   `LIVEKIT_CLOUD_API_KEY` and `LIVEKIT_CLOUD_API_SECRET` from your Cloud project.
   See [the Cloud setup guide](docs/livekit-cloud.md). These settings also work
   when the website is opened locally at `http://localhost:5173`.
3. Run:

```powershell
docker compose up --build
```

Application: http://localhost:5173
API documentation: http://localhost:8000/docs
Health check: http://localhost:8000/api/health

The backend runs migrations and seeds the Interviewer automatically.
All public registrations create Candidates.

The repository-root `.env` is the only active environment file. `.env.example`
is a tracked template, not a second configuration file. Do not create
`backend/.env` or `frontend/.env`. Local backend and Discord MCP processes load
the root file regardless of their working directory; process environment
variables take precedence. Docker Compose reads the same root file and passes
only each service's settings into its container, without copying secrets into
images or exposing them to the frontend. `DATABASE_URL` is the local connection;
Compose supplies the backend's internal PostgreSQL URL separately.

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

## Knowledge embeddings with pgvector

PostgreSQL stores previous-JD chunk embeddings in
`knowledge_chunks.embedding` as `vector(768)`. Ollama continues to generate
the embeddings using `nomic-embed-text:latest`; pgvector handles storage and
similarity search. Queries use cosine distance (`<=>`), model metadata filtering,
and a database `ORDER BY ... LIMIT` rather than loading every vector into Python.
The HNSW index uses `vector_cosine_ops`; small datasets may use a sequential scan
because PostgreSQL chooses the lowest-cost plan. HNSW is an approximate index.
See the [pgvector documentation](https://github.com/pgvector/pgvector#hnsw).

The PostgreSQL image is built from `postgres/Dockerfile`, retaining PostgreSQL 16
and Alpine while installing pgvector 0.8.2. For an existing checkout, run:

```powershell
docker compose up -d --build
```

Migration `0014_pgvector_knowledge` enables the extension, converts the existing
JSON embeddings in place, and creates the index. The existing `postgres_data`
volume is reused. Migration stops without deleting records if an existing vector
does not have 768 dimensions. No new API key or separate vector database is needed.
When running PostgreSQL outside Docker, install pgvector on that server before
running Alembic, and use a migration account able to create the extension.

The database requires 768-dimensional embeddings. Switching to a different model
requires compatible dimensions and re-embedding existing knowledge; vectors from
different models are excluded from each other's searches. SQLite remains a JSON
fallback for offline tests only. CV screening and ranking continue to use the
existing requirement assessment workflow; this migration affects previous-JD RAG.

The Gemini unpaid tier should be used only with synthetic or non-sensitive
demo content. Do not submit real CVs, candidate personal information, or
confidential company material through the unpaid tier.

## Job-description workflow

1. Sign in as the Interviewer and open **Jobs**.
2. Open **Reference documents**, select an approved historical job
   description PDF, and upload it. The PDF must contain selectable text; scanned
   image-only documents need OCR before upload. The default limits are 15 MB and
   100 pages and can be changed with `KNOWLEDGE_PDF_MAX_FILE_SIZE_MB` and
   `KNOWLEDGE_PDF_MAX_PAGES`.
3. Use the central supervisor chat and describe the role, for example: `I want to hire a
   backend engineer.`
4. HireSense checks the knowledge base and drafts the job description directly from
   relevant sources. If no suitable reference is found, it asks for the skills and
   duties needed, then drafts from your reply. There is no separate requirements
   proposal, approval or generation step. Screening data is derived internally.
5. Review the draft. Request edits in
   natural language, such as `Remove Kubernetes from preferred skills`, then
   explicitly tell it to **approve the job description**.
6. Use the saved job cards to reopen records after a reload. **Create job description manually**
   remains available alongside the assistant without requiring AI or embeddings.
   Drafts can be edited directly; editing an approved JD creates a new draft
   version so the approved version remains unchanged.

The supervisor uses Gemini's native tool calling via `ChatGoogleGenerativeAI`.
`bind_tools()` exposes JD drafting, JD editing, JD approval, Discord posting,
response syncing, candidate screening and help, with interview/assessment tools
when configured. There is no requirements-discovery tool in this supervisor.
LangGraph's built-in `ToolNode` executes the selected tool and returns
a `ToolMessage` to the supervisor before it produces its final answer.

The graph is `START -> supervisor_agent -> tools -> capture_tool_result ->
supervisor_agent -> END`, with conditional branches for tool execution,
completion, and errors. Exactly one business tool can execute per chat request.
The final response model disables further tool calls; a response-generation
failure falls back to the completed tool's result without losing refresh or
background-screening signals. Business services receive the actual interviewer
message, and approval checks reject fabricated or absent approval instructions.
See the [official Gemini integration documentation](https://docs.langchain.com/oss/python/integrations/chat/google_generative_ai#tool-calling).

The existing `GEMINI_API_KEY` and `GEMINI_CHAT_MODEL` settings are reused. Its
persistent session stores the drafting role, internal screening profile, active
JD, active posting, current phase, and conversation history. The browser keeps
the supervisor session ID in session storage so refreshing the page restores
the same workflow.

The supervisor also stores the last native tool-call name and arguments in its
existing session state. Tools reuse the current services, including pgvector
knowledge retrieval, job-specific Google Forms intake, background CV screening,
and Discord publishing through the MCP server.

Editable diagrams for all four actual graphs are available in
[`docs/langgraphs/hiresense-all-langgraphs.drawio`](docs/langgraphs/hiresense-all-langgraphs.drawio).

## Discord job posting

HireSense publishes through a dedicated MCP server and the Discord Bot API.
The application backend is an MCP client; it no longer sends Discord requests
directly. The MCP server exposes only a configuration check and a
`publish_job_post` tool locked to one configured channel.

Create an application and bot in the Discord Developer Portal, install the bot
in the target server, and grant it **View Channel**, **Send Messages**, and
**Embed Links** permissions for the target channel. Enable Discord developer
mode and copy the channel ID. Put the bot token and channel ID only in the root
`.env` file:

```dotenv
DISCORD_BOT_TOKEN=your-private-bot-token
DISCORD_CHANNEL_ID=your-numeric-channel-id
DISCORD_DEFAULT_HEADING=BJIT is Hiring!
JOB_POST_DEFAULT_APPLICATION_URL=
JOB_POST_DEFAULT_CONTACT_EMAIL=
JOB_POST_DEFAULT_LOCATION=
JOB_POST_DEFAULT_APPLICATION_DEADLINE=
JOB_POST_DEFAULT_INSTRUCTIONS=
```

The bot token is supplied only to the `job-posting-mcp` container. The main
backend reads both MCP endpoints and timeouts from the root `mcp.json` registry,
mounted read-only in Docker. See [MCP configuration](docs/mcp-configuration.md).
Do not place the token in `frontend/.env`, a
`VITE_*` variable, source code, screenshots, or logs. Recreate the MCP server
and backend after changing the configuration:

```powershell
docker compose up -d --build --force-recreate job-posting-mcp backend
```

To publish:

1. Open an approved job description under **Jobs**.
2. In the central **HireSense assistant** chat, enter a command such as
   **Post this job**. The same chat is used for requirement discovery and job
   posting; no separate posting chatbot is shown.
3. Provide the application link and application deadline when the assistant
   asks. The heading, contact email, location, and instructions come from the
   configured reusable defaults.
4. Review the automatically refreshed Discord preview. Tell the assistant about
   any application-link or deadline change if needed.
5. Type **approve** to publish the reviewed preview automatically. Typed
   approval is the explicit publication confirmation. Successful and failed
   tasks are reported in the central chat, and publication status is refreshed.
6. Review the saved `published`, `failed`, or `uncertain` status after the
   request or after refreshing the page.

The existing **Prepare job post** editor remains available for manual preview
creation. It can edit all configured footer values and uses the same protected
preview and publication services as the assistant.

After explicit interviewer approval, the backend calls the MCP
`publish_job_post` tool over Streamable HTTP. The MCP server publishes one
message using Discord content plus one embed and forces
`allowed_mentions.parse` to an empty list. It rejects oversized posts rather
than truncating the approved job description. Discord currently limits message content to 2,000 characters,
embed titles to 256, embed descriptions to 4,096, individual field values to
1,024, and combined embed text to 6,000 characters. See Discord's official
[authentication](https://docs.discord.com/developers/reference#authentication)
and [message](https://docs.discord.com/developers/resources/message) documentation.

Known limitations: the MCP server targets one configured Discord channel and
exposes job publication only. A network timeout after sending is recorded as `uncertain`;
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

Uploaded source PDFs are private runtime data under
`backend/storage/knowledge/` and are ignored by Git. HireSense extracts their
text, stores searchable chunks in PostgreSQL, and records source metadata such
as the original filename and page count. Removing an uploaded knowledge
document deletes its database record, indexed chunks, and stored source PDF.

The chatbot does not treat the LLM's own completeness claim as authoritative.
The backend checks required skills, qualifications, experience and selection
criteria before confirmation is enabled. Confirmed profiles retain source
references, model metadata and interviewer overrides for traceability.

On startup, the backend runs `alembic upgrade head` before starting FastAPI.
The first migration creates the existing authentication schema on a clean
database and adopts the existing `users` table when upgrading a database that
was created by the original development milestone.

## Google Forms candidate and CV intake

HireSense can import candidate responses from the Google Sheet linked to the
application form and download uploaded PDF/DOCX CVs from Google Drive. Candidate
records and application metadata are stored in PostgreSQL. CV files are stored
under `backend/storage/cvs/`; both that directory and `backend/secrets/` are
excluded from Git.

Complete these one-time setup steps:

1. Open `backend/secrets/google-service-account.json` and copy its
   `client_email` value. Share the response spreadsheet and the Google Forms
   upload folder with that address as a viewer. Enabling the APIs alone does not
   grant the service account access to those files.
2. Copy the spreadsheet ID from the response Sheet URL. It is the value between
   `/d/` and `/edit`.
3. Add the ID to the project `.env` file:

   ```dotenv
   GOOGLE_FORMS_SPREADSHEET_ID=your-spreadsheet-id
   ```

4. Add a required Google Form question named `Job Posting` (or configure its
   exact name with `GOOGLE_FORMS_JOB_COLUMN`). Each answer must contain either
   a HireSense posting ID, such as `Post #12`, or an exact job title. Posting
   IDs are recommended because job titles can be repeated.
5. If the response tab is not named `Form Responses 1`, set
   `GOOGLE_FORMS_SHEET_NAME`. Header names are detected from common Google Form
   labels. The exact labels can also be configured with the
   `GOOGLE_FORMS_*_COLUMN` variables shown in `.env.example`.
6. Restart the backend, open **Candidates**, and choose **Sync responses**.

The Candidates page opens directly on a searchable table, with filters for each
job posting and ten applications per page by default. Always-visible pagination
includes Previous/Next, numbered page buttons on larger screens, and a choice of
5, 10, 20 or 50 candidates per page. Search and job filters return to page one;
row numbers continue across pages. Choose **Inspect** to see contact
details, application information, and CV files in a keyboard-accessible modal.
**Open CV** opens a PDF in a new tab; Word CVs download to open on your device.
Rows are numbered, and each row offers **Inspect** and **Delete**. Choose
**Select candidates** to show checkboxes and delete up to 100 selected applications
with one confirmation. Selection continues across pages and clears when filters
change. The table omits CV counts and collection setup notes; CVs remain available
in the details modal, which only shows relevant contact fields. Sync remains available.
Bulk deletion checks ownership of every selected application before changing any
records, commits the changes together, and only then removes their private CV files.

CV files are served through
`GET /api/candidates/applications/{application_id}/cvs/{document_id}` with the
interviewer's authorization header. The server checks posting ownership, both
record IDs, private storage boundaries, file format and checksum. Responses are
not cached; no public storage URL or token-bearing link is created. The frontend
uses temporary blob URLs and retains the usual expired-login handling.

The sync is idempotent: importing the same Sheet row into the same job posting
again does not create a duplicate application. Every row is routed independently
using its job value. Missing, unknown, inaccessible, or ambiguous job values are
reported and are never assigned to another posting.

The service account has read-only Sheets and Drive scopes. The API never serves
the private CV directory as static content. Each accepted file is size-checked,
restricted to PDF/DOCX, given a safe local filename, and recorded with a SHA-256
digest for later parsing and ranking.

Deleting a collected application removes its application and CV records from
PostgreSQL, deletes its locally stored CV files, and removes the candidate when
they have no other applications or documents. HireSense retains only a hashed
import exclusion so the unchanged Google Sheet row is not imported again.

Other web-app delete actions are also persistent: deleting a knowledge document
removes its indexed chunks, while deleting a job description removes its local
postings, applications and CV records. A Discord message already published to
an external server remains on Discord.

## CV screening and semantic ranking

The shared assistant stays available across **Jobs**, **Candidates**, and
**Assessments**, keeping the same conversation as you navigate. You can ask:

- “Sync responses” to import the configured Google Sheet and download CVs. Each
  response is routed using the existing Job Posting answer; sync is not restricted
  to the job selected on Assessments.
- “Screen candidates for Frontend Engineer” or “Screen Post #12” to start a
  background batch for that posting's pending applications.
- “Screen candidates for the selected job” to use the Assessments job selector.

The assistant asks for a posting when the target is missing or ambiguous, rejects
applications from another job, and prevents a second conversational batch while
one is already running for that job. It reports import warnings and task failures,
shows screening progress, and refreshes applications and ranking after completion.
An active conversational batch can be restored after reloading the page.

1. Import applications and CVs with **Candidates → Sync responses** or the shared
   assistant. Syncing routes responses across all jobs using their Job Posting answers.
   CV Screening focuses on weights and ranking, without sync or application-list controls.
2. Open **CV Screening** and select the job in the ranking section. HireSense
   uses only applications routed to that posting and requires its confirmed
   requirement profile and approved job description.
3. Set the **Technical skills**, **Experience**, and **Qualifications** percentages
   (total 100%) in the compact weights row. Choose **Rank candidates** to explicitly approve
   them. Pending CVs are prepared in the background and scored after screening;
   existing screening results are reused when current.
4. Read the single ranking table. Choose **Inspect evidence** only if you want
   category scores, short explanations, focused CV quotations and PDF page/DOCX
   block locations in a keyboard-accessible modal. Met is green, Partially met
   is amber, and Unmet is red. Full-source expanders and the previous-ranking
   selector are not shown; historical snapshots remain saved, and the page
   loads the latest ranking. Closing the modal returns focus to its Inspect button.
   Rankings show 10 candidates per page by default, with 5/10/20/50 row options,
   numbered pages and Previous/Next controls. Rank values stay unchanged across
   pages. A new ranking returns to page one. Interview selection and scheduling
   are available separately under **Schedule Interviews**, immediately after
   **CV Screening** in the navbar.
5. Open **Schedule Interviews**, choose a job, and select candidates from its
   latest CV ranking. Selections persist across pages. Use the scheduling form
   to choose checked candidates, the highest-ranked candidates, or candidates
   above a score. Preview recipients, times and email before confirming delivery.
   The shared assistant receives the selected job and candidates on this page.
   **Interview** remains the page for meeting details, delivery and rescheduling.

Application dropdowns share rounded, viewport-aware menus with selected-state
indicators and keyboard navigation (arrows, Home/End, Enter, Escape and type-ahead).
Page-size controls stay compact. Transcript multi-selects support checking and
unchecking passages without Ctrl/Cmd-click. Menus avoid clipped cards and remain
inside the active dialog when opened there. LiveKit device controls retain their
SDK-provided meeting theme.

PDF and DOCX text are parsed only from the private `backend/storage/cvs/`
directory. Image-only PDFs, corrupt or encrypted files, unsafe paths, unsupported
formats and documents outside the configured size/page/text limits are recorded as
processing failures. They receive zero evidence coverage and stay in the ranking,
with the processing issue disclosed when evidence is inspected. The screening prompt treats CV text
as untrusted data, validates cited quotes against parsed source blocks, and runs
a separate model check before positive evidence is accepted.

Ranking uses auditable category-weighted coverage: Met = 1, Partially Met = 0.5,
and Unmet = 0. New scores normalize ambiguous or missing requirement matches to
Unmet, without requiring manual confirmation. No candidates are held for review;
failed processing has zero coverage, not a judgment of candidate capability.
Within-category coverage uses approved
requirement weights, then the three category percentages produce the final score.
Unmapped selection criteria stay evidence-only. Ties share the same rank and are
ordered stably by application ID. Results
persist with the CV hash, requirement snapshot, model, prompt version and
calculation version. Unchanged compatible results are reused; changed CVs or job
requirements are screened again.

The limits can be configured in the root `.env` file:

```dotenv
CV_MAX_PAGES=40
CV_MAX_CHARACTERS=150000
CV_MIN_EXTRACT_CHARACTERS=80
SCREENING_BATCH_MAX_APPLICATIONS=50
```

Gemini receives CV content during screening. Use only data that your privacy and
data-processing policy permits sending to the configured model provider. Real
candidate data should not be sent through an unpaid/demo API tier.

## Tests

```powershell
docker compose exec backend python -m pytest -q
```

The migration and storage tests also run against isolated SQLite databases.

The default suite uses isolated SQLite databases; real pgvector integration tests
are skipped unless `PGVECTOR_TEST_SERVER_URL` is supplied. To run those tests,
point that variable at a disposable PostgreSQL server with pgvector installed.
The test account needs permission to create databases. Each integration test
creates and removes its own randomly named database; it never migrates the
database named in the supplied connection URL.

## Stop

For a temporary HTTPS website demo on another device, see
[Cloudflare demo setup](docs/cloudflare-demo.md). Audio/video connects separately
to LiveKit Cloud when configured; the tunnel exposes the website. Stop the tunnel
with `./scripts/stop-cloudflare-demo.ps1` when finished.

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
- Candidate documents are stored under the host-mounted private
  `backend/storage/cvs/` directory. Do not place CVs, credentials or exported
  candidate data in the repository.
- JWTs use sessionStorage for this local milestone.
- Logout removes the browser session but does not revoke a previously
  issued token. Tokens expire after their configured lifetime.
- Before public deployment, add HTTPS, rate limiting, password reset
  and a reviewed session/token-revocation design.
- Copilot and recruitment features are deferred.
## Live interview transcription

Optional consent-based Deepgram Nova-3 captions are documented in
[docs/live-transcription.md](docs/live-transcription.md), including the worker
profile, private environment settings, tests, retention and benchmark procedure.
The feature is disabled by default and does not record audio or video.
