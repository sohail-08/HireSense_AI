# HireSense: Approximate LLM Token Usage

Planning estimate · 27 October 2026

## Executive estimate

For **one job posting, 10 screened CVs and 3 interviewed candidates**, with **8 substantive
answers and one practical exercise per interview**, a useful initial estimate is:

| Measure | Worked-example allowance |
| --- | ---: |
| Gemini input tokens | 1,005,600 |
| Gemini visible output tokens | 141,950 |
| Input + visible output | **1,147,550 ≈ 1.15 million** |
| With a 25% operational reserve | **≈ 1.43 million** |
| Successful model calls under the stated assumptions | 219 |

Use **about 1.4–1.5 million input-plus-visible-output tokens** as a provisional allocation for this
example, **before any additional model thinking tokens**. This is a planning scenario, not a measured
average, a hard maximum, a provider quota guarantee or a currency-cost estimate.

The largest component is transcript answer analysis: the current pipeline can make four separate
model requests per answer and resend job requirements, references and prior structured findings.
A single Analyze answers click is not necessarily a single LLM call.

## Basis, assumptions and limitations

This estimate follows the source call paths, rather than multiplying document words by a fixed
number. It does not use candidate records, generate real model responses or call a provider tokenizer.

- One job with 12 approved requirements; CVs contain roughly 1,000–1,500 English words over 2–3 pages.
- Three candidates proceed to interviews of roughly 20–30 minutes, with eight substantive answers each.
- Each interview has roughly 60–120 final transcript segments. Segment count depends on the STT
  boundaries, not just the number of questions.
- Each candidate receives one question-suggestion request, one task-ideas request, one selected-task
  draft and one practical correctness review.
- Each CV uses one extraction call, two matching batches, one audit and a recovery batch plus its
  audit: six calls in the worked example. Recovery is not inevitable for every CV.
- There are 12 central assistant turns and 9 private interview-assistant requests.
- Each interview is analyzed once with its finalized answers. Additional live/incremental analysis,
  repeated drafting, failed responses and manual retries are outside the base total.
- The visible-output allowances include structured JSON and evidence quotations, not just UI text.
- System instructions, repeated source context, tool definitions and structured-format overhead are
  allowed for in the input estimates. Exact provider accounting must be verified with usage metadata.
- Long CVs, long code submissions, larger reference sets, extensive history, non-English text and
  changed inputs can put usage outside these ranges.

