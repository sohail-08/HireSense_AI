"""Explicit opt-in local database examples; no providers, email or Discord calls."""
import argparse
import json
from sqlalchemy import select, text
from app.database import engine, SessionLocal
from app.models.user import User, UserRole
from app.models.job import RequirementProfile, JobDescription, JobPosting
from app.models.candidate import Candidate, CandidateApplication, CVDocument
from app.agents.interview_analysis import digest
from app.services.preview_seed import seed_recruitment, SEED


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Required: persist the authored local recruitment examples")
    args = parser.parse_args()
    if not args.apply:
        parser.error("Nothing was written. Pass --apply to seed this configured database.")
    with engine.connect() as guard:
        locked = False
        try:
            if engine.dialect.name == "postgresql":
                locked = bool(guard.scalar(text("SELECT pg_try_advisory_lock(681274092724)")))
                guard.commit()
                if not locked: raise RuntimeError("Another recruitment seed is running")
            with SessionLocal() as db:
                owner = db.scalar(select(User).where(User.role == UserRole.INTERVIEWER, User.is_active.is_(True)))
                if not owner: raise RuntimeError("Sign in/create the interviewer account before seeding")
                models = (User, RequirementProfile, JobDescription, JobPosting, Candidate, CandidateApplication, CVDocument)
                existing = {model: {row.id: digest({c.name: getattr(row, c.name) for c in model.__table__.columns})
                    for row in db.scalars(select(model))} for model in models}
                result = seed_recruitment(db, owner.id, session_factory=SessionLocal)
                db.expire_all()
                for model, records in existing.items():
                    for row_id, checksum in records.items():
                        row = db.get(model, row_id)
                        if not row or digest({c.name: getattr(row, c.name) for c in model.__table__.columns}) != checksum:
                            raise RuntimeError("An existing record changed during seeding; inspect concurrent activity")
                print(json.dumps({"seed": SEED, "jobs": result, "external_actions": 0,
                    "preserved_existing_records": sum(len(r) for r in existing.values())}))
        finally:
            if locked:
                guard.execute(text("SELECT pg_advisory_unlock(681274092724)")); guard.commit()


if __name__ == "__main__":
    main()
