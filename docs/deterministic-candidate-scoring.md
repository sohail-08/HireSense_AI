# Deterministic candidate scoring

This feature consumes persisted, evidence-validated `RequirementMatch` records.
It makes no AI calls and does not duplicate CV parsing or requirement matching.
Existing unweighted screening coverage remains available in the API. The interviewer
page shows only the deterministic weighted ranking to avoid competing score views.

## Interviewer workflow

1. Open Assessments and select a job posting with a confirmed requirement profile
   and approved JD.
2. Review only the category percentages (initial proposal: technical 50%, experience
   30%, qualifications 20%). Per-requirement dropdowns and weight inputs are removed.
3. Existing requirement weights and required/preferred classifications are preserved.
   Unmapped selection criteria remain evidence-only, outside the numeric percentage.
   Category assignments in an existing approved configuration remain intact.
4. A category with no positively weighted requirements must receive 0%; redistribute
   its percentage explicitly so all category weights total 100%.
5. Select **Save weights & rank candidates**. This explicitly approves the reviewed
   configuration. Editing inputs alone never approves or recalculates anything.
6. If CVs need processing, the same action starts a screening batch and displays
   progress. The backend automatically scores after saving matches using the approved
   configuration for the exact requirement version. Otherwise saved matching results
   are scored immediately. Errors are shown without replacing the last saved ranking.
7. Read one ranking table (rank, candidate, score). Every application is included,
   with no review queue or unranked candidates. Select **Inspect evidence** for
   scored requirement outcomes, category scores, required gaps and CV quotations/locators.
   Evidence-only selection criteria and their quotations are hidden from this view
   and its Unmet requirements banner, without deleting saved outcomes or changing scores.
   Calculation details and saved explanations are not displayed in this view;
   the backend still preserves them for audit/history.
8. Expand **Previous rankings** only when needed. Historical results retain their
   original weights, and changed requirement versions are labelled. Unapplied edits
   are clearly distinguished from the weights used by the displayed saved ranking.

The Assessments page contains the job selector, three category weights, the ranking
action, and results. Sync responses and the collected-application list are not shown
on this page. Collection and full application management remain on Candidates;
the shared assistant can still sync responses and refresh results.
Technical hashes, formula metadata, duplicate coverage rankings,
application-selection checkboxes, and separate approval/screen/calculate buttons are
not part of this simplified flow. No business records are removed by this UI change.

## Formula and arithmetic

Formula version: `category-weighted-coverage-v4`.
Snapshot version: `scoring-snapshot-v4`.
Version 2 added evidence-only selection criteria. Version 3 converts ambiguous or
missing saved requirement matches to Unmet (zero credit), without a manual requirement
verification step. Version 4 removes review-based ranking exclusion: all applications
receive a rank, and rejected positive evidence receives zero credit at requirement level.
Partially met evidence retains partial credit. Version 1/2/3 snapshots,
justifications and ranks are preserved without recalculation. Select **Save weights &
rank candidates** to create a result using the new policy from existing saved matches.

Status values: met=1, partially_met=0.5, unmet=0. Legacy unable_to_determine outcomes
are normalized to Unmet in new scoring runs and receive zero credit.

```
category_score = sum(requirement_weight * status_value)
                 / sum(requirement_weight) * 100
final_score = sum(category_score * category_weight) / 100
```

Approved requirement weights may be zero (explicit exclusion from numeric coverage),
but cannot be negative or non-finite. At least one positively weighted requirement
must exist in each category with a positive category weight. Missing categories are
shown as N/A, never as 100%. Uncertain requirements remain in the denominator and
receive no credit. Required gaps remain visible even for zero-weight criteria.

Only categorized requirements enter category numerators and denominators. Unmapped
selection criteria keep saved outcomes, evidence, gap reporting and review flags,
but contribute neither points nor denominator weight. They are preserved in saved
API results but hidden from the frontend evidence view. Match counts include both scored and evidence-only
criteria; the percentage is calculated solely from the scored requirements.

The pure service uses exact rational arithmetic for all intermediate values and
ranking. Snapshots preserve exact numerator/denominator pairs. Decimal projections
have 28 significant digits and are stored in PostgreSQL `NUMERIC(80,60)` columns;
JSONB breakdowns also contain precise decimal strings. No percentage-display rounding
is used during calculation or ordering. Repeating fractions necessarily have a finite
decimal projection, but exact rational values retain the original result.

Weights support six decimal places; configuration approval accepts at most 1,000
criteria. The wide numeric scale retains decimal projections even for very small
contributions. These limits avoid unbounded precision and oversized configurations.

Display rule: two decimal places, ROUND_HALF_UP, consistently in the backend
justification and frontend decimal-string formatter. Equal exact scores share ranks
(88,82,82,70 gives 1,2,2,4). Application ID supplies a stable secondary display order.

The percentage is job-requirement coverage, not candidate competence, a probability
of hiring success, or an automated hire/reject recommendation. No automatic required-
gap disqualification rule exists in the current profile schema.

## Evidence and processing diagnostics

Justification is a deterministic template using only approved evaluation criteria,
saved statuses, arithmetic, and reverified quotations with source-block references.
It does not copy unconstrained AI explanations or invent candidate achievements.
Quotations must occur in their saved source block. Unsupported positive outcomes
become Unmet and contribute zero. Missing, duplicate, ambiguous or rejected outcomes
never earn positive credit. New AI schemas and persisted scoring outcomes expose only
Met, Partially met and Unmet; legacy fourth outcomes normalize to Unmet.

