from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.models.user import User, UserRole
from app.security import hash_password


def seed_interviewer(db: Session) -> User:
    settings = get_settings()
    email = str(settings.interviewer_email).lower()

    existing = db.scalar(
        select(User).where(
            User.role == UserRole.INTERVIEWER
        )
    )

    if existing:
        if existing.email != email:
            raise RuntimeError(
                "Existing interviewer email differs "
                "from configuration"
            )
        return existing

    if db.scalar(select(User).where(User.email == email)):
        raise RuntimeError(
            "Configured interviewer email belongs "
            "to another account"
        )

    user = User(
        name=settings.interviewer_name,
        email=email,
        password_hash=hash_password(
            settings.interviewer_password.get_secret_value()
        ),
        role=UserRole.INTERVIEWER,
    )

    db.add(user)

    try:
        db.commit()

    except IntegrityError:
        db.rollback()

        # Another backend startup may have seeded it first.
        existing = db.scalar(
            select(User).where(
                User.role == UserRole.INTERVIEWER
            )
        )

        if existing and existing.email == email:
            return existing

        raise

    db.refresh(user)
    return user


if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        seed_interviewer(db)

    print("Interviewer account is ready.")