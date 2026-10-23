"""Private practical-assessment APIs; candidate endpoints never expose reviews."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from app.database import get_db
from app.security import require_interviewer
from app.models.user import User
from app.routes.interview_rooms import COOKIE_NAME, candidate_origin, sensitive, run, limiter
from app.schemas.work_sample import Task, SaveTask, Action, CandidateReady, SaveSubmission, DraftTask, Review, AssessExercise
from app.services.work_sample import WorkSampleService

router = APIRouter(tags=["Live work samples"])


def get_service():
    return WorkSampleService()


@router.get("/api/interview-rooms/candidate/work-sample")
def candidate_read(request: Request, response: Response, db: Session = Depends(get_db), service=Depends(get_service)):
    sensitive(response)
    return run(db, lambda: service.candidate_read(db, request.cookies.get(COOKIE_NAME)))


@router.post("/api/interview-rooms/candidate/work-sample/ready")
def candidate_ready(data: CandidateReady, request: Request, response: Response, db: Session = Depends(get_db), service=Depends(get_service)):
    candidate_origin(request)
    sensitive(response)
    return run(db, lambda: service.ready(db, request.cookies.get(COOKIE_NAME), data))


@router.post("/api/interview-rooms/candidate/work-sample/save")
def candidate_save(data: SaveSubmission, request: Request, response: Response, db: Session = Depends(get_db), service=Depends(get_service)):
    candidate_origin(request)
    sensitive(response)
    token = request.cookies.get(COOKIE_NAME)
    # Cookie never enters logs, response bodies, or limiter keys.
    key = ("work-save", request.client.host if request.client else "unknown")
    if not limiter.allow(key, 120):
        raise HTTPException(429, "Please wait before saving again")
    return run(db, lambda: service.save_submission(db, token, data))


@router.get("/api/work-samples/templates")
def templates(response: Response, db: Session = Depends(get_db), user: User = Depends(require_interviewer), service=Depends(get_service)):
    sensitive(response)
    return service.list_templates(db, user.id)


@router.post("/api/work-samples/templates")
def save_template(data: Task, response: Response, db: Session = Depends(get_db), user: User = Depends(require_interviewer), service=Depends(get_service)):
    sensitive(response)
    return service.template(db, user.id, data)


@router.get("/api/work-samples/interviews/{interview_id}")
def read(interview_id: int, response: Response, db: Session = Depends(get_db), user: User = Depends(require_interviewer), service=Depends(get_service)):
    sensitive(response)
    return run(db, lambda: service.read(db, user.id, interview_id))


@router.put("/api/work-samples/interviews/{interview_id}")
def save(interview_id: int, data: SaveTask, response: Response, db: Session = Depends(get_db), user: User = Depends(require_interviewer), service=Depends(get_service)):
    sensitive(response)
    return run(db, lambda: service.save_task(db, user.id, interview_id, data))


@router.post("/api/work-samples/interviews/{interview_id}/action")
def action(interview_id: int, data: Action, response: Response, db: Session = Depends(get_db), user: User = Depends(require_interviewer), service=Depends(get_service)):
    sensitive(response)
    return run(db, lambda: service.action(db, user.id, interview_id, data))


@router.post("/api/work-samples/interviews/{interview_id}/draft")
def draft(interview_id: int, data: DraftTask, response: Response, db: Session = Depends(get_db), user: User = Depends(require_interviewer), service=Depends(get_service)):
    sensitive(response)
    if not limiter.allow(("work-draft", user.id), 5):
        raise HTTPException(429, "Please wait before generating another draft")
    try:
        return run(db, lambda: service.draft_task(db, user.id, interview_id, data.brief))
    except RuntimeError:
        db.rollback()
        raise HTTPException(503, "AI task drafting is unavailable. You can still prepare the task manually.") from None


@router.post("/api/work-samples/interviews/{interview_id}/assess")
def assess(interview_id: int, data: AssessExercise, response: Response, db: Session = Depends(get_db), user: User = Depends(require_interviewer), service=Depends(get_service)):
    sensitive(response)
    return run(db, lambda: service.assess(db, user.id, interview_id, data.discussion_segment_ids))


@router.post("/api/work-samples/interviews/{interview_id}/review")
def review(interview_id: int, data: Review, response: Response, db: Session = Depends(get_db), user: User = Depends(require_interviewer), service=Depends(get_service)):
    sensitive(response)
    return run(db, lambda: service.review(db, user.id, interview_id, data))
