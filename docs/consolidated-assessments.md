# Candidate scores and final ranking

## Interviewer workflow

1. In **Assessments**, select a job, choose the CV scoring weights, and rank CVs.
2. Conduct the interviews and save the transcripts.
3. In **Reports**, select the job and click **Calculate final ranking**.
4. Read the table: rank, candidate, CV score, interview score, final score.
5. Open **View details** to see question scores. Expand a question and
   **Why this score? View evidence** to read the answer and exact source quotes.
6. Download the ranking or a candidate report if needed. HTML/print remains
   available if PDF preparation fails.

The main screen does not expose source hashes, requirement matrices, review
checkboxes, version selectors, or a multi-step comparison form. Evidence is optional
to inspect, not a gate that blocks the ranking. The existing CV Assessments page
and its approved category weights are unchanged.

## Scoring

The interviewer approved this fixed formula:

**Final score = CV score × 50% + interview score × 50%.**

For example, CV 80% and interview 60% give a final score of 70%.

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
interview/analysis, or application cohort prompts **Calculate again**. Old reports
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
simpler UI retains those functions while using the interviewer's approved 50/50
policy. The original WBS spreadsheet and requirements PDF were not modified.

## Verification and synthetic samples

Run backend tests from `backend` with `.venv/Scripts/python.exe -m pytest` and
frontend tests with `npm run test:rooms`, `npm run test:scoring`, and
`npm run test:interviews`; production build: `npm run build`.

`python scripts/generate_assessment_samples.py --output ../output/pdf` generates
synthetic-only individual and comparison PDFs for layout checks. It never reads
the database or real CVs/transcripts. Generated artifacts are ignored by Git.
