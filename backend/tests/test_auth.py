import os
from datetime import datetime, timedelta, timezone

# Test-only configuration must be set before importing app modules.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET_KEY"] = (
    "test-only-jwt-secret-key-with-at-least-32-characters"
)
os.environ["INTERVIEWER_EMAIL"] = "interviewer@hiresense.com"
os.environ["INTERVIEWER_PASSWORD"] = (
    "TestInterviewerPassword123!"
)

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.database import Base, get_db
from app.models.user import User, UserRole
from app.routes.auth import router
from app.security import hash_password, require_interviewer
from app.seed_interviewer import seed_interviewer


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(engine)

    sessions = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    with sessions() as db:
        seed_interviewer(db)

    def test_db():
        with sessions() as db:
            yield db

    test_app = FastAPI()
    test_app.include_router(router)
    test_app.dependency_overrides[get_db] = test_db

    @test_app.get("/interviewer-only")
    def interviewer_only(
        user=Depends(require_interviewer),
    ):
        return {"role": user.role}

    with TestClient(test_app) as test_client:
        yield test_client, sessions

    engine.dispose()


def register_candidate(api, **overrides):
    return api.post(
        "/api/auth/register",
        json={
            "name": "Candidate One",
            "email": "candidate@example.com",
            "password": "CandidatePassword123!",
            **overrides,
        },
    )


def login(
    api,
    email="candidate@example.com",
    password="CandidatePassword123!",
):
    return api.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )


def test_registration_creates_candidate_and_hashes_password(
    client,
):
    api, sessions = client

    response = register_candidate(api)

    assert response.status_code == 201
    assert response.json()["role"] == "candidate"
    assert "password_hash" not in response.json()

    with sessions() as db:
        user = db.scalar(
            select(User).where(
                User.email == "candidate@example.com"
            )
        )
        assert user.password_hash != "CandidatePassword123!"


def test_duplicate_email_is_case_insensitive(client):
    api, _ = client

    register_candidate(api)

    response = register_candidate(
        api,
        email="CANDIDATE@example.com",
    )

    assert response.status_code == 409


def test_client_cannot_choose_role(client):
    api, _ = client

    response = register_candidate(api, role="interviewer")

    assert response.status_code == 422


def test_seed_email_cannot_be_registered(client):
    api, _ = client

    response = register_candidate(
        api,
        email="interviewer@hiresense.com",
    )

    assert response.status_code == 409


def test_login_and_me(client):
    api, _ = client

    register_candidate(api)

    response = login(api)

    assert response.status_code == 200

    token = response.json()["access_token"]

    me = api.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert me.status_code == 200
    assert me.json()["role"] == "candidate"


def test_wrong_password(client):
    api, _ = client

    register_candidate(api)

    response = login(api, password="WrongPassword123!")

    assert response.status_code == 401


@pytest.mark.parametrize("token", [None, "invalid-token"])
def test_me_rejects_missing_or_invalid_token(client, token):
    api, _ = client

    headers = (
        {"Authorization": f"Bearer {token}"}
        if token
        else {}
    )

    assert api.get(
        "/api/auth/me",
        headers=headers,
    ).status_code == 401


def test_me_rejects_expired_token(client):
    api, _ = client

    now = datetime.now(timezone.utc)

    token = jwt.encode(
        {
            "sub": "1",
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(hours=1),
            "iss": "hiresense",
            "aud": "hiresense-web",
        },
        get_settings().jwt_secret_key.get_secret_value(),
        algorithm="HS256",
    )

    response = api.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


def test_backend_role_guard(client):
    api, _ = client

    register_candidate(api)

    token = login(api).json()["access_token"]

    response = api.get(
        "/interviewer-only",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403

    token = login(
        api,
        "interviewer@hiresense.com",
        "TestInterviewerPassword123!",
    ).json()["access_token"]

    response = api.get(
        "/interviewer-only",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200


def test_inactive_user_cannot_reuse_token(client):
    api, sessions = client

    register_candidate(api)

    token = login(api).json()["access_token"]

    with sessions() as db:
        user = db.scalar(
            select(User).where(
                User.email == "candidate@example.com"
            )
        )

        user.is_active = False
        db.commit()

    response = api.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


def test_seed_is_idempotent(client):
    _, sessions = client

    with sessions() as db:
        first = seed_interviewer(db)
        second = seed_interviewer(db)

        assert first.id == second.id

        interviewers = db.scalars(
            select(User).where(
                User.role == UserRole.INTERVIEWER
            )
        ).all()

        assert len(interviewers) == 1


def test_database_rejects_second_interviewer(client):
    _, sessions = client

    with sessions() as db:
        db.add(
            User(
                name="Second Interviewer",
                email="second@example.com",
                password_hash=hash_password(
                    "AnotherPassword123!"
                ),
                role=UserRole.INTERVIEWER,
            )
        )

        with pytest.raises(IntegrityError):
            db.commit()

        db.rollback()