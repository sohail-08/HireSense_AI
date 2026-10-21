# Evidence-grounded semantic CV screening

## What changed

Screening finds meaning-based evidence rather than converting keyword counts or
embedding similarity into a hiring score. The interviewer still chooses the same
three CV category weights. Accepted outcomes remain Met (1), Partially met (0.5),
and Unmet (0). There is no manual-review gate.

1. Validate file integrity and parse PDF/DOCX source blocks. Image-only pages fail
   safely instead of being silently omitted. This implementation does not add OCR.
2. Split long blocks into overlapping, exact source passages (900 characters,
   120 overlap), preserving original block IDs and offsets. No content is silently
   truncated. Complexity is bounded to 512 passages and 60 requirements per CV.
3. Store private 768-dimensional CV embeddings in `cv_passages` (pgvector), not
   in the shared previous-JD/question knowledge base. Retrieval filters by CV
   document, file hash, and encoder revision before ordering by cosine distance.
   Exact search is intentional: the candidate-local corpus is small and stable.
4. Retrieve by semantic relevance and lexical relevance, combine ranks, and add
   neighbouring passages for context. Nomic uses `search_document:` and
   `search_query:` prefixes. Similarity is a retrieval signal, not numeric credit.
5. Gemini matches approved requirements against passages using a fixed rubric.
   It selects passage IDs; the backend constructs quotations and character spans
   from stored text. It cannot write an invented quotation into accepted evidence.
6. Audit the meaning of the match against the actual CV. For rejected, malformed,
   or Unmet findings, perform at most one recovery pass against the full parsed
   CV, then audit again. Missing/duplicate responses or persistently invalid
   source references fail processing instead of manufacturing Unmet scores.
7. Compute relevant experience from source-backed dates, merging overlapping
   employment months and ignoring unsupported/future ranges. The model selects
   relevant employment records; application code calculates duration. Incomplete
   dates do not receive invented precise years. Present roles use a frozen
   evaluation month, shown in processing metadata. Date precision is monthly;
   year-only dates count only the intervening complete years as a conservative
   lower bound. The current incomplete month is not counted for ongoing roles.
   Zero years means no minimum, so it is not turned into an artificial scored
   requirement. A category without requirements must have 0% weight, redistributed
   explicitly through the existing weight approval controls.
8. Persist accepted requirement matches, then apply the existing exact weighted
   scoring formula. Changing weights does not run the language model again.

## Rubric

Met requires all explicitly requested conditions to be demonstrated. Partial
requires relevant evidence of some but not all conditions. Unmet means the
criterion is not demonstrated by the CV, not that the person lacks the ability.

Do not add hidden professional-experience requirements to a plain skill criterion.
A skills-list claim can satisfy a plain named-skill criterion, but cannot prove
professional use, proficiency, production delivery, or years of experience.
Exact single-name entries in labelled skills lists (for example `Skills: React`)
use a backend rule for a plain `React` requirement with no extra conditions.
Negated claims, multiword criteria, or requirements with additional details still
use semantic evaluation. This prevents the model from inventing proficiency or
professional-use conditions; it does not prove the candidate's skill in practice.
The decision rule and source quotation are retained in the processing trace.
For applied skills, hands-on coursework or personal-project practice can receive
Partial when the requested production/professional context is missing; a bare
skills-list claim is not hands-on practice. The reasoning must say what is
demonstrated and what is missing. This does not turn a lower degree or course
into partial proof of a specifically required higher degree.
Equivalent meanings count (Django REST work supports Python web development).
Merely related technologies are not interchangeable when a specific one is
required (Angular is not React). Lower degrees do not automatically satisfy a
higher degree; equivalences must be explicitly allowed by the approved criterion.
An independent audit still rejects unsupported conclusions.

## Stable results and honest failures

The evidence screen presents a short plain-language reason and up to four
distinct, relevant source excerpts per requirement. Recorded experience months
are expressed in years/months, without recalculating against today's date.
Excerpts are exact contiguous slices of saved quotations; omitted text is marked.
The original passages remain available under **View full source passages**.
This is read-time presentation only: existing rankings update on refresh without
rescoring, changing weights, rewriting evidence, or making new model calls.
Older screenings without a saved duration use a general explanation rather than
inventing an experience total.

The engine identity includes the configured model, prompt/schema hashes, parser
package versions, rubric/passage/retrieval versions, retrieval settings, encoder
model digest, evaluation month, and the explicit policy revision. File metadata
changes that leave parsed text and source layout unchanged reuse matching results.

Completed evaluations can be copied only within the same owned job posting and
identical source content/requirements/engine identity. Target application and CV
IDs remain separate, and copied quotations are checked against target passages.
Changing these inputs creates a new evaluation rather than overwriting history.
Per-job row locking protects the short cache-claim transaction, not provider calls.
Concurrent identical work is rejected with a retry message rather than evaluated
twice. Unexpected provider/database errors do not disclose private payloads.

