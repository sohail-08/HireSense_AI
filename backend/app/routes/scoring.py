from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.scoring import ScoreRunRequest, ScoringApproval
from app.security import require_interviewer
from app.services.scoring_service import ScoringConflict, ScoringService


router = APIRouter(prefix="/api/scoring", tags=["Deterministic scoring"])


def execute(operation):
    try:
        return operation()
    except LookupError as exc:
        raise HTTPException(404, detail=str(exc)) from None
    except ScoringConflict as exc:
        raise HTTPException(409, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from None


@router.get("/jobs/{job_id}/configuration")
def configuration(job_id: int, db: Session = Depends(get_db), user: User = Depends(require_interviewer)):
    return execute(lambda: ScoringService.proposal(db, user_id=user.id, job_id=job_id))


@router.post("/jobs/{job_id}/configuration")
def approve_configuration(job_id: int, data: ScoringApproval, db: Session = Depends(get_db), user: User = Depends(require_interviewer)):
    return execute(lambda: ScoringService().approve(db, user_id=user.id, job_id=job_id, data=data))


@router.post("/jobs/{job_id}/runs")
def calculate(job_id: int, data: ScoreRunRequest, db: Session = Depends(get_db), user: User = Depends(require_interviewer)):
    return execute(lambda: ScoringService().run(db, user_id=user.id, job_id=job_id, data=data))


@router.get("/jobs/{job_id}/runs")
def history(job_id: int, db: Session = Depends(get_db), user: User = Depends(require_interviewer)):
    return execute(lambda: ScoringService().list_runs(db, user_id=user.id, job_id=job_id))


@router.get("/runs/{run_id}")
def detail(run_id: int, db: Session = Depends(get_db), user: User = Depends(require_interviewer)):
    return execute(lambda: ScoringService().detail(db, user_id=user.id, run_id=run_id))
