from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Response,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.auth import (
    LoginRequest,
    TokenResponse,
)
from app.schemas.user import UserResponse
from app.security import (
    DUMMY_HASH,
    create_access_token,
    require_interviewer,
    verify_password,
)


router = APIRouter(
    prefix="/api/auth",
    tags=["Authentication"],
)


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

    if user.role != UserRole.INTERVIEWER:
        raise HTTPException(
            status_code=403,
            detail="Candidates join using the private link in their interview invitation. No account or sign-in is needed.",
            headers={"Cache-Control": "no-store"},
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
    user: User = Depends(require_interviewer),
):
    response.headers["Cache-Control"] = "no-store"
    return user
