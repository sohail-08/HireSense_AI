from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.user import User, UserRole


password_hasher = PasswordHash.recommended()
bearer = HTTPBearer(auto_error=False)

# Used when an email does not exist, so password verification
# still takes place before returning the generic login error.
DUMMY_HASH = password_hasher.hash(
    "dummy-password-not-an-account"
)


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(
    password: str,
    password_hash: str,
) -> bool:
    return password_hasher.verify(password, password_hash)


def create_access_token(user_id: int) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)

    return jwt.encode(
        {
            "sub": str(user_id),
            "iat": now,
            "exp": now + timedelta(
                minutes=settings.access_token_expire_minutes
            ),
            "iss": "hiresense",
            "aud": "hiresense-web",
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm="HS256",
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(
        bearer
    ),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise unauthorized

    try:
        payload = jwt.decode(
            credentials.credentials,
            get_settings().jwt_secret_key.get_secret_value(),
            algorithms=["HS256"],
            issuer="hiresense",
            audience="hiresense-web",
            options={
                "require": ["sub", "exp", "iat", "iss", "aud"]
            },
        )

        user_id = int(payload["sub"])

    except (InvalidTokenError, ValueError, TypeError):
        raise unauthorized from None

    user = db.get(User, user_id)

    if user is None or not user.is_active:
        raise unauthorized

    return user


def require_interviewer(
    user: User = Depends(get_current_user),
) -> User:
    if user.role != UserRole.INTERVIEWER:
        raise HTTPException(
            status_code=403,
            detail="Interviewer access required",
        )

    return user