Scanned, missing, corrupt, or failed CVs are not assigned zero scores or numerical
ranks by the screening/scoring services. Successful candidates in a mixed batch
can still be scored. The UI explains which CVs failed, with optional details.
This is a processing error state, not a fourth requirement outcome.

Hosted models are not mathematically deterministic. Reuse freezes validated
decisions; it does not prove their accuracy. Use explicit hosted model revisions
when available. The provider-reported model version is recorded, and mixing
reported revisions within an evaluation fails safely. If a cloud alias's policy
changes, deliberately increment `SCREENING_ENGINE_REVISION`. The local embedding
alias is resolved to its actual digest and checked while embedding.

Deleting an application removes its private passages as well as existing screening,
score, transcript, and report data through the existing deletion workflow. No
private CV passages are exposed through the shared knowledge search endpoint.

## Configuration and upgrades

Existing `OLLAMA_*` and `GEMINI_*` settings are reused. New optional settings:

```ini
SCREENING_EVIDENCE_TOP_K=6
SCREENING_ENGINE_REVISION=semantic-evidence-v1
SCREENING_REQUEST_INTERVAL_SECONDS=4.1
```

Migration: `0023_cv_semantic_evidence`. It adds private passages and screening
fingerprint/metadata columns; it does not delete or recalculate existing scores.
After upgrading, open Assessments and use **Save weights & rank candidates** once
to screen with the new rules. Old successful results remain in history.

Screening requests are paced within each backend process. Transient HTTP failures
have at most three attempts; a long provider quota wait or authentication failure
stops the batch rather than repeatedly calling the provider for every CV. This is
not a substitute for a shared rate limiter when running multiple backend workers.
Adjust the request interval to the limits of your own Gemini account. Retry after
fixing the service issue; unprocessed CVs are never given a fabricated zero.

The existing five-node screening graph keeps its actual nodes/edges:
`retrieve_validate_extract_text → extract_structured_profile → match_requirements
→ validate_evidence → persist_result`. Passage retrieval occurs in the first node;
bounded recovery occurs in `validate_evidence`. No diagram-only nodes were added.

## Testing and calibration

`tests/test_semantic_screening.py` checks quotation ownership, missing evidence,
bounded recovery, rejected conclusions, isolation, model digest changes, exact
passage boundaries, non-overlapping dates, cache invalidation and deletion. These
are mocked-provider regression tests, not claims of real-model accuracy.

`tests/fixtures/cv_semantic_benchmark.json` contains 20 synthetic, labelled cases
covering equivalent meanings, explicit technology mismatch, negation, skill-only
claims, qualifications, prompt injection, and relevant/overlapping experience.
The labels are a starting calibration policy; have the interviewer validate and
expand them. Never commit real candidate CVs or private benchmark data.

From `backend`, live evaluation is explicit and uses provider quota:

```powershell
.venv/Scripts/python.exe scripts/benchmark_cv_screening.py --live --limit 20
```

Read previously recorded metrics without provider calls:

```powershell
.venv/Scripts/python.exe scripts/benchmark_cv_screening.py --predictions ../output/cv-screening-benchmark.json
```

The script uses an isolated in-memory SQLite database and synthetic text only,
never business records. It reports accuracy, macro F1, processing errors, and
duration. A four-case smoke run is not evidence that all twenty cases, real CVs,
or a batch of twenty candidates meet accuracy/throughput targets. Benchmark those
separately before a production deployment. No perfect accuracy guarantee is made.

### Validation snapshot (20 October 2026)

The final live synthetic run graded all 20 cases: 19 agreed with the labels
(95% accuracy, macro F1 0.9111), with zero processing errors. The remaining
mismatch was a bare skills-list claim receiving Partial for a professional-use
criterion whose label was Unmet. This remains a calibration limitation of model
judgment, not proof of professional experience. Earlier runs also showed why
explicit rubrics, literal rules, and saved-result reuse matter: hosted decisions
can vary. Do not interpret this small calibration set as real-CV accuracy or
twenty-candidate throughput. Expand the labelled evaluation before production.

Results are saved under ignored `output/cv-screening-benchmark-validated.json`.
The actual PostgreSQL `vector(768)` retrieval/isolation probe also passed, with
all synthetic inserts rolled back. No real candidates were rescored during these
checks. Existing CV category weights and the CV/interview 50/50 final weighting
were preserved; historical scores were not overwritten.

To verify the actual PostgreSQL vector operator and CV-local scope after upgrading:

```powershell
docker compose exec -T backend python scripts/check_cv_pgvector.py --run
```

This uses two existing CV IDs only as foreign keys, synthetic text, and local
Ollama calls. All temporary passage inserts are rolled back; existing CV text and
screening results are untouched. The script refuses to run without `--run`.

Primary API references: [Ollama embeddings](https://docs.ollama.com/api/embed),
[model digests](https://docs.ollama.com/api/tags), and
[Nomic task prefixes](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5).
