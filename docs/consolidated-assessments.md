# Candidate scores and final ranking

## Interviewer workflow

1. In **CV Screening**, select a job, choose the CV scoring weights, and rank CVs.
2. Conduct the interviews and save the transcripts.
3. Review the live practical response and approve or reject correctness.
4. In **Assessment**, select the job and click **Calculate final ranking**.
   Read rank, candidate, CV score, interview score, practical score and final score.
5. Search candidates by name and use the pagination controls for larger lists.
   Filtering and paging never renumber the saved ranks or recalculate scores.
6. Open the **View details** button to inspect question scores in a modal. The
   ranking stays in place behind it, with search/page state preserved. Closing
   restores focus to the triggering button; loading failures can be retried inside
   the modal. Existing report/comparison deep links also open there. Expand a question and
   **Why this score?** to read the score explanations. Each answer is displayed
   once, without transcript source details or extra quoted passages beneath the
   explanations. Saved evidence and the separate CV evidence section are unchanged.
7. Click **Download this report** in candidate details to prepare and download
   a PDF in one step. The button shows progress and can be retried if preparation
   or download fails. Ranking/comparison exports retain their existing formats.

**Candidate performance** replaces the verbose evidence-summary grid. Strengths and
areas to improve are short, grouped highlights (three visible per card). Unassessed
topics and verification points stay in separate collapsed sections. Use **Show all**
for additional highlights or **Sources** for original explanations and evidence.
The concise wording is a deterministic presentation of validated labels and source
statuses, not a new AI judgment. Existing saved reports adopt this presentation
without changing their original findings, scores or saved weights.

The main screen does not expose source hashes, requirement matrices, review
checkboxes, version selectors, or a multi-step comparison form. Evidence is optional
to inspect, not a gate that blocks the ranking. The existing CV Assessments page
and its approved category weights are unchanged. The job selector and calculation
action share a compact card with CV/interview/practical weight chips. Table score bars are
decorative: exact decimal formatting and server-provided ranks remain authoritative.
Missing scores remain dashes, and zero scores remain zero. No model work or export
is started by opening, searching, paging or inspecting the ranking.

## Scoring

The interviewer approved this fixed formula:

**Final score = interview score × 60% + CV score × 30% + practical score × 10%.**

For example, CV 80%, interview 60% and practical approval (100%) give 70%.
Rejection (0%) gives 60%. A pending practical review is not zero and withholds
the final score/rank. Correctness is decided by the interviewer after discussing
the candidate's single submitted response, not by an AI model.

Formula `cv30-interview60-practical10-v3` replaces the previous 40/60 policy. Click **Calculate
final ranking** to update existing totals. Validated interview grades and CV scores
are reused; changing these weights does not itself require another AI assessment.
Historical reports retain their saved weights and totals, and old rankings/reports
are marked outdated. Reports with different final weighting policies cannot share
a new combined rank. Screen and export formula captions use each report's saved weights.

The interview score is the average score of all included interview questions.
Each question uses the saved answer rubric: relevance, correctness, completeness,
and reasoning/examples, equally weighted at 25% each. Each dimension earns 1,
0.5, or 0 based on validated evidence. Unanswered questions score zero; explicitly
excluded/procedural questions do not enter the average. A missing transcript,
expired source, or failed analysis is not an unanswered question and is not made
into a zero. It gets a short explanation and no final rank until scoring succeeds.

Positive credit requires a validated candidate quote. Correctness also needs an
answer guide or technical reference; completeness needs an answer guide. These
remain in the knowledge base with the suggested questions. The total is computed
in application code, not chosen by the language model. Exact rational values
determine ranking and ties; displayed percentages are rounded half-up to 2 places.
Equal totals share a rank (1, 1, 3). Comparable candidates must use the same job
requirements, CV formula/weights, and interview rubric.

Scores describe job-requirement evidence, not hiring-success probability. There
is no automated hire/reject decision, automatic invitation, or report emailing.

## Background processing and persistence

`POST /api/assessments/jobs/{job_id}/ranking` with `{"confirmed":true}` starts a
durable job-wide calculation. `GET` at the same URL only reads progress/results;
opening the page never starts model work. The central assistant can call the
native `candidate_assessments` tool with `operation="rank"` on explicit request.

`FinalRankingService` freezes the application cohort, saved CV scoring run, and
latest completed interview (by scheduled start, then ID). It reuses fresh saved
answer analysis; missing, failed or stale analysis is queued through the existing
Feature 5 service. Then it creates versioned consolidated reports and persists
their final ordering. The existing background worker resumes this workflow after
a restart. CVs are not re-screened by this action. Repeated requests reuse work;
an explicit retry can retry failed processing.

The coordinator stores its state in the existing `assessment_comparisons` JSON
snapshot and linked assessment IDs. No schema migration, separate database, or
new service is needed. The original CV ranks and successful historical report
versions are preserved. A changed transcript, CV score, job requirement, selected
interview/analysis, practical decision, or application cohort prompts **Calculate again**. Old reports
are never relabelled with an invented final score.

## Main implementation files

- `backend/app/assessments/final_scoring.py`: exact totals, plain summaries, ties.
- `backend/app/services/final_ranking_service.py`: durable job-wide coordination.
- `backend/app/assessments/workflow.py`: existing seven-node consolidation graph;
  `aggregate_components` computes totals. No extra model call is needed to combine
  scores or produce the short explanations.
- `backend/app/services/interview_analysis.py`: saved transcript answer scoring
  and the shared background worker.
- `backend/app/services/assessment_service.py`: versioned reports and comparisons.
- `backend/app/routes/assessments.py`: authenticated progress/calculation routes.
- `frontend/src/pages/ConsolidatedAssessmentsPage.tsx`: simple ranking page.
- `frontend/src/components/assessments/FinalRankingTable.tsx`: searchable, paginated
  ranking table, score comparisons and explicit report actions.
- `frontend/src/components/assessments/AssessmentView.tsx`: scores and optional evidence.
- `backend/app/assessments/templates/report.html`: concise private HTML/PDF layout.

## Privacy and exports

Every read, calculation, comparison and export checks interviewer ownership.
Responses are private/no-store. Source expiry and deletion also delete pending
rankings and related report files; filesystem removal occurs only after commit.
No additional candidate data is sent to an AI model during total calculation.
Exports freeze their payload, use autoescaped application-owned HTML, and check
file hashes. PDF rendering remains offline, JavaScript-disabled, resource-blocked,
and bounded by a hard subprocess deadline. A failed export cannot invalidate scores.

The supplied WBS rows 36–42 and business requirements Features 5–6 cover question
answer analysis, consolidated assessment, reports and candidate comparison. This
simpler UI retains those functions while using the interviewer's approved 60/30/10
policy. The original WBS spreadsheet and requirements PDF were not modified.

## Verification and synthetic samples

Run backend tests from `backend` with `.venv/Scripts/python.exe -m pytest` and
frontend tests with `npm run test:rooms`, `npm run test:scoring`, and
`npm run test:interviews`; production build: `npm run build`.

`python scripts/generate_assessment_samples.py --output ../output/pdf` generates
synthetic-only individual and comparison PDFs for layout checks. It never reads
the database or real CVs/transcripts. Generated artifacts are ignored by Git.
