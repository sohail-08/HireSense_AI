from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.agents.job_description import OllamaJobDescriptionModel
from app.database import get_db
from app.models.user import User
from app.schemas.job import (
    JobDescriptionGenerateRequest,
    JobDescriptionResponse,
    JobDescriptionUpdateRequest,
)
from app.security import require_interviewer
from app.services.job_description_service import JobDescriptionService


router = APIRouter(
    prefix="/api/job-descriptions",
    tags=["Job Descriptions"],
)


def _service() -> JobDescriptionService:
    return JobDescriptionService(OllamaJobDescriptionModel())


@router.post(
    "/generate",
    response_model=JobDescriptionResponse,
    status_code=status.HTTP_201_CREATED,
)
def generate_job_description(
    data: JobDescriptionGenerateRequest,
    db: Session = Depends(get_db),
    interviewer: User = Depends(require_interviewer),
):
    try:
        return _service().generate(
            db,
            requirement_profile_id=data.requirement_profile_id,
            interviewer_user_id=interviewer.id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None


@router.get("/{job_description_id}", response_model=JobDescriptionResponse)
def get_job_description(
    job_description_id: int,
    db: Session = Depends(get_db),
    interviewer: User = Depends(require_interviewer),
):
    try:
        return _service().get_for_interviewer(
            db,
            job_description_id=job_description_id,
            interviewer_user_id=interviewer.id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@router.patch("/{job_description_id}", response_model=JobDescriptionResponse)
def update_job_description(
    job_description_id: int,
    data: JobDescriptionUpdateRequest,
    db: Session = Depends(get_db),
    interviewer: User = Depends(require_interviewer),
):
    try:
        return _service().update_draft(
            db,
            job_description_id=job_description_id,
            interviewer_user_id=interviewer.id,
            update=data,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/{job_description_id}/approve", response_model=JobDescriptionResponse)
def approve_job_description(
    job_description_id: int,
    db: Session = Depends(get_db),
    interviewer: User = Depends(require_interviewer),
):
    try:
        return _service().approve(
            db,
            job_description_id=job_description_id,
            interviewer_user_id=interviewer.id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
