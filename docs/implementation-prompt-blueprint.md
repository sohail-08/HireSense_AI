# HireSense: Parent and Child Implementation Prompts

Prepared for project review · 27 October 2026

## Purpose

This document presents newly authored prompts for implementing HireSense from an empty repository.
It is a structured development blueprint, not a historical transcript of previous AI conversations
or a copy of the application's runtime system prompts.

The **parent prompt (P-00)** defines the complete product, architecture and shared constraints.
The **20 child prompts (C-01–C-20)** turn that specification into focused, testable implementation
tasks. Each child inherits P-00 and builds on the completed prerequisites listed below.

For the actual instructions used inside the running application, see the separate
[system prompt catalog](system-prompts.md). These two documents serve different purposes:
this blueprint instructs a coding assistant to build features; the catalog records instructions
the application sends to its models.

## How to use the prompts

1. Start a coding-assistant session with P-00 and request the implementation of C-01.
2. Run each later child prompt after its prerequisites have been completed and checked.
   Include P-00 again if the assistant no longer has that context.
3. Provide the current repository and the preceding implementation notes. Do not supply real
   candidate data or secrets as prompt text; configure credentials through private environment settings.
4. Require implementation and verification for each stage before proceeding. Record actual test
   results and any missing external configuration instead of treating generated code as proven correct.
5. Keep domain services independently usable through APIs/manual controls first. C-17 connects the
   completed services to the unified assistants; earlier stages need not invent temporary chat agents.

No live provider calls, real candidate messages or production deployments are implied by using this
document. Provider accounts, credentials and approvals must be supplied separately.

## Prompt hierarchy and implementation order

All child prompts inherit P-00. A dependency refers to an earlier child prompt, not to a separate agent.

