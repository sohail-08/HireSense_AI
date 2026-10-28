# Interviewer accounts and candidate links

Only the interviewer signs in with email/password. The configured interviewer is
provisioned by the existing seed process; there is no public account-registration
endpoint or signup form. `/api/auth/register` is absent from the API/OpenAPI schema.
`/api/auth/login` issues a JWT only for an active interviewer, and `/api/auth/me`
requires interviewer access. Existing password checks, token expiry, seeded-account
uniqueness and interviewer authorization are unchanged.

Candidates use the private link in their invitation (`/interview/join/:token`).
The link is exchanged for the existing HttpOnly candidate-room cookie, not a user
account/JWT. Device setup, consent, waiting-room admission, interview participation,
and practical-task submission remain account-free. Invalid/expired/revoked links,
origin checks, rate limits, candidate privacy and room authorization are unchanged.

The frontend no longer includes a signup page, candidate account dashboard or
candidate account navigation. Old `/register` and `/candidate/*` bookmarks redirect
to the interviewer login page, which contains only interviewer sign-in guidance.
They do not redirect into a public candidate dashboard. Legacy
candidate JWTs are not restored as web sign-ins; a candidate response from an older
server is also rejected and its stored web token cleared.

No database migration or record deletion is performed. Historical user roles and
rows remain for compatibility; applications, CVs, candidate profiles, schedules,
photos, interview sessions and assessment history are preserved. The three removed
frontend account/signup source files remain recoverable through Git history.

Regression tests use synthetic accounts and isolated databases. They cover removal
of signup, denial of legacy candidate sign-in, interviewer sign-in/role guards,
public candidate join routes, and the real link-cookie/admission/media workflow
with mocked providers. No real invitation, provider request or candidate record is
needed to verify the change.
