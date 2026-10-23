# Innovation Feature — Live Work-Sample Studio

This feature adds an observable work product to the existing CV and interview
evidence. It supports code or written responses, including fictional HR, sales,
and support exercises. It does not infer honesty, personality, protected traits,
AI assistance, or future job performance.

## Using the feature

Open an interview console and select **Practical exercise**. Prepare a task
manually, choose one of your saved templates, or request an AI draft based on the
job description and available knowledge. Check every generated fact, permitted
tool rule, deliverable and criterion. Weights must total 100. Private draft saves
do not message the chatbot or send invitations. Templates are immutable copies
and should contain reusable, synthetic material only.

**Approve & share task** freezes the task/rubric snapshot and makes it visible to
the admitted candidate in their existing private interview page. The candidate
reads it, asks clarifications, and selects **I'm ready**. Only the interviewer
starts the working period. Video/audio and consented transcription remain the
existing independent services; an exercise does not enable recording or obtain
device permissions automatically.

The candidate writes a response and explanation. Changes autosave after a short
typing pause; **Save now** is also available. The interviewer sees the last
server-saved work, not unsent keystrokes. Timing adjustments require a reason;
pauses stop editing and preserve unsaved text in the current page. Reloading
restores server-saved work, not offline changes. A before-unload warning helps
avoid losing unsaved changes; no candidate text is stored in localStorage.

**Submit exercise** saves the current response and explanation atomically and
locks the final attempt. Its receipt is shown only after server acknowledgement.
Time expiry or interview shutdown freezes the latest server-saved draft with a
different status; neither is relabelled as candidate-confirmed submission.
Another attempt requires interviewer authorization and a reason, retains the
original, starts from a copy, and waits for readiness again (maximum five).

After discussing the work, the interviewer can optionally select up to 12 saved
transcript passages (16,000 characters total) before choosing **Assess exercise**.
Interviewer passages are context only. Candidate discussion can be cited, but
unclear ASR remains unverified. The task, exact response, chosen discussion,
hashes, prompt version and model are frozen in a durable assessment request.

The interviewer reviews concise criterion findings, expands exact evidence as
needed, adjusts the summary/outcomes/reasons/quotations, and records a review
note before approval. AI drafts are retained separately from approved findings.
Approval is immutable. A new attempt is the explicit way to collect more work.
Accepted AI results are reused; retry only retries a failed assessment, not an
accepted score. No practical result enters the existing 40% CV / 60% interview
formula. Newly generated candidate reports and PDF exports include a separate
practical section; old saved reports remain historical and become stale when
their sources change. Recalculate the ranking to refresh a saved report.

## Assessment boundaries

The LangGraph pipeline generates a structured assessment, validates exact source
quotes and line ranges, then independently checks logical support against the
approved criteria/materials. Every scored finding needs evidence. Unsupported
findings become **Needs verification**; a provider/schema/evidence failure yields
an unavailable assessment, never a zero. Numeric aggregation is deterministic:
met=1, partially met=0.5, unmet=0, weighted by the approved rubric. If any criterion
needs verification, the overall practical percentage is withheld.

An independent AI check is not a guarantee of correctness. Human review remains
essential. The code editor is a text workspace: no code execution, test runner,
dependency installation, arbitrary repository fetching, or runtime verification
exists in this version. Nothing may claim tests passed on that basis. Use
job-relevant criteria and consistent conditions, allow appropriate adjustments,
and never penalize device/connection problems or use camera/typing behaviour as
a cheating score.

## Persistence and access

Migration `0024_live_work_samples` adds private template, exercise, attempt and
assessment tables to PostgreSQL. No external file uploads are accepted. Exercise
commands serialize on the assigned interview row; candidate saves also require
the expected attempt ID and draft revision to prevent stale-tab overwrites.
Submitted attempts have content hashes and cannot be modified by normal saves.

Candidates use the existing expiring, revocable, application-scoped HttpOnly
interview cookie and admission check; matching a candidate account's email never
grants access. Candidate mutations require the configured frontend origin.
Candidates cannot access templates, events, private reviews, assessment results,
reports, or other candidates' work. Interviewer endpoints require JWT role and
ownership checks. Sensitive responses are no-store; no credentials or submission
content are written to application error logs.

`WORK_SAMPLE_RETENTION_DAYS` defaults to 30 days from task creation. Linking a
discussion passage can shorten expiry to that passage's retention deadline.
Expired exercise access is denied immediately; a durable worker removes expired
work and derived reports. Candidate/application deletion explicitly removes work,
attempts, assessments and derived reports. Deleting a transcript also removes
practical assessments containing copies of that discussion, while retaining the
independent written submission. Saved reusable templates remain until managed
by their owner and must not contain candidate-specific personal information.

The worker recovers only queued/interrupted assessments on backend restart.
It never shares tasks, starts exercises, approves reviews, or sends email.
Normal Docker restarts preserve database content. Build/restart the backend and
frontend through the existing safe deployment procedure; startup applies the
Alembic migration. No new external service is required beyond configured Gemini
and the existing knowledge embedding service for optional AI task drafting.

## Verification

Offline tests use synthetic task/response data and fake models/media. Run:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_work_samples.py tests/test_migrations.py -q
cd ../frontend
npm run test:rooms -- tests/rooms/work-samples.test.tsx
npm run build
```

The real PostgreSQL concurrency tests use only disposable randomly named test
databases when `PGVECTOR_TEST_SERVER_URL` is explicitly configured. No paid model,
mail, publication, real candidate scoring, or browser automation is used for
verification.
