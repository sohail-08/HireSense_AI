# F7: Candidate identification and profile overview

Photo verification is optional, one-to-one comparison with the photo attached to
the expected application. It does not search a face database, prove legal identity,
detect cheating, continuously monitor the interview, or change assessment scores.
Final weights remain interview 60%, CV 30%, practical 10%.

## Setup and use

1. Add the optional Google Form image-upload question **Candidate photo**. No
   Google Form biometric-consent question is needed. Restrict uploads to one JPG
   or PNG. Share the upload folder/files with the existing Google service account
   as a viewer, as well as the linked response spreadsheet. Existing read-only
   Sheets/Drive scopes are sufficient; do not make applicant photos public.
2. Run normal application sync. An encrypted, metadata-stripped processing copy
   is attached to the application, not to a name or a globally shared email.
   Old rows can be backfilled on re-sync. Missing/unreadable photos do not block CV
   intake. A changed form email cannot silently replace another application's photo.
3. Provision the local models explicitly, from `backend`:

   ```powershell
   .\.venv\Scripts\python.exe -m app.identity.provision
   ```

   In Docker use `docker compose exec -T backend python -m app.identity.provision`.
   Runtime inference never downloads files. The provisioner pins and verifies
   YuNet and SFace SHA-256 hashes and stores their licence notices alongside them.
4. Rebuild the web services and apply Alembic revision `0027_candidate_identity`
   through the normal backend entrypoint. Existing candidates are not enrolled
   by the migration. Keep the existing private storage mount persistent.
5. On the candidate's private pre-interview page, the checkbox starts unchecked.
   **Allow photo verification** records the current notice and consent, then
   prepares an encrypted face template locally. No template is created before
   this app consent. **Continue without face matching** provides the manual path.
6. Once admitted and joined with camera enabled, the app reuses the existing
   LiveKit local camera track to send three temporary JPEG samples. It does not
   open another camera, record video, or save those samples. The backend compares
   all three samples to the application's template using local CPU inference.
7. The interviewer sees an explicit matched/unverified/manual/missing/declined
   status next to the scheduled candidate profile, saved CV score and CV-backed
   areas to explore. A manual confirmation requires a note and a joined candidate;
   it is labelled separately from a photo match. Unclear results never reject a
   candidate, block an interview, or award/deduct marks.
   Match outcomes, similarity values, thresholds, check timestamps and manual
   notes are interviewer-only, including at the API boundary. Candidates see
   only consent, capture availability and a neutral submission acknowledgement.
   They retain access to the privacy notice, decline/withdrawal controls and
   camera recapture where available; no outcome is revealed after recapture.

## Privacy and security

- Reference photos and templates are Fernet-encrypted using an independent key.
  Set `IDENTITY_ENCRYPTION_KEY` to a valid Fernet key, or keep the automatically
  created private `storage/identity-secrets/template.key` with the persistent
  storage volume. Back up the key securely with the database; losing it makes
  existing templates unreadable. Never commit or publicly serve the key, photos,
  templates or model storage. Do not rotate a key without a re-enrollment plan.
- Encrypted processing photos are deleted after template extraction, including
  failed extraction. Photos/templates expire after 30 days or 7 days after the
  completed interview, whichever comes first. The maintenance worker also handles
  pending-consent photos. `IDENTITY_RETENTION_DAYS` and
  `IDENTITY_POST_INTERVIEW_DAYS` control these limits.
- Withdrawal deletes this app's photo/template and invalidates the check. Sheet
  re-sync cannot undo withdrawal. Deleting the application removes its identity
  records. Original Google Drive uploads and backups remain under the form
  owner's retention/deletion policy; HireSense's read-only integration cannot
  delete those originals. Audit status/timestamps are separate from biometric
  templates.
- Candidate routes use scoped interview cookies, origin checks and no-store
  responses. Verification requires admission, live consent, current session,
  current join/reference generations and optimistic version checks. Revocation,
  leaving, expiry, withdrawal and reference changes prevent reuse of a match.
  In-flight inference is rechecked before any result is persisted.
- JPG/PNG input, dimensions, file bytes and request body sizes are bounded. Face
  count, lighting, sharpness and minimum face size are checked. No demographic,
  emotion or personality inference is performed. No candidate image or embedding
  is sent to Gemini; candidates never receive embeddings or numerical similarity.
- `IDENTITY_ENABLED=false` disables enrollment and verification. Missing models,
  invalid encryption keys and inference failures produce an unavailable state,
  never a positive match. Model versions are bound to templates.

## Limits and verification

The default cosine threshold is `0.5`; it is not a calibrated probability or a
production accuracy guarantee. Validate false-match and false-nonmatch rates on
consented, representative data and review local requirements before real use.
Self-uploaded photos do not establish a person's official identity. Three samples
are **not liveness detection**: replay, substituted client frames or synthetic
media can still bypass this mechanism. Prefer manual verification when uncertain.

Automated tests cover consent, encryption, no pre-consent inference, admission,
match/unclear outcomes, ownership, request bounds, stale results, withdrawal,
expiry and manual fallback. Local model loading and blank-image rejection are
checked separately. No unattended real-person webcam test is claimed.

The optional PostgreSQL regression includes a pre-existing vector-search test
whose assertion requires the planner to choose HNSW even for a three-row table.
It also fails on the unchanged pre-feature container; no RAG query or index was
changed for this feature. The new identity/seed PostgreSQL checks pass separately.

Primary model sources:
[OpenCV model collection](https://github.com/opencv/opencv_zoo),
[OpenCV face comparison tutorial](https://docs.opencv.org/4.x/d0/dd4/tutorial_dnn_face.html).
