from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session
from app.database import get_db
from app.security import require_interviewer
from app.models.user import User
from app.routes.interview_rooms import run, sensitive
from app.schemas.interview_analysis import StartAnalysis, CorrectPairs, ReviewInput, ReferenceUpdate
from app.services.interview_analysis import InterviewAnalysisService

router = APIRouter(prefix="/api/interview-rooms/{interview_id:int}/analysis", tags=["Interview analysis"])


def service():
    return InterviewAnalysisService()


@router.get("")
def get(interview_id: int, response: Response, run_id: int | None = None, db: Session = Depends(get_db),
        user: User = Depends(require_interviewer), analysis=Depends(service)):
    sensitive(response)
    return run(db, lambda: analysis.read(db, user.id, interview_id, run_id))


@router.post("", status_code=202)
def start(interview_id: int, data: StartAnalysis, response: Response, db: Session = Depends(get_db),
          user: User = Depends(require_interviewer), analysis=Depends(service)):
    sensitive(response)
    def operation():
        item = analysis.enqueue(db, user.id, interview_id, data)
        return {"id": item.id, "status": item.status, "version": item.version}
    return run(db, operation)


@router.put("/references")
def references(interview_id: int, data: ReferenceUpdate, response: Response, db: Session = Depends(get_db),
               user: User = Depends(require_interviewer), analysis=Depends(service)):
    sensitive(response)
    return run(db, lambda: analysis.references(db, user.id, interview_id, data))


@router.post("/pairing", status_code=202)
def correct(interview_id: int, data: CorrectPairs, response: Response, db: Session = Depends(get_db),
            user: User = Depends(require_interviewer), analysis=Depends(service)):
    sensitive(response)
    def operation():
        item = analysis.correct(db, user.id, interview_id, data)
        return {"id": item.id, "status": item.status, "version": item.version}
    return run(db, operation)


@router.post("/{run_id}/reviews")
def review(interview_id: int, run_id: int, data: ReviewInput, response: Response, db: Session = Depends(get_db),
           user: User = Depends(require_interviewer), analysis=Depends(service)):
    sensitive(response)
    return run(db, lambda: analysis.review(db, user.id, interview_id, run_id, data))