| Prompt | Feature / deliverable | Prerequisites |
| --- | --- | --- |
| [C-01](#c-01-project-foundation-and-development-environment) | Project foundation and development environment | P-00 |
| [C-02](#c-02-data-model-migrations-and-private-storage) | Data model, migrations and private storage | C-01 |
| [C-03](#c-03-interviewer-authentication-and-candidate-link-access) | Interviewer authentication and candidate link access | C-02 |
| [C-04](#c-04-knowledge-base-local-embeddings-and-rag) | Knowledge base, local embeddings and RAG | C-02, C-03 |
| [C-05](#c-05-rag-assisted-job-description-preparation) | RAG-assisted job-description preparation | C-04 |
| [C-06](#c-06-discord-publication-through-a-dedicated-mcp-service) | Discord publication through a dedicated MCP service | C-05 |
| [C-07](#c-07-google-forms-intake-and-candidate-management) | Google Forms intake and candidate management | C-06 |
| [C-08](#c-08-cv-extraction-ocr-and-evidence-grounded-screening) | CV extraction, OCR and evidence-grounded screening | C-04, C-07 |
| [C-09](#c-09-deterministic-cv-scoring-and-shortlisting) | Deterministic CV scoring and shortlisting | C-08 |
| [C-10](#c-10-interview-scheduling-invitations-and-rescheduling) | Interview scheduling, invitations and rescheduling | C-09 |
| [C-11](#c-11-live-interview-rooms-and-participant-consoles) | Live interview rooms and participant consoles | C-03, C-10 |
| [C-12](#c-12-consented-live-transcription-and-reliable-text-persistence) | Consented live transcription and reliable text persistence | C-11 |
| [C-13](#c-13-transcript-understanding-granular-scoring-and-performance-summaries) | Transcript understanding, granular scoring and performance summaries | C-04, C-12 |
| [C-14](#c-14-live-work-sample-studio) | Live Work-Sample Studio | C-04, C-11 |
| [C-15](#c-15-optional-application-photo-verification) | Optional application-photo verification | C-07, C-11 |
| [C-16](#c-16-fast-final-ranking-and-traceable-reports) | Fast final ranking and traceable reports | C-09, C-13, C-14 |
| [C-17](#c-17-unified-tool-calling-recruitment-and-interview-assistants) | Unified tool-calling recruitment and interview assistants | C-05, C-06, C-07, C-09, C-10, C-13, C-14, C-16 |
| [C-18](#c-18-dashboard-navigation-and-polished-user-experience) | Dashboard, navigation and polished user experience | C-17 |
| [C-19](#c-19-regression-tests-security-and-failure-recovery) | Regression tests, security and failure recovery | C-18 |
| [C-20](#c-20-reproducible-deployment-and-professional-project-documentation) | Reproducible deployment and professional project documentation | C-19 |

C-19 performs cross-feature hardening in addition to the incremental tests required by every child.
C-20 is the final deployment/documentation review; basic startup and migrations are already required
in C-01 and C-02.

## P-00: Parent prompt — complete project specification

```text
Act as a senior full-stack engineer and solution architect. Build HireSense, an AI-assisted
recruitment platform, from an empty repository. Implement the project incrementally through the
child prompts in this document. Produce working code, migrations, tests and deployment instructions,
not only a conceptual design.

Product objective:
Help an interviewer create a job description, publish a job, import applications, screen CVs,
schedule and conduct interviews, assess practical work and compare evidence-backed final results.
Support engineering, HR, sales and other job-related roles. The system assists the interviewer; it
must not autonomously hire or reject applicants.

Users and access:
Interviewers authenticate and own their recruitment resources. Candidates apply through Google Forms
and attend via expiring private invitation links, without candidate accounts or signup. Candidates
may access only their own participation and practical-task functions. Transcripts, assistant
conversations, assessment results and photo-match outcomes are interviewer-only.

Architecture:
Use React 19, TypeScript, Vite and Tailwind CSS; Python 3.12, FastAPI, Pydantic, SQLAlchemy and
Alembic; PostgreSQL 16 with pgvector; Gemini for structured generation and assessment; and a private
Docker Ollama service using nomic-embed-text with 768-dimensional vectors. Use LangGraph for scoped
orchestration and explicit workflows, not unconstrained autonomous agents. Keep business services in
a modular FastAPI backend with in-process background work and persisted recovery states.

Integrations:
Use read-only Google Sheets/Drive intake, a dedicated Discord posting MCP service, a separate
interview-scheduling MCP service, SMTP invitations with .ics attachments, direct browser WebRTC
through LiveKit Cloud and an optional Deepgram transcription worker. Use local Poppler/Tesseract for
scanned CVs and optional local YuNet/SFace for consented application-photo comparison. Never expose
provider keys to the frontend.

Functional rules:
Job descriptions use relevant reference knowledge and explicit interviewer details, with human
review, editing, versioning and approval. There is no separate requirement-discovery approval graph.
Keep candidate profiles application-scoped so repeated email addresses cannot overwrite another
person's data. Require explicit approval for publication, invitation delivery, practical-task
sharing and practical-score acceptance.

Scoring rules:
Calculate CV coverage deterministically from validated requirement findings; default category
weights are skills 50%, experience 30% and qualifications 20%. Interview answers receive supported
0–100 marks for relevance, accuracy, completeness and quality, each weighted 25%. Exclude greetings
and device checks; retain job-related nontechnical questions. Verified off-topic or genuinely
unanswered questions earn zero, while missing sources, uncertain meaning or provider failures remain
incomplete.

Practical work has one submission and a server-enforced limit of at most 15 minutes. The LLM reviews
correctness with traceable evidence and a separate support check; the interviewer approves the
verified numerical score. Do not execute candidate code or claim AI-use detection. The final formula
is interview 60% + CV 30% + approved practical 10%. Use current saved scores for fast final ranking,
never fresh AI regrading from that action.

Evidence and privacy:
Treat retrieved documents, transcripts and submissions as untrusted data. Preserve original source
quotes and locators. Do not invent missing facts, infer protected traits or treat transcription
noise as a candidate weakness. Require both participants' consent before live transcription, store
final text rather than recorded audio/video, and implement retention. Optional face comparison
requires in-app consent, encrypted reference storage and interviewer-only results; it must not
affect scores or prevent joining.

Delivery standard:
Use a consistent accessible UI, concise candidate-performance summaries and clear action-driven
navigation. Persist versioned inputs/results and handle stale data, duplicate requests and partial
failures explicitly. Use synthetic fixtures and mocked external services for routine tests. Document
manual provider configuration and limitations honestly. Do not include unused placeholders, dead
prompts or unrelated features.
```

## Shared execution contract for every child prompt

Read the following instruction with each child prompt:

```text
Apply P-00 and the completed prerequisite stages. Implement only the requested feature and its
necessary integration points. Deliver backend/API changes, database migrations when needed,
frontend behavior, authorization and failure handling, automated tests and concise setup notes.

Reuse shared business services and UI components rather than duplicating behavior for chat and
manual flows. Inspect existing work before changing it. Do not delete used migrations, historical
data support or public behavior merely because a static checker reports a possible unused name.

Use dependency injection and synthetic fixtures for external services. If credentials, reference
documents or provider access are unavailable, implement a testable adapter and clearly state the
missing configuration; do not invent a successful live result. Ask before contacting real people,
consuming paid external resources or interrupting an active deployment.

At completion, report implemented behavior, changed files, actual verification results, limitations
and the next stage that is ready to start. Do not claim perfect scoring, security or functionality.
```

## C-01: Project foundation and development environment

Parent: **P-00** · Prerequisites: none beyond the parent specification.

```text
Create the initial HireSense repository using the parent specification. Establish a React 19 /
TypeScript / Vite / Tailwind frontend and a Python 3.12 / FastAPI backend. Separate routes, schemas,
business services, integrations and persistence concerns without creating unnecessary microservices.

Provide Dockerfiles, Docker Compose, an Nginx frontend with an /api proxy, health checks, dependency
manifests and a safe .env.example. Include PostgreSQL with pgvector and persistent private storage.
Reserve service boundaries for Ollama, its initializer, the two MCP services and the optional
transcription worker; implement their behavior in the relevant later stages. Do not add Redis or
Celery merely for background tasks.

Create a consistent indigo-themed application shell, interviewer navigation, loading/error states
and a not-found page. Add test configuration and basic health/build checks.

Acceptance: the frontend builds, the API health endpoint works against the database, containers use
service-name networking, secrets are not bundled into the browser, and a clean checkout has
documented startup steps. Explain which later integrations still require credentials or
implementation.
```

## C-02: Data model, migrations and private storage

Parent: **P-00** · Prerequisites: **C-01**.

```text
Design and implement the persistence layer for the complete recruitment lifecycle. Model interviewer
accounts, versioned requirement profiles and job descriptions, publications, application-scoped
candidate profiles, CV documents and passages, knowledge documents/chunks, screening runs, scoring
configurations/rankings, interview schedules/deliveries/access sessions, consented transcripts,
answer analyses, practical exercises/submissions/reviews, photo-verification records and final
report artifacts.

Use SQLAlchemy and Alembic with explicit foreign keys, constraints, timestamps and ownership. Store
workflow states, input hashes, model/prompt/policy versions and source references needed to detect
stale results. Keep shared knowledge retrieval separate from private candidate CV passages.

Provide private storage helpers for CVs, reference PDFs and reports. Support configurable retention
and safe deletion with authorization, path containment and dependent-result invalidation. Do not
expose storage paths as public URLs.

Acceptance: migrations work on a disposable database, illegal state/data combinations are rejected,
deletion cannot escape the private storage root, and records belonging to one interviewer cannot be
used by another. Preserve schema history rather than replacing migrations with automatic table
creation.
```

## C-03: Interviewer authentication and candidate link access

Parent: **P-00** · Prerequisites: **C-02**.

```text
Implement interviewer-only account access and candidate participation without candidate accounts.
Provide secure password hashing, JWT-based interviewer authentication, protected routes and a
configurable initial interviewer account. Do not create public registration or candidate signup
screens.

Create candidate access through expiring, unguessable interview invitation links exchanged for
narrowly scoped HttpOnly cookies. Bind access to the intended interview/application, enforce origin
checks and expiry, and support revocation during rescheduling or interview closure. Never place
privileged tokens in candidate-visible responses or logs.

Separate candidate and interviewer response schemas. Candidates must not access interviewer notes,
transcripts, assessments, final rankings, assistant conversations or photo-match outcomes. Enforce
ownership and role checks in backend services, not just hidden UI controls.

Acceptance: tests cover invalid/expired/revoked links, cross-interview access, unauthorized API
requests and candidate denial of private interviewer resources. An eligible candidate can join
through the link without creating an account. Explain local HTTP versus deployed HTTPS cookie
configuration.
```

## C-04: Knowledge base, local embeddings and RAG

Parent: **P-00** · Prerequisites: **C-02**, **C-03**.

```text
Implement a private reference knowledge base with separate source types for historical job
descriptions and interview questions with approved answer guides. Allow authorized reference-PDF
ingestion, preserve document/page/chunk metadata and expose searchable source references.

Run Ollama inside Docker with nomic-embed-text producing 768-dimensional vectors. Implement an
ollama-init setup job that downloads a missing model, verifies its pinned identity and checks a
valid inference before allowing the backend to start. Persist the model cache and reuse it on
subsequent starts; do not depend on a separately configured host Ollama installation.

Use pgvector retrieval, model-compatible document/query prefixes and explicit model/dimension
metadata. Prevent incompatible model revisions from mixing with saved vectors. Isolate candidate CV
vectors from the shared reference corpus.

Acceptance: tests verify chunk provenance, source-type filters, embedding dimensions, model-cache
reuse, initialization failure handling and authorized retrieval. Missing or irrelevant reference
material produces an explicit state, not invented evidence. Keep scanned-CV OCR in its own later
pipeline rather than silently applying it to every reference document.
```

## C-05: RAG-assisted job-description preparation

Parent: **P-00** · Prerequisites: **C-04**.

```text
Build the Jobs workspace and job-description preparation flow. Let an interviewer describe a role
conversationally, retrieve genuinely relevant previous job descriptions and create a grounded draft
using Gemini structured output. Ask a concise follow-up only when both the sources and interviewer
details are insufficient.

Derive a structured screening requirement profile internally. Do not introduce a separate
requirement-discovery conversation, graph or approval step. Preserve required versus preferred
skills, experience and qualifications; do not invent pay, benefits, company facts or missing job
requirements.

Support manual JD creation, targeted editing, draft review, explicit approval, new versions and
private reference-document management. Editing must preserve unrelated requirements, and approved
versions must remain available when a new draft is created.

Acceptance: role-appropriate references are used, unrelated retrieved roles are rejected, source
references remain traceable, and generation never counts as approval or publication. Test missing
context, manual entry, editing, authorization and version preservation. Reveal the draft review
section when an action creates or updates it.
```

## C-06: Discord publication through a dedicated MCP service

Parent: **P-00** · Prerequisites: **C-05**.

```text
Implement a private job-posting MCP service using Streamable HTTP and a LangGraph workflow for
interpreting posting commands and validating details. Use the approved JD version, configured
employer branding and a fixed authorized Discord destination.

Collect the application-form URL and deadline, generate a publication preview and require an
explicit interviewer confirmation before posting. Distinguish starting a workflow, supplying
details, revising, rejecting and approving. Keep the Discord bot token in the posting service, not
in the browser or ordinary assistant output.

Persist the reviewed content, approved version, destination, external message reference and
publication outcome. Guard against duplicate publication and handle uncertain provider outcomes
without blind retries. Shared business services must enforce approval regardless of whether the user
uses chat or manual controls.

Acceptance: tests cover explicit approval, rejected previews, stale JD versions, duplicate requests,
service failures and credential isolation. No real Discord message should be sent by normal tests.
Do not add automated hiring decisions or uncontrolled posting destinations.
```

## C-07: Google Forms intake and candidate management

Parent: **P-00** · Prerequisites: **C-06**.

```text
Implement read-only application intake from a Google Form's response Sheet and uploaded Google Drive
files. Route each response to its intended job posting and import supported CV files plus the
optional Candidate photo field. Explain service-account sharing and configurable response-column
mappings.

Make synchronization idempotent using source identities and file hashes. Keep each application's
profile and assessment history isolated: a repeated email address must not merge different
applicants or overwrite another submission. Preserve prior submissions and use conservative
duplicate detection with an auditable repair path.

Build the Candidates workspace with search, job filters, pagination, counts, application details,
authorized CV access and scoped deletion. Provide per-posting notifications for responses waiting to
be synchronized. Deleted source rows must not unexpectedly reappear on every sync.

Acceptance: tests cover repeated syncs, multiple postings, repeated emails, malformed rows,
inaccessible files, deletion exclusions and cross-owner access. Partial import failures should
identify affected rows while preserving successful records. Do not require candidate login or
automatically contact candidates during import.
```

## C-08: CV extraction, OCR and evidence-grounded screening

Parent: **P-00** · Prerequisites: **C-04**, **C-07**.

```text
Implement the ScreeningWorkflow pipeline for PDF and DOCX CVs. Extract selectable text first and
automatically use local Poppler/Tesseract OCR for scanned PDF pages when necessary. Preserve
page/block locators, warnings and source text. Reject unreadable or insufficient-confidence output
instead of scoring it blindly.

Create private CV passages and combine semantic and lexical retrieval with neighboring context. Use
Gemini to extract source-backed profile facts, assess approved job requirements and independently
validate evidence support. Match equivalent meanings without treating different named technologies
or degree levels as interchangeable. Derive exact quotations and offsets from original source text
rather than trusting fabricated citations.

Persist input fingerprints, extraction status, source references, evidence gaps and validated
requirement findings. Cache compatible results and expose per-document retry states.

Acceptance: native, scanned, mixed and unreadable CV tests preserve provenance; cross-candidate
passage leakage is impossible; prompt-like content inside documents is ignored; service failures do
not become zero scores. A mixed batch can retain successful results while clearly reporting failed
documents.
```

## C-09: Deterministic CV scoring and shortlisting

Parent: **P-00** · Prerequisites: **C-08**.

```text
Implement CandidateScoringWorkflow and the CV ranking workspace using validated requirement
findings. Calculate coverage deterministically: met = 1, partially met = 0.5, unmet = 0. Apply
approved requirement weights within categories, then combine category percentages.

Use default category weights of technical skills 50%, experience 30% and qualifications 20%, with
controlled interviewer approval of configurations totaling 100%. Define and validate redistribution
for categories without weighted requirements. Use exact decimal or rational arithmetic so rounding
does not alter ordering or ties.

Persist the scoring configuration, source versions, component breakdowns, explanations and ranking
snapshots. Reuse unchanged inputs and invalidate stale scores. Embedding similarity is for
retrieval, not a candidate score.

Acceptance: repeat calculations produce identical totals, ties use a documented shared-rank rule,
malformed weights are rejected, and unreadable/unprocessed CVs remain unranked. Show traceable
evidence and concise gaps. Completed successful processing must become eligible for scheduling
without a stale document-error flag blocking the candidate.
```

## C-10: Interview scheduling, invitations and rescheduling

Parent: **P-00** · Prerequisites: **C-09**.

```text
Implement a private interview-scheduling MCP service that forwards authorized operations to the
backend using delegated interviewer access. Both the assistant and manual controls must call the
same scheduling services.

Support selecting checked applications, named candidates, the original top N or a score threshold
from persisted rankings. Resolve names only within the selected job and ask for clarification when
ambiguous. Display not scheduled, scheduled and completed states so users cannot confuse eligible
candidates or create duplicate invitations.

Use sequential individual slots, Asia/Dhaka defaults, validated dates/durations and a
recipient/time/email preview. Send SMTP invitations with private join links and .ics attachments
only after explicit confirmation. Support reviewed rescheduling, preserved history and old-link
revocation.

Track pending, sending, sent, failed and uncertain delivery states; uncertain sends must not be
retried automatically.

Acceptance: tests cover name resolution, exclusions, duplicate requests, time calculations, explicit
approval and rescheduling. Mock mail delivery in tests and offer Mailpit for development. Show an
accessible delivery-progress view and reveal the scheduling/preview section after relevant actions.
```

## C-11: Live interview rooms and participant consoles

Parent: **P-00** · Prerequisites: **C-03**, **C-10**.

```text
Implement one-to-one interviews with LiveKit Cloud. FastAPI should authorize rooms and issue scoped
media tokens; browsers must exchange WebRTC media directly with LiveKit, not through the application
proxy or a website tunnel.

Provide device checks, a candidate waiting state, interviewer admission, reconnect/leave handling
and a terminal interview-ended state. Prevent new access after closure and keep transient media
failures from corrupting recruitment records.

Design a polished console: a large main participant view, a smaller switchable self-preview, compact
microphone/camera/leave controls and a stable left-side media area on desktop. Open the interviewer
workspace on candidate information before transcript or assistant tabs. Give candidates a minimal
participation console and a practical-task workspace without exposing transcripts or
interviewer-only analysis.

Acceptance: tests cover admission, token ownership, disconnect/reconnect, closing a room and
responsive keyboard-accessible controls. Do not record audio/video. Use simulated participants in
routine tests; do not consume live media quota automatically.
```

## C-12: Consented live transcription and reliable text persistence

Parent: **P-00** · Prerequisites: **C-11**.

```text
Implement a separate optional transcription-worker container using LiveKit Agents and Deepgram.
Start transcription only after both participants consent and the interviewer explicitly starts it.
The worker must subscribe only to the two authorized microphone tracks, never arbitrary
participants, screen audio or display-name matches.

Send audio from the worker to Deepgram and preserve speaker labels, sequence identifiers, timestamps
and final text. Display interim revisions only in the authorized interviewer UI. Persist final
segments idempotently through a private backend callback protected by a separate worker secret;
block that route through public Nginx proxy access.

Handle reconnection, duplicate events, ordering, bounded queues, provider failure, session gaps and
configurable text retention without interrupting the human call. Keep Deepgram credentials out of
browsers.

Acceptance: tests demonstrate consent enforcement, candidate transcript denial, trusted-track
filtering, callback authentication, replay protection and recovery of saved final text. Record no
raw audio/video, and expose missing-speech/session warnings rather than silently claiming a complete
transcript.
```

## C-13: Transcript understanding, granular scoring and performance summaries

Parent: **P-00** · Prerequisites: **C-04**, **C-12**.

```text
Implement InterviewAnalysisGraph over saved final transcript segments. Detect substantive questions,
pair answers and retrieve approved question/answer guides. Exclude greetings, device checks and
unrelated small talk, but include job-relevant HR, sales, behavioral and technical questions.

Interpret obvious transcription substitutions using the complete exchange while preserving exact
original quotes. Never invent missing concepts, reverse negations or claim to recover audio. If
competing readings change the grade, retain an explicit verification-needed state.

Use Gemini to assign independently supported integer marks from 0 to 100 for relevance, accuracy,
completeness and quality, each weighted 25%. Do not derive numeric marks from a fixed
met/partial/unmet lookup. Independently check citations, meaning and score support. Verified
off-topic or genuinely unanswered questions earn zero; provider/reference/transcript failures do
not.

Analyze answers must persist component scores immediately. Cache unchanged validated results and
provide concise strengths, weaknesses, evidence gaps and verification needs linked to
transcript/reference evidence.

Acceptance: tests cover paraphrases, ASR errors, nontechnical job questions, exclusion rules,
off-topic zeros, nuanced partial credit, quota failures, source validation and repeat-result reuse.
Technical correctness requires suitable approved references.
```

## C-14: Live Work-Sample Studio

Parent: **P-00** · Prerequisites: **C-04**, **C-11**.

```text
Implement a job-scoped practical exercise flow for technical and nontechnical roles. Let the private
interview assistant suggest two or three self-contained tasks grounded in the job and reference
context. After the interviewer selects one, create a private editable draft and reveal the
practical-exercise section.

Use WorkSampleGraph to validate that each task is feasible within 1–15 minutes, including reading
time. Do not generate a configurable assessment rubric, extra attempts, model answers or a written
Explain your approach field. The interviewer asks explanations verbally.

Require review and explicit sharing, candidate readiness and interviewer start. Enforce server-side
timing, autosave and one immutable submission; expiry freezes the latest saved work.

Have Gemini propose a 0–100 correctness score with exact submission-line evidence, followed by a
separate support check. The interviewer approves the verified AI score rather than assigning marks
or awarding an automatic 100.

Acceptance: tests cover draft privacy, readiness, deadlines, autosave, duplicate submissions,
expired work, missing materials, invalid citations and approval gating. Code is reviewed as text
only; do not claim execution, plagiarism detection or proof that outside help was absent.
```

## C-15: Optional application-photo verification

Parent: **P-00** · Prerequisites: **C-07**, **C-11**.

```text
Implement optional one-to-one comparison between the expected application's uploaded photo and short
interview camera samples using local YuNet/SFace models. The candidate gives consent in the
application before matching; consent is not inferred from merely uploading a photo to Google Forms.

Let the interviewer request capture and view match results in candidate information. Candidates
should see a compact permission control, not match scores or sensitive diagnostic results. An
unchecked consent control must not block joining; retain manual interviewer verification.

Encrypt stored reference photos/templates, protect encryption keys, provision model weights
explicitly and implement retention/deletion controls. Do not send biometric images or templates to
Gemini. Show the authorized application photo clearly, centered at a useful size, with resilient
loading and private image access.

Acceptance: tests cover consent, wrong application/interview access, missing photos,
unclear/multiple faces, unavailable models, expired references, capture-request expiry and
interviewer-only results. Face comparison must not change recruitment marks or claim legal-ID
verification, liveness detection or continuous monitoring.
```

## C-16: Fast final ranking and traceable reports

Parent: **P-00** · Prerequisites: **C-09**, **C-13**, **C-14**.

```text
Implement final assessment consolidation using saved, current component results. The fixed final
formula is interview 60% + CV 30% + approved practical 10%. Calculate totals and ranking
deterministically using exact arithmetic and stable shared-rank rules.

Calculate final ranking must not trigger fresh AI grading of interviews or practical work. Identify
missing, stale, failed or unapproved components and direct the interviewer to the required action.
Do not convert a missing assessment into zero or silently redistribute final weights.

Use ConsolidatedAssessmentGraph to resolve source versions, assemble evidence, validate readiness
and produce reports. Optional AI summary selection may prioritize existing grounded facts but must
not invent scores or claims. Present concise candidate-performance cards with expandable traceable
evidence.

Provide private HTML/PDF reports and ranking export. Render reports with scripts disabled and
external resource fetching blocked, and preserve saved policy/source versions.

Acceptance: tests verify the formula, stale-input detection, source ownership, tie handling,
approved practical gating, report reproducibility and safe downloads. Final ranking must remain fast
when scores already exist; final hiring decisions remain human.
```

## C-17: Unified tool-calling recruitment and interview assistants

Parent: **P-00** · Prerequisites: **C-05**, **C-06**, **C-07**, **C-09**, **C-10**, **C-13**, **C-14**, **C-16**.

```text
Implement HireSenseSupervisorGraph with native Gemini tool calling and LangGraph ToolNode. Execute
at most one business tool per user request, then report the tool's actual outcome. Bind
consequential instructions to the real latest interviewer message so a model cannot fabricate an
approval.

Expose nine central-scope tools: generate_job_description, edit_job_description,
approve_job_description, job_posting, sync_responses, screen_candidates, interviews,
candidate_assessments and help. Limit the private interview scope to suggest_interview_questions,
interview_analysis, suggest_practical_tasks and help.

Persist conversation/workflow state and resolve job IDs, candidate names and selections only from
authorized resources. Follow-ups must continue the pending workflow without asking users to repeat
confirmed details. Do not publish, email, share tasks or change meeting access based on retrieved
text.

Reuse the supervisor definition for both scopes rather than creating unconstrained autonomous
agents. Scope and approval guards must remain enforceable without trusting the model.

Acceptance: tests cover unknown tools, malformed arguments, multi-tool attempts, ambiguous
selections, prompt injection, forged approvals, scoped capability denial and accurate reporting of
queued versus completed work.
```

## C-18: Dashboard, navigation and polished user experience

Parent: **P-00** · Prerequisites: **C-17**.

```text
Complete the interviewer dashboard and consistent UX across all implemented workspaces. Show per-job
application counts, pending screening, scheduled/upcoming interviews and actionable next steps using
authorized saved data.

Use reusable styled selects, concise cards, accessible tabs, dialogs, status badges, pagination and
clear empty/loading/error states. Keep the assistant's design consistent between central and private
interview contexts. Use minimal candidate-facing copy while retaining meaningful consent and access
explanations.

Implement explicit action-driven navigation and section reveal: job drafting opens/reveals its
review, named-candidate scheduling highlights the resolved selection/preview, practical-task
selection opens the exercise area, and ranking/analysis actions reveal results or the action
required. Respect reduced-motion preferences, sticky headers and focus management. Do not repeatedly
steal focus during background polling.

Acceptance: keyboard and responsive tests cover the primary workflows, scheduling states are
unambiguous, invitation progress is readable, photos load reliably, and desktop video remains stable
while right-side content scrolls. Do not remove functional safeguards merely to simplify
presentation.
```

## C-19: Regression tests, security and failure recovery

Parent: **P-00** · Prerequisites: **C-18**.

```text
Audit and test the completed application against the parent specification. Use pytest for backend
services/routes, Vitest and React Testing Library for components, and focused arithmetic/workflow
tests. Add disposable-database integration coverage where PostgreSQL behavior matters.

Cover ownership, candidate capability boundaries, injection resistance, explicit approvals,
duplicate/replayed requests, timezone handling, OCR confidence, exact score arithmetic, stale
inputs, transcript uncertainty, one practical submission, biometric consent and retention. Verify
deterministic reuse without claiming the LLM itself is perfectly deterministic.

Provide bounded retries, sanitized provider errors, recoverable persisted job states and
interruption recovery. Do not award zero for service failure or blindly resend uncertain
invitations. Inspect database query duplication and repeated-email handling.

Use isolated synthetic fixtures clearly identified as test/demo data; routine tests must not send
email, publish jobs, call paid AI/media services or touch a real recruitment database. Require
explicit opt-in for external integration checks.

Acceptance: publish actual test results, distinguish pre-existing failures from regressions, remove
confirmed unused code and prompts, and retain migration/compatibility code that still serves saved
records. Never describe a test as passing without running it.
```

## C-20: Reproducible deployment and professional project documentation

Parent: **P-00** · Prerequisites: **C-19**.

```text
Finish deployment and handover for a clean device. Provide Docker Compose startup with persistent
PostgreSQL, Ollama/model cache, private storage, both MCP services, backend and frontend. Gate
backend startup on successful embedding initialization. Include optional profiles for the
transcription worker and Mailpit, plus an optional Cloudflare website tunnel.

Document the configuration that cannot be automatic: Gemini credentials, Google service-account
sharing, Discord bot/channel access, SMTP, LiveKit, Deepgram, identity model provisioning and secure
public origins. Never suggest these accounts are bundled or that the whole system works offline.

Explain health checks, initialization exit status, troubleshooting, backups/restoration including
the biometric encryption key, retention and safe upgrades. A website tunnel must not be described as
carrying WebRTC media.

Write a professional README, feature guides, high-level/system architecture diagrams and editable
draw.io diagrams of actual LangGraph nodes and edges. Maintain an inventory of active application
prompts separately from this implementation blueprint.

Acceptance: a new developer can start supported services, configure integrations, run isolated tests
and understand limitations from the documentation. Do not restart an active interview or contact
real candidates as part of handover.
```

## Review and demonstration checklist

Before presenting the reconstructed implementation to a supervisor, demonstrate:

- An interviewer creates, reviews and approves a grounded JD, then explicitly confirms publication.
- A form response imports once into the correct posting, with a privately accessible CV and photo.
- Both native and scanned CVs preserve evidence references, and failed extraction is not scored.
- Saved CV rankings feed a scheduling preview with clear interview states and confirmed invitations.
- A candidate joins by private link without signup and cannot read interviewer-only resources.
- Consented final transcript text produces saved answer scores and a concise evidence-backed summary.
- The same practical flow supports an engineering task and a nontechnical scenario, with one submission,
  a maximum 15-minute timer, verified numerical correctness marks and interviewer approval.
- Optional photo comparison is local, consented and separate from assessment marks.
- Final ranking reads saved results and applies interview 60%, CV 30% and practical 10%.
- Reports retain traceable sources; provider failures, stale inputs and missing components remain visible.
- A clean-device setup, automated test report and accurate limitations are documented.

This checklist defines expected acceptance evidence; it is not a claim that a newly generated
implementation has already passed those checks.

