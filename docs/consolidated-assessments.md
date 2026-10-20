# Feature 6 — consolidated assessments and private reports

## Scope and reference coverage

The implementation was checked against `HireSense_WBS_Final_Functionality_Covered.xlsx`
(`WBS_20_Days`, rows 36–42, 50–55) and the supplied business-information PDF
(Features 5–6, pp. 13–14; privacy, asynchronous processing and persistence requirements,
pp. 18–22). The original spreadsheet and PDF were not modified.

Feature 6 now consolidates saved CV screening, deterministic scores, selected
interview analysis and reviewer annotations; shows suitability, supported strengths,
limitations, gaps and verification; exports/prints private reports; and compares
same-job candidates without inventing a combined hiring score.

The Feature 5 gap addressed here is **question-side requirement coverage**.
Question detection can attach only approved requirement IDs to an actual spoken
question. Pairing preserves them, including after interviewer pairing corrections.
Coverage distinguishes `asked_unanswered`, `asked_answer_pending`, `answered`,
and `not_explored`. Being asked about a requirement does not prove it is met.
The pairing version changed to `question-coverage-turn-pairing-v2`; old saved
analysis remains unchanged. Explicitly analyze saved answers again to obtain
question-side coverage for old interviews. Report generation never does that work.

The optional comprehensive CV-claim verification/coding exercise features are not
prerequisites and were not added. No report email delivery was added.

## Interviewer workflow

Open **Reports** in interviewer navigation, or the report action in Jobs,
Candidates or Interviews. The existing **Assessments** CV ranking screen remains.

1. Select a posting and a candidate application.
2. Read the source-readiness notice. Missing evidence permits a labelled partial
   report; it does not become a zero score or a successful complete assessment.
3. Generate an assessment. Polling shows queued/processing stage and the final
   completed/failed outcome. Generation is background work, not HTTP model work.
4. Inspect saved CV components, suitability narrative, requirement matrix,
   questions/answers, evidence, provenance and limitations.
5. Record a separate authored/timestamped review note. Notes do not overwrite findings.
6. Prepare HTML for download/print or prepare a PDF. A failed PDF does not fail the
   assessment or prevent an independent HTML export.
7. Choose a prior assessment version, or explicitly generate a new version after
   relevant source changes. Old report content is never silently replaced.
8. Check 2–4 applications to save a side-by-side comparison of their latest completed
   assessment versions. The comparison endpoint also accepts explicit historical IDs.

The central supervisor binds the native `candidate_assessments` tool through its
existing `bind_tools()` / `ToolNode` flow. Examples: “Show the consolidated
assessment”, “Generate the assessment”, “Compare these candidates”. Select the
application(s) on Reports first, or explicitly give application IDs. Returned links
open the authorized saved reports. The interview-room capability allowlist remains
restricted and cannot access recruitment-wide reports or other candidates.

## Sources, lifecycle and ranking policy

Each assessment belongs to **application ID + posting ID**, not name/email.
It freezes the approved requirement/configuration, saved scoring run/result,
screening run, CV hash/source blocks, selected interview(s), unexpired finalized
transcript revisions, selected answer-analysis versions and their annotations.

Default interview selection: the latest completed interview by scheduled start,
then interview ID (`latest-completed-interview-by-scheduled-start-v1`). It does not
silently union historical interviews. The UI can explicitly select up to five
sessions or a CV-only partial report. The API can pin scoring/analysis versions.
The default CV score is the latest completed compatible scoring run for the
current requirement version. Selecting an older version is labelled incompatible
with current requirements, not quietly represented as current.

Generation state (`queued`, `processing`, `completed`, `failed`), evidence
completeness (`complete`, `partial`), and interviewer review (`reviewed`,
`not_reviewed`) are separate. A completed task may contain partial evidence.
Complete means source readiness/compatibility passed, not that all requirements
are met. Unexplored requirements are never changed into unmet interview outcomes.

