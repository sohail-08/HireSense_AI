from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Response,
    status,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
)
from app.schemas.user import UserResponse
from app.security import (
    DUMMY_HASH,
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)


router = APIRouter(
    prefix="/api/auth",
    tags=["Authentication"],
)


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    data: RegisterRequest,
    db: Session = Depends(get_db),
):
    email = str(data.email).lower()

    # Reserve the configured interviewer email.
    if email == str(get_settings().interviewer_email).lower():
        raise HTTPException(
            status_code=409,
            detail="This email is unavailable",
        )

    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(
            status_code=409,
            detail="This email is already registered",
        )

    user = User(
        name=data.name,
        email=email,
        password_hash=hash_password(data.password),
        role=UserRole.CANDIDATE,
    )

    db.add(user)

    try:
        db.commit()

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This email is unavailable",
        ) from None

    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(
    data: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    user = db.scalar(
        select(User).where(
            User.email == str(data.email).lower()
        )
    )

    valid = verify_password(
        data.password,
        user.password_hash if user else DUMMY_HASH,
    )

    if user is None or not valid or not user.is_active:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password",
        )

    response.headers["Cache-Control"] = "no-store"

    return TokenResponse(
        access_token=create_access_token(user.id),
        expires_in=(
            get_settings().access_token_expire_minutes * 60
        ),
    )


@router.get("/me", response_model=UserResponse)
def me(
    response: Response,
    user: User = Depends(get_current_user),
):
    response.headers["Cache-Control"] = "no-store"
    return user