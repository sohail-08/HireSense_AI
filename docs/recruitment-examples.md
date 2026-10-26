# Local recruitment examples

This is an explicit, offline, idempotent database population tool, not automatic
startup data and not a production evaluation. The ordinary UI shows candidate
names, jobs and reports without extra fixture badges.

```powershell
docker compose exec -T backend python -m scripts.seed_recruitment --apply
```

It uses the existing active interviewer and adds separate **Backend Engineer** and
**HR Executive** postings with five applications. Each includes a downloadable
one-page CV, source-linked screening, deterministic CV scoring, a completed
interview and transcript, answer guides, authored saved answer judgments, one
12-minute practical submission and approved correctness review, a consolidated
performance report, and a final 60/30/10 ranking. Scores are calculated using the
app's existing calculators. Re-running does not duplicate these applications,
files, reports or unchanged ranking versions. PostgreSQL runs are serialized
using a dedicated session-level advisory lock. An interrupted run can resume.

Names, contact addresses, CVs, transcripts and judgment scenarios are fictional.
Email addresses use the reserved `example.test` domain. Private metadata includes
`fixture_seed=recruitment-explorer-v1`; practical model provenance is
`authored-fixture-v1`, not a claim that Gemini evaluated a real candidate. This
distinction must be retained in any evaluation/export or use outside local
demonstration. No score demonstrates model accuracy.

No emails, delivery records, external Discord publications, external URLs to a
real post, paid model calls, real-person photos, biometric consent or camera-match
results are generated. The postings are locally published manual records. Missing
photo verification correctly stays unverified; identity confirmation is never
invented merely to fill a screen. All examples complete the assessment/ranking
flow independently of optional face matching.

Existing records/accounts/settings are not modified. Ordinary app deletion can
remove these example applications and jobs. Keep the provenance identifiers if
writing a cleanup tool; do not delete by name/email alone. CV files follow normal
private document storage and deletion rules. Transcripts and practical evidence
retain the normal 30-day availability window, after which reports may expire.