Generation, read and export do not invoke parsing, screening, transcription,
answer analysis, SMTP, LiveKit or Google. Manual generation is the default; no
automatic assessment generation was enabled. Startup recovers interrupted queued
work through the existing analysis background loop.

Staleness compares relevant source identities, CV hash, requirement version,
transcript watermark and selected analysis/reviews, not unrelated record counters.
Review notes on the consolidated report do not invalidate its source evidence.
Saved comparisons keep their original report versions/cohort/order and show a
separate historical-source notice when those sources change.

CV Decimal values, category/requirement weights, formula, match counts, required
gaps, written justification, full-job cohort and original ranks are preserved.
Screening and its derived score are **one evidence component**, never two weights.
Existing saved answer scores are displayed as findings only. The repository has
no approved combined CV/interview weighting policy: no combined score, overall
post-interview rank, “hire/reject” threshold, or hiring-success probability is invented.

Comparison ordering is explicitly **CV score order**. It requires completed,
compatible CV screening/scoring, matching requirement version, formula and
configuration, with no relevant source staleness. Otherwise the comparison is
informational and explains incompatibilities. Rubric differences are also shown.
Ordering uses the saved exact rational score where available, otherwise the
stored decimal. Ties share competition rank; application ID only stabilizes display.
Selected-cohort ranks do not replace the original full-job ranks/cohort.

## Evidence and AI boundary

CV quotes must occur in the selected document's stored source block. Interview
quotes must resolve to the authorized interview/session/segment/revision, exact
characters, timestamps, offsets and trusted speaker role. Question/answer pair
ownership and question/interviewer vs answer/candidate association are rechecked.
Technical-reference quotes must match the snapshotted guide version/content.
Unverifiable citations are excluded and surfaced as limitations.

The saved Feature 5 logical-support check is required before retaining a supported
interview conclusion; a matching quote alone is not sufficient. Conflicting CV and
interview findings are retained separately and never labelled misrepresentation.
Unanswered questions, unverified claims, unreliable transcription, missing
processing and unexplored requirements remain distinct.

Narrative facts are produced by explicit auditable templates over validated saved
results. Gemini can only select/order existing fact IDs within their original
categories (Pydantic schema, at most two attempts, provider timeout 45 seconds).
It cannot introduce free-form claims, scores, weights, ranks, decisions or tools.
Invalid/unavailable model output falls back to the deterministic supported facts.
No live Gemini request was needed for synthetic verification.

Actual consolidation graph nodes, in order:

`resolve_source_versions` → `validate_readiness` → `build_requirement_matrix` →
`aggregate_components` → `draft_summary` → `validate_claims_citations` →
`persist_assessment`.

These seven registered nodes have eight unconditional edges including START/END.
The model is used only in `draft_summary`; API/service orchestration is not drawn
as fictitious graph edges. The older draw.io bundles are not regenerated here.

## Storage, privacy and migration

Migration `0022_consolidated_assessment` follows `0021_interview_analysis` and adds:

| Table | Purpose |
| --- | --- |
| `assessment_runs` | Immutable source/result versions, fingerprints, lifecycle, expiry |
| `assessment_reviews` | Separately authored review notes |
| `assessment_comparisons` | Frozen explicit cohort and selected report versions |
| `report_artifacts` | Frozen export payload, template/format, state, private key and SHA-256 |

It does not replace existing tables or delete business data. Downgrade refuses to
discard nonempty assessments. The normal entrypoint runs `alembic upgrade head`.
Application row locks plus unique version/fingerprint constraints protect creation.
Repeated identical source requests reuse an existing run; **Generate new version**
explicitly creates a new version. Exports are idempotent for their frozen payload.

All endpoints require interviewer JWT plus posting/application ownership, including
comparison/export/download. Candidate JWTs and candidate invitation cookies cannot
read these reports. Responses use private/no-store caching. No CV disk paths,
meeting links/tokens, SMTP credentials or worker secrets appear in report data.

