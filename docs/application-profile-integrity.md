# Application profiles and repeated form submissions

An email typed into a form is not a verified global identity. Each imported form
application now owns its candidate profile. A new submission never overwrites
another application's name, phone, links or location, even when email addresses
are identical. Re-sync updates only the matching application's profile. Shared
historical profiles are detached before updating; attached CV records follow the
correct application. A moved sheet row cannot replace another person's stored
submission merely because its row number was reused.

Current candidate lists, screening cohorts, CV rankings and final-ranking cohorts
use the same conservative repeat rule: the same job, normalised full name, valid
email, identical CV file fingerprints and disposition. Different
names, emails, jobs or CV versions are never collapsed. Blank/invalid
identities and missing CVs remain separate. Applications with interviews or active
biometric data are protected; separate independently actioned applications are
not merged. When no activity exists, the latest submission supplies current contact details.

Grouping does not delete or rewrite original form responses, CV files, submissions,
scores, transcripts or interview links. Retained repeats have private grouping
metadata; deleting the visible anchor does not cause old grouped rows to reappear.
Existing historical scoring snapshots remain immutable. Recalculation creates a
new, correctly named, repeat-filtered CV ranking using the existing approved
weights and evidence. Different people who supplied identical CV content can
still legitimately receive equal scores; scores are not varied artificially.

## Repair existing profiles

First end active interviews and resolve pending deliveries/background assessments.
The repair reads saved form responses, not external Google data. It is owner-scoped
and leaves direct-upload and locally authored example records untouched.

```powershell
docker compose exec -T backend python -m scripts.repair_application_profiles
docker compose exec -T backend python -m scripts.repair_application_profiles --apply
```

The first command is a dry run. The second restores profiles, updates per-application
CV ownership and writes private repair/grouping metadata. Original submissions and
file hashes remain unchanged. Missing original identities are reported for manual
review, never invented. Existing biometric matches are invalidated if a name/email
was corrected, and affected templates require re-enrollment. A Google re-sync can
prepare a new photo copy, but explicit in-app consent is still required.

The CLI refreshes CV rankings and existing consolidated reports using deterministic
calculators and already-saved assessments; no model calls, invitations or Discord
publications occur. Previous reports remain immutable and become stale after an
identity correction. Existing final-ranking comparisons also become stale when
their source identity or cohort changes; use the app's normal recalculation flow
for a new comparison. Re-running the repair is idempotent.
