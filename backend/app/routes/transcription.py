"""Thin public controls and authenticated worker-only text persistence APIs."""
import hmac
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.models.transcription import TranscriptSegment, TranscriptionSession
from app.security import require_interviewer
from app.services.transcription_service import TranscriptionService, TranscriptionConflict, segment_payload
from app.routes.interview_rooms import COOKIE_NAME, candidate_origin, get_rooms, sensitive, run
from app.schemas.transcription import ConsentInput, ClaimInput, WorkerUpdate, StreamInput, SegmentInput

router = APIRouter(tags=["Transcription"])


def get_transcription():
    return TranscriptionService()


def invoke(db, operation):
    def guarded():
        try:
            return operation()
        except TranscriptionConflict as exc:
            db.rollback()
            raise HTTPException(409, str(exc)) from None
    return run(db, guarded)


def interviewer_row(db, user, interview_id, rooms):
    return rooms.owned(db, user.id, interview_id, lock=True)


@router.get("/api/interview-rooms/{interview_id:int}/transcription/status")
def interviewer_status(interview_id: int, response: Response, db: Session = Depends(get_db),
        user: User = Depends(require_interviewer), rooms=Depends(get_rooms), service=Depends(get_transcription)):
    sensitive(response)
    return invoke(db, lambda: service.status(db, interviewer_row(db, user, interview_id, rooms), "INTERVIEWER"))


@router.post("/api/interview-rooms/{interview_id:int}/transcription/consent")
def interviewer_consent(interview_id: int, data: ConsentInput, response: Response, db: Session = Depends(get_db),
        user: User = Depends(require_interviewer), rooms=Depends(get_rooms), service=Depends(get_transcription)):
    sensitive(response)
    return invoke(db, lambda: service.consent(db, interviewer_row(db, user, interview_id, rooms), "INTERVIEWER", data))


@router.post("/api/interview-rooms/{interview_id:int}/transcription/start")
def start(interview_id: int, response: Response, db: Session = Depends(get_db), user: User = Depends(require_interviewer),
        rooms=Depends(get_rooms), service=Depends(get_transcription)):
    sensitive(response)
    return invoke(db, lambda: service.start(db, interviewer_row(db, user, interview_id, rooms)))


@router.post("/api/interview-rooms/{interview_id:int}/transcription/stop")
def stop(interview_id: int, response: Response, db: Session = Depends(get_db), user: User = Depends(require_interviewer),
        rooms=Depends(get_rooms), service=Depends(get_transcription)):
    sensitive(response)
    return invoke(db, lambda: service.stop(db, interviewer_row(db, user, interview_id, rooms)))


@router.get("/api/interview-rooms/{interview_id:int}/transcript")
def transcript(interview_id: int, response: Response, cursor: str | None = None, db: Session = Depends(get_db),
        user: User = Depends(require_interviewer), rooms=Depends(get_rooms), service=Depends(get_transcription)):
    sensitive(response)
    def fetch():
        interviewer_row(db, user, interview_id, rooms)
        query = select(TranscriptSegment).join(TranscriptionSession).where(
            TranscriptSegment.interview_id == interview_id, TranscriptionSession.expires_at > service.now())
        if cursor:
            previous = db.get(TranscriptSegment, cursor)
            if not previous or previous.interview_id != interview_id:
                raise TranscriptionConflict("Invalid transcript cursor")
            # ID is a stable tie-breaker across session-local sequence numbers.
            from sqlalchemy import or_, and_
            query = query.where(or_(TranscriptSegment.start_at > previous.start_at,
                and_(TranscriptSegment.start_at == previous.start_at, TranscriptSegment.id > previous.id)))
        rows = list(db.scalars(query.order_by(TranscriptSegment.start_at, TranscriptSegment.id).limit(501)))
        return {"segments": [segment_payload(row) for row in rows[:500]], "next_cursor": rows[499].id if len(rows) > 500 else None}
    return invoke(db, fetch)


@router.delete("/api/interview-rooms/{interview_id:int}/transcript", status_code=204)
def delete_transcript(interview_id: int, response: Response, db: Session = Depends(get_db),
        user: User = Depends(require_interviewer), rooms=Depends(get_rooms), service=Depends(get_transcription)):
    sensitive(response)
    return invoke(db, lambda: service.delete_history(db, interviewer_row(db, user, interview_id, rooms)))


@router.get("/api/interview-rooms/candidate/transcription/status")
def candidate_status(request: Request, response: Response, db: Session = Depends(get_db),
        rooms=Depends(get_rooms), service=Depends(get_transcription)):
    sensitive(response)
    return invoke(db, lambda: service.status(db, rooms.session(db, request.cookies.get(COOKIE_NAME), lock=True), "CANDIDATE"))


@router.post("/api/interview-rooms/candidate/transcription/consent")
def candidate_consent(data: ConsentInput, request: Request, response: Response, db: Session = Depends(get_db),
        rooms=Depends(get_rooms), service=Depends(get_transcription)):
    candidate_origin(request)
    sensitive(response)
    return invoke(db, lambda: service.consent(db, rooms.session(db, request.cookies.get(COOKIE_NAME), lock=True), "CANDIDATE", data))


def worker_authorization(request: Request):
    key = get_settings().transcription_worker_secret.get_secret_value()
    authorization = request.headers.get("authorization", "")
    if len(key) < 32 or not hmac.compare_digest(authorization, "Bearer " + key):
        raise HTTPException(401, "Worker authentication required")


internal = APIRouter(prefix="/api/internal/transcription", dependencies=[Depends(worker_authorization)], tags=["Internal transcription"])


def worker_invoke(db, response, operation):
    sensitive(response)
    try:
        return operation()
    except TranscriptionConflict:
        db.rollback()
        raise HTTPException(409, "Transcription session unavailable") from None
    except PermissionError:
        db.rollback()
        raise HTTPException(403, "Worker access denied") from None
    except LookupError:
        raise HTTPException(404, "Transcription session unavailable") from None
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(503, "Transcript persistence unavailable") from None


@internal.post("/{sid}/claim")
def claim(sid: str, data: ClaimInput, response: Response, db: Session = Depends(get_db), service=Depends(get_transcription)):
    return worker_invoke(db, response, lambda: service.claim(db, sid, data.claim, data.caption_public_key.model_dump()))


@internal.post("/{sid}/update")
def update(sid: str, data: WorkerUpdate, response: Response, db: Session = Depends(get_db), service=Depends(get_transcription)):
    return worker_invoke(db, response, lambda: service.update_worker(db, sid, data))


@internal.post("/{sid}/streams")
def stream(sid: str, data: StreamInput, response: Response, db: Session = Depends(get_db), service=Depends(get_transcription)):
    return worker_invoke(db, response, lambda: service.open_stream(db, sid, data))


@internal.post("/{sid}/segments")
def segment(sid: str, data: SegmentInput, response: Response, db: Session = Depends(get_db), service=Depends(get_transcription)):
    return worker_invoke(db, response, lambda: service.persist(db, sid, data))