Exports live under `backend/storage/reports/<random-id>.html|pdf` on persistent
Docker bind storage. Downloads use authorized endpoints and validate SHA-256;
storage keys are not exposed. Reports retain minimal identity, not email/phone.
Report snapshots contain necessary private evidence text: treat them like transcripts.

Derived assessments/comparisons/artifacts expire no later than their selected
transcription sources. Expired reads/downloads are denied; background cleanup
removes their rows and files. Application deletion and interview/transcript cleanup
also remove derived reports and comparisons. Physical files are unlinked after
transaction commit (rollback preserves them). Backups and already-downloaded
copies remain subject to the operator's retention process. A filesystem unlink
failure can leave an inaccessible private orphan that needs operational cleanup.

The root `.env` is unchanged; no new secrets/environment file is needed. Storage,
generated samples and private credentials stay ignored by Git.

## HTML/PDF runtime

`Jinja2==3.1.6` and `playwright==1.64.0` are pinned. Docker installs Chromium and
its OS/font dependencies as part of the backend image, then runs as `appuser`.
The renderer works without a paid export service. A clean rebuild may take several
minutes and increases image size because Chromium is included.

Application-owned Jinja templates autoescape candidate/LLM text. No candidate
HTML is executed. CSP, disabled JavaScript, blocked service workers, offline
browser context and an all-request abort route prevent remote resource fetching.
HTML is bounded to 4 MB of UTF-8 bytes. Renderer subprocesses receive only an allowlist
of runtime/cache variables, not application API keys or JWT/SMTP secrets. A separate renderer process has a 55-second
wall-clock deadline covering startup/layout/printing/closure; browser launch and
content load also have 15-second limits. Timed-out process groups are terminated.
`Page.pdf()` itself has no timeout argument; the process deadline bounds it.

Reports include branding, versions, component scores, matrix, Q&A, reviewer notes,
numbered evidence appendix, limitations, wrapping/repeated table headers and page
numbers. Individual PDFs use A4 portrait; comparisons use A4 landscape and include
the full underlying reports after the comparison table. HTML supports browser print.

