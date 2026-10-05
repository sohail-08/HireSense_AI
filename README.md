# HireSense

## Current milestone

- Candidate-only registration
- Email/password sign-in
- JWT authentication
- One seeded Interviewer account
- Role-based dashboards and navigation
- Persistent PostgreSQL storage
- Alembic-managed database migrations
- Private named-volume foundation for candidate documents

## Requirements

Docker Desktop running with Linux containers.

## Startup

1. Copy `.env.example` to `.env`.
2. Set your own database password, JWT secret and interviewer password.
3. Run:

```powershell
docker compose up --build
```

Application: http://localhost:5173
API documentation: http://localhost:8000/docs
Health check: http://localhost:8000/api/health

The backend runs migrations and seeds the Interviewer automatically.
All public registrations create Candidates.

On startup, the backend runs `alembic upgrade head` before starting FastAPI.
The first migration creates the existing authentication schema on a clean
database and adopts the existing `users` table when upgrading a database that
was created by the original development milestone.

## Tests

```powershell
docker compose exec backend python -m pytest -q
```

The migration and storage tests also run against isolated SQLite databases.

Tests use isolated SQLite databases and do not modify PostgreSQL.

## Stop

```powershell
docker compose down
```

Database data persists in the named Docker volume.

Do not use `docker compose down -v` unless you intend to delete the database.

## Notes

- Changing INTERVIEWER_PASSWORD after the first startup does not change
  the existing account's password.
- Database changes must be introduced through Alembic migrations.
- Candidate documents will be stored under the private `private_storage`
  Docker volume. Do not place CVs, credentials or exported candidate data in
  the repository.
- JWTs use sessionStorage for this local milestone.
- Logout removes the browser session but does not revoke a previously
  issued token. Tokens expire after their configured lifetime.
- Before public deployment, add HTTPS, rate limiting, password reset
  and a reviewed session/token-revocation design.
- Copilot and recruitment features are deferred.