Google gives roughly four characters per token as a general Gemini text heuristic, but the actual
model tokenizer is required for exact counts. See [Google's token-counting guide](https://ai.google.dev/gemini-api/docs/generate-content/tokens).
The ranges below are analyst-selected allowances based on the application's payload structure;
they are not experimental benchmarks.

## 1. Per-task token allowances

**Input and output columns are totals across the calls in that row, not per individual call.**
Feature rows exclude assistant routing/response overhead; add the relevant assistant row only
when the user invokes the feature through chat. This prevents counting the same overhead twice.

| LLM task | Unit | Successful calls | Input tokens | Visible output tokens |
| --- | --- | ---: | ---: | ---: |
| Central assistant overhead | Per chat turn, excluding the selected feature | 2 | 5,000–12,000 | 200–800 |
| Private interview assistant overhead | Per chat request; task selection is a separate direct action | 1 | 1,500–4,000 | 50–250 |
| JD relevance planning + draft | Per successful knowledge-first draft | 2 | 5,000–11,000 | 800–2,000 |
| AI-assisted JD edit | Per revision | 1 | 2,000–5,000 | 700–1,500 |
| Posting command interpretation | Per start/details/revision/approval message | 1 | 800–2,000 | 80–200 |
| CV extraction, matching, audit and recovery | Per new 2–3 page CV, 12 requirements | 4–7 | 15,000–35,000 | 2,000–5,000 |
| Scheduling / invitation interpretation | Per selection/details/confirmation/reschedule message | 1 | 1,500–5,000 | 100–400 |
| Question-bank suggestions | Per requested set of questions | 1 | 2,500–6,000 | 500–1,200 |
| Practical-task ideas | Per request for 2–3 choices | 1 | 2,000–5,000 | 400–1,000 |
| Selected practical-task draft | Per selected task | 1 | 2,000–5,000 | 600–1,400 |
| Practical correctness review + verification | Per short text/code submission | 2 | 4,000–12,000 | 300–1,200 |
| Transcript segment classification | Per finalized interview, 60–120 fresh segments | 1–2 | 6,000–12,000 | 3,000–7,000 |
| Answer analysis, mapping, evidence check and follow-ups | Per substantive answer, all four calls combined | 4 | 18,000–40,000 | 1,600–4,800 |

Counts describe a normal successful path, excluding retries. The question assistant can avoid its
feature-generation call when no relevant question-bank material exists. Unknown or unsuccessful
requests are not guaranteed to have the same usage as successful ones.

### Other paths and optional behavior

- **Profile-based JD generation:** an existing alternative API path uses one generation call,
  approximately 2,500–6,500 input and 800–1,500 output tokens. Treat it as an alternative to
  knowledge-first planning/drafting, not a mandatory additional stage.
- **JD clarification:** an insufficient-context request can use the planning call without generating
  a draft. A follow-up may repeat planning and retrieval before generation becomes possible.
- **Posting revisions and interview rescheduling:** each additional interpreted command incurs its
  feature call and, when requested in central chat, the central assistant overhead.
- **Assistant help, approval, synchronization and saved-result questions:** the business action may
  use no generation, but sending it through the assistant still incurs routing and, for central
  chat, a final response request.
- **Saved analysis requests in the private interview assistant:** one routing call may read existing
  results without another answer-analysis pass. Missing/stale results can queue new analysis.
- **Consolidated report fact prioritization:** a model-injection hook can select existing fact IDs
  with 1 call, approximately 2,000–5,000 input and 100–300 output tokens; a retry can add another.
  The current default routes/services do not supply this model, so this is **0 extra calls in the
  normal flow and in the worked example**. Reports/performance summaries normally use saved facts.
- **Practical task selected from a saved template or written manually:** no LLM draft is necessary.
  The later AI correctness review is still separate.

## 2. Why transcript analysis is the largest component

For each new, completed, substantive answer, the graph normally performs:

| Stage | Calls per answer | Input allowance | Output allowance |
| --- | ---: | ---: | ---: |
| Assess meaning and score four dimensions | 1 | 4,000–8,000 | 800–1,800 |
| Map answer evidence to job requirements | 1 | 4,000–9,000 | 200–800 |
| Independently validate citations, interpretation and score support | 1 | 6,000–14,000 | 300–1,000 |
| Generate evidence-triggered follow-ups | 1 | 4,000–9,000 | 300–1,200 |
| **Per-answer total** | **4** | **18,000–40,000** | **1,600–4,800** |

The example uses **24,000 input + 3,000 output = 27,000 tokens per answer**.
This is a rounded planning point within those ranges, not a tokenizer result.

For one eight-answer interview:

```text
Segment detection/classification:          9,000 input + 5,000 output = 14,000
Eight answers × four analysis stages:    192,000 input + 24,000 output = 216,000
Interview-analysis total:                201,000 input + 29,000 output = 230,000
```

That is **34 successful calls** in the example: two classification batches and 32 answer-stage calls.
The broad planning range for this interview is approximately **166,000–377,000 tokens** under the
per-stage assumptions, excluding assistant requests, practical work, retries and thinking.

The candidate does not need to say 230,000 tokens. Most input usage comes from resending context.
Later calls include earlier assessment/mapping results, original evidence, job requirements and
references; the independent validation payload can include findings in both targets and context.

Greeting/device-check exclusions, unanswered exchanges and failed stages can skip later calls.
Already accepted, compatible analyses can be reused. Their savings should not be assumed for new
or changed answers. Updating live answers repeatedly can cost more than one finalized pass.

## 3. Full-flow worked example

The following table applies one planning point to each task. The displayed arithmetic is exact for
these chosen allowances; the underlying allowances remain approximate.

| Stage | Quantity | Calls in example | Input tokens | Output tokens | Total tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| JD source selection and drafting | 1 | 2 | 7,500 | 1,500 | 9,000 |
| One AI-assisted JD edit | 1 | 1 | 3,500 | 1,200 | 4,700 |
| Posting command interpretation | 3 | 3 | 3,600 | 450 | 4,050 |
| CV screening with one recovery round | 10 | 60 | 220,000 | 35,000 | 255,000 |
| Scheduling / invitation command interpretation | 3 | 3 | 7,500 | 750 | 8,250 |
| Question-bank suggestions | 3 | 3 | 10,500 | 2,250 | 12,750 |
| Practical-task suggestions | 3 | 3 | 9,000 | 2,100 | 11,100 |
| Selected practical-task draft | 3 | 3 | 9,000 | 3,000 | 12,000 |
| Practical correctness review + verification | 3 | 6 | 18,000 | 1,800 | 19,800 |
| Transcript detection, two batches | 3 | 6 | 27,000 | 15,000 | 42,000 |
| Answer assessment + mapping + check + follow-ups | 24 | 96 | 576,000 | 72,000 | 648,000 |
| Central assistant routing and final response | 12 | 24 | 96,000 | 6,000 | 102,000 |
| Interview assistant routing | 9 | 9 | 18,000 | 900 | 18,900 |
| **Total** | | **219** | **1,005,600** | **141,950** | **1,147,550** |

The 12 central turns represent: draft JD, edit JD, approve JD, start posting, supply posting details,
approve posting, synchronize responses, start screening, select interview candidates, supply
schedule details, confirm invitations and request final ranking.

The 9 private interview-assistant requests are three per interviewed candidate: suggest questions,
suggest practical tasks and request answer analysis. Selecting a task creates its draft through a
separate direct action, already counted in the task-draft row, without another routing turn.

Chat overhead is separated from the underlying feature calls. For example, a successful JD draft
requested in central chat normally comprises two supervisor calls plus two drafting feature calls.

### Operational reserve

A 25% reserve adds approximately 287,000 tokens to the 1.15-million base, resulting in about
1.43 million. This is only an illustrative contingency—not a measured retry rate or an upper bound.
Repeated live analysis, long contexts or frequent failed validations can exceed it substantially.
Thinking tokens, when used by the configured model, must be accounted for separately.

## 4. Activities with no direct Gemini generation

| Activity | Direct Gemini tokens | Important distinction |
| --- | ---: | --- |
| Manual JD entry/editing or approval | 0 | AI editing or chat-mediated approval adds the relevant calls |
| Actual Discord publication | 0 | Command interpretation and assistant chat are separate |
| Google Sheet synchronization / Drive download | 0 | A central-chat request still has assistant overhead |
| PDF/DOCX text extraction and local OCR | 0 | Extracted text subsequently enters CV screening |
| Deterministic CV totals and ranking | 0 | Evidence matching/auditing already consumed tokens |
| Actual SMTP invitation / .ics creation | 0 | AI scheduling interpretation is separate |
| Room admission, joining and LiveKit media controls | 0 | LiveKit has a separate media-usage model |
| Consented speech recognition | 0 Gemini tokens | Deepgram receives audio; see the separate usage boundary below |
| Photo display and local face matching | 0 | No Gemini image or biometric embedding request |
| Practical autosave, countdown, submission and approval | 0 | AI draft and correctness review are separate |
| Candidate performance-summary formatting | 0 additional by default | Reuses saved analysis facts |
| Final 60% / 30% / 10% arithmetic and comparisons | 0 | Asking through chat still incurs supervisor overhead |
| Standard HTML/PDF report rendering and downloads | 0 | Default report consolidation does not regrade answers |
| Polling and reading unchanged saved results | 0 | A new assistant message is different from a normal API read |

### Embeddings and transcription are separate workloads

**Ollama / Nomic:** reference-document ingestion, private CV indexing and semantic queries consume
local embedding computation. Their tokenization is model-specific and must not be added to the
Gemini totals. New/changed documents need indexing; unchanged compatible indexes can be reused.
The local model has no generative answer-output token budget, but it still uses CPU/RAM/storage.

**Deepgram:** track actual audio streamed by the worker, not text-generation tokens. The example
contains 60–90 minutes of interview wall-clock time across three interviews. There are two
independent microphone streams, so that wall-clock figure is not automatically the provider's
processed or billable stream duration. Consult actual provider usage for the configured setup.

**LiveKit:** participant/media usage is also separate from Gemini tokens. No audio/video recording
or Gemini multimodal processing is part of this estimate.

## 5. Scaling the estimate to a different recruitment round

For a completed interview with eight answers, one question-suggestion request, one practical exercise
and three private assistant requests, the example's candidate-dependent interview bundle is:

```text
Transcript analysis                  230,000
Question suggestions                   4,250
Task suggestions                       3,700
Selected task draft                    4,000
Practical review + verification         6,600
Three private assistant routes         6,300
Total per interviewed candidate       254,850 tokens
```

Using the same rounded allowances:

```text
T ≈ 25,500 × N
   + I × (14,000 + 27,000 × Q + 24,850)
   + 8,500 × A
   + J

N = new CVs screened
I = interviews with the complete bundle above
Q = substantive answers assessed per interview
A = central assistant turns
J = feature-specific job-round work: JD drafting/editing and interpreted posting/scheduling commands
```

For the worked example, N=10, I=3, Q=8, A=12 and J=26,000 produce 1,147,550 tokens.
Adjust J and the interview bundle when the number of job drafts, commands, exercises or assistant
requests changes. Do not apply this formula blindly to longer CVs, more requirements or longer
answers: those change the per-unit input sizes and may add matching/classification batches.

For CVs with R requirements, the first-pass call count is approximately
**1 extraction + ceil(R/6) matching calls + 1 audit**. If S requirements enter recovery, add
**ceil(S/6) recovery matching calls + 1 recovery audit**. Provider retries are additional.
With 12 requirements this gives four first-pass calls, or six/seven with a recovery round.

## 6. Turning the estimate into measured usage

Google's [token-counting guide](https://ai.google.dev/gemini-api/docs/generate-content/tokens) describes
preflight input counting and response usage metadata. Input, visible output, thinking and cached
input should be kept separate. Cached input is not an additional quantity to add again to an
already inclusive input total.

The current structured client reads the generated result and model revision but does not persist
a full token-usage ledger. Supervisor call usage is likewise not aggregated into a project ledger.
Therefore saved scores or conversation counts alone cannot establish exact historical usage.

A future instrumentation change should capture provider-reported usage for every call, including
supervisor routing/final responses and feature calls. Record stage, model revision, input/output/
thinking tokens, cache counts, attempt number, request ID and a non-sensitive workflow identifier.
Do not log complete candidate prompts or secrets merely to measure usage.

Use provider-reported totals and their documented field semantics rather than assuming
input + visible output always equals all generated usage. Failed requests may not return complete
usage metadata, so reconcile with the provider's usage dashboard. Application result reuse,
provider prompt caching and provider thinking are different mechanisms.

This document does not add that instrumentation or make any generation/countTokens requests.
It estimates runtime usage; it does not estimate the tokens spent developing the project.

## Source map

- [Supervisor routing and response calls](../backend/app/agents/supervisor.py)
- [Direct JD planning and drafting](../backend/app/agents/direct_job_description.py)
- [Profile-based JD generation and editing](../backend/app/agents/job_description.py)
- [Posting command interpretation](../backend/app/agents/job_posting.py)
- [CV matching batches, audit and recovery](../backend/app/screening/ai.py)
- [Scheduling command interpretation](../backend/app/agents/interview_commands.py)
- [Question suggestions and interview routing](../backend/app/services/interview_copilot.py)
- [Transcript call stages and bounded retries](../backend/app/agents/interview_analysis.py)
- [Practical-task generation](../backend/app/agents/work_sample.py)
- [Practical evaluation and verification](../backend/app/agents/practical_scoring.py)
- [Optional report fact-selection hook](../backend/app/assessments/workflow.py)
- [Default report processing without an extra model](../backend/app/services/assessment_service.py)
- [Structured Gemini response handling](../backend/app/llm/gemini.py)