Primary implementation references checked:
[Jinja autoescaping](https://jinja.palletsprojects.com/en/stable/api/),
[Playwright browser installation](https://playwright.dev/python/docs/browsers),
[PDF API](https://playwright.dev/python/docs/api/class-page#page-pdf),
[resource routing](https://playwright.dev/python/docs/api/class-browsercontext#browser-context-route).

## Affected folder structure / file manifest

```text
backend/
  alembic/versions/0022_consolidated_assessment.py          new
  app/
    assessments/{__init__,sources,workflow,reports,pdf_worker}.py  new
    assessments/templates/report.html                    new
    models/assessment.py; schemas/assessment.py            new
    routes/assessments.py                                 new
    services/{assessment_service,report_service}.py        new
    agents/{interview_analysis,supervisor,supervisor_tools}.py  modified
    schemas/{interview_analysis,supervisor}.py              modified
    services/{interview_analysis,candidate_application_service,supervisor_service}.py modified
    main.py; models/__init__.py                            modified
  scripts/generate_assessment_samples.py                  new, synthetic-only
  tests/{assessment_fixtures,test_assessments,conftest}.py  new
  tests/test_interview_analysis.py                        modified
  Dockerfile; requirements.txt                            modified
frontend/src/
  components/assessments/{assessmentApi,AssessmentView}.tsx/ts  new
  pages/ConsolidatedAssessmentsPage.tsx                    new
  App.tsx; types/index.ts                                 modified
  components/{assistant/SupervisorProvider,common/Navbar,jobs/SupervisorChatPanel}.tsx modified
  components/interviews/{analysisApi,InterviewAnalysisPanel}.ts/tsx modified
  pages/{CandidatesPage,InterviewsPage,JobDescriptionPage}.tsx modified
frontend/tests/rooms/assessments.test.tsx                  new
docs/consolidated-assessments.md                          new
docs/interview-analysis.md; docs/langgraphs/README.md; README.md; .gitignore modified
output/pdf/                                              generated, ignored
```

## API reference

All paths below are under `/api/assessments`:

- `GET /applications?job_posting_id=…` — authorized application/readiness list.
- `GET /applications/{id}` — readiness, interview options and version history.
- `POST /applications/{id}` — queue/reuse a version; optional `scoring_run_id`,
  `interview_ids`, `analysis_run_ids`, `new_version`.
- `GET /runs/{id}` — generation state and persisted report, with current staleness.
- `POST /runs/{id}/reviews` — separate review note and reviewed marker.
- `POST /comparisons` — 2–4 explicit `assessment_ids` for distinct same-job applications.
- `GET /comparisons/{id}` — saved comparison/order, source-change notice.
- `POST /runs/{id}/exports` or `/comparisons/{id}/exports` — `format: html|pdf`, optional retry.
- `GET /exports/{id}` — asynchronous export status.
- `GET /exports/{id}/download` — private, hash-checked attachment.

## Verification and manual checks

Validation results and sample inspection notes are recorded below after the final
checks. Initial tests caught a synthetic role-policy fixture issue, an import-order
test settings issue, and the unsupported Playwright PDF timeout argument; each was
corrected before final verification.

Verified on 2026-10-20:

| Check actually executed | Result |
| --- | --- |
| Full local backend suite, including worker tests | 341 passed, 15 optional integration checks skipped |
| Full backend-container suite, excluding separate worker runtime | 330 passed, 9 optional checks skipped |
| Focused assessment + Feature 5 suite after renderer isolation | 60 passed |
| Assessment suite after export-file cleanup change | 25 passed |
| Frontend component tests | 52 passed |
| Frontend scoring + scheduling tests | 7 + 2 passed |
| TypeScript/Vite production build and backend/frontend Docker builds | Passed |
| PostgreSQL migration | `0022_consolidated_assessment`; all four new tables present |
| Deployment health / report page / authenticated application list | HTTP 200 |
| Private report download without JWT | HTTP 401 |
| Assessment API cache policy | `no-store` |
| Existing users/jobs/applications/CVs/interviews/transcripts/scoring-run counts | Unchanged before vs after migration |
| Current public-origin setting | Preserved; no Cloudflare hostname rotation |
| Git whitespace check with CRLF-aware settings | Passed |

Synthetic PDF verification: the final portrait individual stress report has 10
pages; the landscape comparison plus both full evidence reports has 27 pages.
Every page was rendered to PNG and reviewed in contact sheets; title, matrix,
comparison and appendix/end pages were also inspected at readable size. Repeated
table headers, wrapping, numbered references and page footers were verified.
Automated text-box checks found zero characters outside either PDF page bounds.
Candidate identifiers and saved score values (including 75.00 and 68.75) matched
their HTML/PDF representations. The deliberately long samples contain partial
source cases; real candidate files were not used. Generated artifacts are under
`output/pdf/`, excluded from Git.

Non-blocking warnings remain: existing LangGraph/Starlette deprecations and the
existing large LiveKit bundle warning. Skipped optional provider/database integration
checks were not claimed as passed. No live Gemini, Deepgram, SMTP or media call was
made for report verification. The configured Cloudflare origin was preserved, but
this task did not start/rotate a tunnel or test remote meeting connectivity.

Reproduce backend tests from `backend/`:

```powershell
.venv/Scripts/python.exe -m pytest tests -q
```

Container backend tests exclude the separate transcription-worker runtime tests:

```powershell
docker compose run --rm --no-deps --entrypoint python backend -m pytest tests -q -p no:cacheprovider --ignore=tests/transcription_worker
```

From `frontend/`: `npm run build`, `npm run test:rooms`, `npm run test:scoring`,
`npm run test:interviews`. Rebuild with `docker compose build backend frontend`.
Before restarting, finish active interviews/transcription and pending email delivery.
For Cloudflare mode use the existing demo restart helper/current origin, not a plain
Compose restart that resets public links to localhost.

Generate **synthetic-only** individual/comparison samples from the repository root:

```powershell
New-Item -ItemType Directory output/pdf -Force
docker compose run --rm --no-deps --entrypoint python -v "${PWD}/output/pdf:/output" backend scripts/generate_assessment_samples.py --output /output
```

The sample generator does not query the database or read real CV/transcript files.
Source fixtures and scripts are reviewable; generated PDFs/HTML/PNG are ignored.

Manual acceptance checks:

1. Generate a report for an application with saved CV score + completed analyzed interview;
   verify selected interview, requirement version and source IDs, then reload.
2. Generate with missing/failed/unfinalized sources: expect completed **partial** report.
3. Open a source citation and compare exact quoted text, version, speaker and offsets.
4. Change relevant upstream evidence; old report stays unchanged with a stale notice.
   Generate a new version and switch between versions.
5. Compare two same-job reports with common CV configuration; verify saved scores,
   tie handling, comparison cohort and unchanged original full-job ranks.
6. Compare incompatible versions: expect informational results, not a fabricated order.
7. Save a note, export HTML/PDF, print HTML; verify facts match the chosen version.
8. Check missing/invalid candidate JWT, candidate cookie and foreign-owner export access.
9. Delete a test application or expire a test transcript; derived rows and private
   files should disappear. Already-downloaded files cannot be remotely revoked.

## Limits / operational decisions

- Manual assessment generation is enabled; automatic generation is intentionally off.
- No approved combined weighting policy exists, so interview findings never alter CV ranks.
- Comparisons are limited to four candidates; selected interview sessions to five.
- Text-generation quality is constrained by upstream evidence and its logical-support checks;
  provider failure has a deterministic fallback, not fabricated prose.
- Missing or expired sources cannot be recovered by report generation. Run the actual
  upstream workflow explicitly if appropriate; retention deletions are not reversed.
- Long reports include full evidence appendices and can span many pages.
- The existing single-interviewer product policy is unchanged.
- No real candidate report, credential, CV or transcript is added to Git.

## Reports navbar crash regression (2026-10-20)

A completed report with `Numeric(80, 60)` zero scores returned `0E-60` from
PostgreSQL/Python Decimal. The fixed-point-only percentage formatter passed that
string to `BigInt`, throwing during `AssessmentView` rendering and unmounting the
application. The shared formatter now handles decimal/scientific notation using
exact coefficient/exponent arithmetic and half-up rounding; invalid values remain
unavailable rather than becoming zero. Stored report values are not changed.
A Reports-scoped error boundary preserves navigation and offers recovery for
unexpected future render/chunk errors. Full App/navbar regression tests cover
initial navigation, automatic opening of the saved zero-score report, and recovery.
Verification: 55 component tests, 9 scoring tests, 2 scheduling tests and both
local/Docker production frontend builds passed. Direct browser inspection was
blocked by saved browser permissions; no browser workaround was used.

## Suggested reviewable commits

1. `feat: persist versioned consolidated assessment sources and lifecycle`
2. `feat: consolidate validated CV and interview evidence with explicit LangGraph stages`
3. `feat: add private assessment reports and central supervisor report tools`
4. `feat: compare saved candidate assessments with transparent CV-only ordering`
5. `feat: export escaped assessment HTML and bounded offline Chromium PDFs`
6. `test: verify assessment privacy provenance exports and question coverage`

A single combined alternative:

```text
feat: add evidence-grounded consolidated candidate assessments and reports

- Persist versioned application-scoped CV and interview source snapshots
- Consolidate validated findings without rerunning upstream workflows
- Add report generation, evidence inspection, review notes and source-change notices
- Compare same-job candidates with explicit CV-only ordering and preserved cohorts
- Export private HTML/PDF reports using escaped templates and offline Chromium
- Distinguish unanswered interview requirements from unexplored coverage
- Add synthetic regression tests, sample reports and deployment documentation
```
