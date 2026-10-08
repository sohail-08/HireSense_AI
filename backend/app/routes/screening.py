from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal, get_db
from app.models.screening import ScreeningBatchItem, ScreeningRunStatus
from app.models.user import User
from app.schemas.screening import (
    ScreeningBatchCreate,
    ScreeningBatchResponse,
    ScreeningDashboardResponse,
    ScreeningJobOption,
    ScreeningRunDetailResponse,
)
from app.security import require_interviewer
from app.services.screening_service import ScreeningService


router = APIRouter(prefix="/api/screening", tags=["CV Screening"])


def _service() -> ScreeningService:
    return ScreeningService(get_settings())


def _process_batch(batch_id: int) -> None:
    with SessionLocal() as db:
        _service().process_batch(db, batch_id=batch_id)


@router.get("/jobs", response_model=list[ScreeningJobOption])
def list_screening_jobs(
    db: Session = Depends(get_db),
    interviewer: User = Depends(require_interviewer),
):
    return _service().list_jobs(db, interviewer_user_id=interviewer.id)


@router.get(
    "/jobs/{job_posting_id}",
    response_model=ScreeningDashboardResponse,
)
def get_screening_dashboard(
    job_posting_id: int,
    db: Session = Depends(get_db),
    interviewer: User = Depends(require_interviewer),
):
    try:
        return _service().dashboard(
            db,
            interviewer_user_id=interviewer.id,
            job_posting_id=job_posting_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post(
    "/batches",
    response_model=ScreeningBatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_screening_batch(
    data: ScreeningBatchCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    interviewer: User = Depends(require_interviewer),
):
    service = _service()
    try:
        batch = service.create_batch(
            db,
            interviewer_user_id=interviewer.id,
            job_posting_id=data.job_posting_id,
            application_ids=data.application_ids,
        )
        result = service.get_batch(
            db,
            interviewer_user_id=interviewer.id,
            batch_id=batch.id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    background_tasks.add_task(_process_batch, batch.id)
    return result


@router.get(
    "/batches/{batch_id}",
    response_model=ScreeningBatchResponse,
)
def get_screening_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    interviewer: User = Depends(require_interviewer),
):
    try:
        return _service().get_batch(
            db,
            interviewer_user_id=interviewer.id,
            batch_id=batch_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@router.post(
    "/batches/{batch_id}/retry",
    response_model=ScreeningBatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_screening_batch(
    batch_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    interviewer: User = Depends(require_interviewer),
):
    service = _service()
    try:
        original = service.get_batch(
            db,
            interviewer_user_id=interviewer.id,
            batch_id=batch_id,
        )
        application_ids = list(
            db.scalars(
                select(ScreeningBatchItem.application_id).where(
                    ScreeningBatchItem.batch_id == batch_id,
                    ScreeningBatchItem.status.in_(
                        [
                            ScreeningRunStatus.FAILED,
                            ScreeningRunStatus.REVIEW_REQUIRED,
                        ]
                    ),
                )
            )
        )
        if not application_ids:
            raise ValueError("This batch has no failed or review-required applications")
        batch = service.create_batch(
            db,
            interviewer_user_id=interviewer.id,
            job_posting_id=original["job_posting_id"],
            application_ids=application_ids,
        )
        result = service.get_batch(
            db,
            interviewer_user_id=interviewer.id,
            batch_id=batch.id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    background_tasks.add_task(_process_batch, batch.id)
    return result


@router.get(
    "/runs/{run_id}",
    response_model=ScreeningRunDetailResponse,
)
def get_screening_run(
    run_id: int,
    db: Session = Depends(get_db),
    interviewer: User = Depends(require_interviewer),
):
    try:
        return _service().run_detail(
            db,
            interviewer_user_id=interviewer.id,
            run_id=run_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
