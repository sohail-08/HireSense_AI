from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from app.database import get_db
from app.models.user import User
from app.security import require_interviewer
from app.schemas.interview import SelectionRequest, PrepareInvites, ConfirmInvites, RescheduleRequest, RetryDelivery
from app.schemas.interview import SelectionPreview, InvitationPreview, InvitationBatchResult, InterviewScheduleResult
from app.services.interview_service import InterviewService, InterviewConflict

router = APIRouter(prefix="/api/interviews", tags=["Interview scheduling"])


def execute(operation):
    try:
        return operation()
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from None
    except InterviewConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except SQLAlchemyError:
        raise HTTPException(409, "Scheduling state changed. Refresh and prepare a new preview.") from None


@router.post("/selection/preview", response_model=SelectionPreview, response_model_exclude_unset=True)
def preview(data: SelectionRequest, db: Session = Depends(get_db), user: User = Depends(require_interviewer)):
    return execute(lambda: InterviewService().preview_selection(db, user.id, data))


@router.post("/invitations/prepare", response_model=InvitationBatchResult, response_model_exclude_unset=True)
def prepare(data: PrepareInvites, db: Session = Depends(get_db), user: User = Depends(require_interviewer)):
    return execute(lambda: InterviewService().prepare(db, user.id, data))


@router.post("/batches/{batch_id}/confirm", response_model=InvitationBatchResult, response_model_exclude_unset=True)
def confirm(batch_id: int, data: ConfirmInvites, tasks: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(require_interviewer)):
    result = execute(lambda: InterviewService().confirm(db, user.id, batch_id, data))
    if result["pending"]:
        tasks.add_task(InterviewService().deliver_batch, result["id"])
    return result


@router.get("/batches/{batch_id}", response_model=InvitationBatchResult, response_model_exclude_unset=True)
def batch(batch_id: int, db: Session = Depends(get_db), user: User = Depends(require_interviewer)):
    return execute(lambda: InterviewService().batch(db, user.id, batch_id))


@router.get("/schedules", response_model=list[InterviewScheduleResult])
def schedules(job_posting_id: int | None = Query(default=None, gt=0), db: Session = Depends(get_db), user: User = Depends(require_interviewer)):
    return execute(lambda: InterviewService().schedules(db, user.id, job_posting_id=job_posting_id))


@router.post("/reschedule/preview", response_model=InvitationPreview, response_model_exclude_unset=True)
def reschedule_preview(data: RescheduleRequest, db: Session = Depends(get_db), user: User = Depends(require_interviewer)):
    return execute(lambda: InterviewService().preview_reschedule(db, user.id, data))


@router.post("/reschedule/confirm", response_model=InvitationBatchResult, response_model_exclude_unset=True)
def reschedule(data: ConfirmInvites, tasks: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(require_interviewer)):
    result = execute(lambda: InterviewService().confirm_reschedule(db, user.id, data))
    if result["pending"]:
        tasks.add_task(InterviewService().deliver_batch, result["id"])
    return result


@router.post("/deliveries/{delivery_id}/retry", response_model=InvitationBatchResult, response_model_exclude_unset=True)
def retry(delivery_id: int, data: RetryDelivery, tasks: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(require_interviewer)):
    result = execute(lambda: InterviewService().retry(db, user.id, delivery_id, data.expected_attempts))
    tasks.add_task(InterviewService().deliver_batch, result["id"])
    return result