No manual review policy: saved diagnostic flags do not remove an application from
ranking. Incomplete or failed screening gives every requirement Unmet (0), with a
processing note in the evidence view. Missing source blocks cannot support positive
credit. Duplicate outcomes and flagged positive matches are Unmet for that requirement;
other grounded matches retain credit. Extraction warnings are retained and disclosed.
Technical parsing failures remain operational failures, not a fourth requirement
outcome or a manual-review queue. Unmet means “not demonstrated by this CV”, not that
the person lacks that capability. Rankings measure available evidence only, and a
zero score from a failed CV must not be interpreted as proof of poor competence.

## Persistence and endpoints

Migration: `0015_deterministic_scoring`, following `0014_pgvector_knowledge`.
It only adds `scoring_configurations`, `scoring_runs`, `candidate_scores`, and
`scoring_request_keys`. PostgreSQL uses JSONB; SQLite tests use JSON.

All endpoints require an authenticated interviewer and enforce job ownership:

- GET `/api/scoring/jobs/{posting_id}/configuration`: current proposal and approval.
- POST same path: explicit approval of category assignments and weights.
- POST `/api/scoring/jobs/{posting_id}/runs`: calculate from saved inputs.
- GET same runs path: saved run history.
- GET `/api/scoring/runs/{run_id}`: persisted ranking, breakdowns and justification.

The run request accepts `configuration_id`, optional `application_ids`, and optional
`idempotency_key`. Default membership is all applications for that posting, including
applications with failed or missing CV processing. Each run snapshots membership, requirement version/hash,
configuration, saved screening-run IDs/versions/models, CV hashes, source blocks,
matches, calculation timestamp, formula and status mapping. CandidateScore records
persist numeric scores, ranking membership, rank, justification and breakdown.

Identical active inputs reuse the existing run. Same idempotency key and request
returns the original run even if active CVs subsequently change; a different request
with that key returns 409. Equivalent numeric weight representations are normalized.
PostgreSQL serializes operations per posting, with unique constraints as a final guard.
Changed weights, requirements or screening inputs create a new run; historical runs
are never recalculated on page load. Scoring is synchronous, local and atomic; request
errors are shown without partially saving a ranking.

Deleting an application removes entire scoring runs containing its copied evidence
and their request keys. This is the intentional privacy/deletion exception to audit
retention, rather than modifying an old calculation. Deleting its job posting cascades
to configurations and runs. Existing PostgreSQL data is preserved by the migration.

## Actual LangGraph

```
START -> category_scoring -> weighted_scoring -> written_justification
      -> rank_candidates -> persist_scores -> END
```

Implementation: `backend/app/scoring/workflow.py`. The graph runs after the existing
screening graph finishes; the call between them is service orchestration, not a
fabricated edge in either compiled graph.

## Verification and limits

Tests use fixed saved outcomes and fake screening AI, never live generation. Coverage
includes arithmetic, weights, missing categories, uncertainty, precision, ties,
grounded explanations, immutable history, idempotency, ownership, candidate denial,
application deletion, automatic scoring after screening, and fresh-session PostgreSQL
round trips. Real database tests create and remove only disposable test databases.

Scoring is exposed in the interviewer UI and invoked automatically after configured
screening; the supervisor does not yet have a separate conversational scoring tool.
PDF/DOCX parsing and Gemini matching retain their existing limitations; deterministic
scoring cannot establish facts absent from a CV. Scores use the confirmed structured
profile, not arbitrary edits to prose JD content. Requirement changes require new
approval and screening against the new requirement version.

## Suggested reviewable commits (user performs Git operations)

1. `feat(scoring): add approved configurations and exact category calculations`
   - Models, migration, schemas, pure calculation service and unit tests.
2. `feat(scoring): persist evidence-backed scoring runs and deterministic rankings`
   - APIs, scoring graph, input snapshots, idempotency, justification, screening hook,
     deletion integration and service/API tests.
3. `feat(ui): add interviewer scoring review and historical ranking breakdowns`
   - Scoring panel, weight approval, ranking columns, expandable saved evidence,
     previous-run selector, documentation and actual LangGraph diagrams.

## File map by increment

1. `backend/app/models/scoring.py`, `backend/app/models/__init__.py`,
   `backend/alembic/versions/0015_deterministic_scoring.py`,
   `backend/app/schemas/scoring.py`, `backend/app/services/scoring_calculation.py`,
   `backend/tests/test_scoring_calculation.py`, `backend/tests/test_migrations.py`.
   Test this increment with `pytest tests/test_scoring_calculation.py tests/test_migrations.py`.
2. `backend/app/services/scoring_service.py`, `backend/app/scoring/__init__.py`,
   `backend/app/scoring/workflow.py`, `backend/app/routes/scoring.py`,
   `backend/app/main.py`, `backend/app/services/screening_service.py`,
   `backend/app/services/candidate_application_service.py`, `backend/tests/test_scoring.py`.
   Test with `pytest tests/test_scoring.py`, then the complete backend suite.
3. `frontend/src/components/candidates/CandidateScoringPanel.tsx`,
   `frontend/src/pages/ScreeningPage.tsx`, `README.md`, this document,
   `docs/langgraphs/05-candidate-scoring.drawio`, `docs/langgraphs/README.md`,
   `docs/langgraphs/hiresense-all-langgraphs.drawio`,
   `docs/hiresense-langgraph-workflow.drawio`. Check with `npm run build` and
   `npm run test:scoring` (decimal total and score-display regression tests).

Pre-existing environment consolidation and Google integration changes are separate
working-tree edits and should not be accidentally grouped into these scoring commits.
