"""Thin room APIs. Public candidate credentials are cookies, never interviewer JWTs."""
import time
from collections import defaultdict, deque
from threading import Lock
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, Request, Response, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.security import require_interviewer
from app.services.interview_rooms import InterviewRooms, RoomAccessError, RoomConflict
from app.integrations.livekit_media import MediaUnavailable
from app.schemas.interview_room import ExchangeInvitation, ConfirmRoomAction, EmptyRoomAction, CandidateRoomInfo, InterviewerRoomInfo, LinkResult, MediaAccess

router = APIRouter(prefix="/api/interview-rooms", tags=["Interview rooms"])
COOKIE_NAME = "hiresense_candidate_session"
COOKIE_PATH = "/api/interview-rooms/candidate"


class PublicRateLimiter:
    """Bounded, thread-safe single-worker limit; production replicas need a shared limit."""
    def __init__(self, clock=time.monotonic):
        self.clock, self.lock, self.buckets = clock, Lock(), defaultdict(deque)

    def allow(self, key, limit):
        now = self.clock()
        with self.lock:
            if key not in self.buckets and len(self.buckets) >= 5000:
                self.buckets.pop(next(iter(self.buckets)))
            bucket = self.buckets[key]
            while bucket and bucket[0] <= now - 60:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            return True


limiter = PublicRateLimiter()


def get_rooms():
    return InterviewRooms()


def sensitive(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"


def candidate_origin(request):
    if request.method != "GET" and request.headers.get("origin") != get_settings().frontend_url.rstrip("/"):
        raise HTTPException(403, "Interview request origin is not permitted")


def run(db, operation):
    try:
        return operation()
    except RoomAccessError as exc:
        payload = {"detail": "This interview access is not available.", "code": exc.code}
        if exc.retry_at:
            payload["retry_at"] = exc.retry_at.isoformat()
        response = JSONResponse(payload, status_code=exc.status)
        sensitive(response)
        if exc.code in {"invalid_session", "revoked_link", "expired_link", "ended", "ending", "cancelled"}:
            response.delete_cookie(COOKIE_NAME, path=COOKIE_PATH, secure=get_settings().candidate_cookie_secure, httponly=True, samesite="strict")
        return response
    except LookupError:
        raise HTTPException(404, "Interview not found") from None
    except PermissionError:
        raise HTTPException(403, "Interviewer access required") from None
    except RoomConflict as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from None
    except MediaUnavailable as exc:
        db.rollback()
        raise HTTPException(503, str(exc)) from None
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(409, "Interview state changed. Refresh and try again.") from None
    except ValueError:
        db.rollback()
        raise HTTPException(422, "Interview room request is not valid") from None


@router.post("/candidate/exchange", response_model=CandidateRoomInfo)
def exchange(data: ExchangeInvitation, request: Request, response: Response, db: Session = Depends(get_db), rooms: InterviewRooms = Depends(get_rooms)):
    candidate_origin(request)
    key = request.client.host if request.client else "unknown"
    if not limiter.allow(key, get_settings().candidate_public_rate_limit):
        return JSONResponse({"detail": "Please wait before trying this interview link again.", "code": "rate_limited"}, 429,
            headers={"Retry-After": "60", "Cache-Control": "no-store"})
    settings = rooms.settings
    if not settings.candidate_cookie_secure and urlsplit(settings.interview_join_base_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise HTTPException(503, "Secure candidate cookies are required for this deployment")
    result = run(db, lambda: rooms.exchange(db, data.token))
    if isinstance(result, Response):
        return result
    token, expires, info = result
    response.set_cookie(COOKIE_NAME, token, max_age=settings.candidate_session_minutes * 60,
        expires=expires, path=COOKIE_PATH, secure=settings.candidate_cookie_secure, httponly=True, samesite="strict")
    sensitive(response)
    return info


@router.get("/candidate/status", response_model=CandidateRoomInfo)
def candidate_status(request: Request, response: Response, db: Session = Depends(get_db), rooms: InterviewRooms = Depends(get_rooms)):
    sensitive(response)
    return run(db, lambda: rooms.candidate_status(db, request.cookies.get(COOKIE_NAME)))


@router.post("/candidate/waiting", response_model=CandidateRoomInfo)
def waiting(data: EmptyRoomAction, request: Request, response: Response, db: Session = Depends(get_db), rooms: InterviewRooms = Depends(get_rooms)):
    candidate_origin(request)
    sensitive(response)
    return run(db, lambda: rooms.waiting(db, request.cookies.get(COOKIE_NAME)))


@router.post("/candidate/media-token", response_model=MediaAccess)
def candidate_media(data: EmptyRoomAction, request: Request, response: Response, db: Session = Depends(get_db), rooms: InterviewRooms = Depends(get_rooms)):
    candidate_origin(request)
    sensitive(response)
    return run(db, lambda: rooms.media_access(db, candidate_token=request.cookies.get(COOKIE_NAME)))


@router.post("/candidate/connected", response_model=CandidateRoomInfo)
def candidate_connected(data: EmptyRoomAction, request: Request, response: Response, db: Session = Depends(get_db), rooms: InterviewRooms = Depends(get_rooms)):
    candidate_origin(request)
    sensitive(response)
    return run(db, lambda: rooms.connected(db, candidate_token=request.cookies.get(COOKIE_NAME)))


@router.post("/candidate/leave", response_model=CandidateRoomInfo)
def candidate_leave(data: EmptyRoomAction, request: Request, response: Response, db: Session = Depends(get_db), rooms: InterviewRooms = Depends(get_rooms)):
    candidate_origin(request)
    sensitive(response)
    return run(db, lambda: rooms.leave(db, candidate_token=request.cookies.get(COOKIE_NAME)))


@router.get("/{interview_id}", response_model=InterviewerRoomInfo)
def status(interview_id: int, response: Response, db: Session = Depends(get_db), user: User = Depends(require_interviewer), rooms: InterviewRooms = Depends(get_rooms)):
    sensitive(response)
    return run(db, lambda: rooms.info(db, rooms.owned(db, user.id, interview_id), interviewer=True))


@router.get("/{interview_id}/candidate-link", response_model=LinkResult)
def retrieve_link(interview_id: int, response: Response, db: Session = Depends(get_db), user: User = Depends(require_interviewer), rooms: InterviewRooms = Depends(get_rooms)):
    sensitive(response)
    return run(db, lambda: rooms.link(db, user.id, interview_id, retrieve_only=True))


@router.post("/{interview_id}/candidate-link", response_model=LinkResult)
def generate_link(interview_id: int, data: ConfirmRoomAction, response: Response, db: Session = Depends(get_db), user: User = Depends(require_interviewer), rooms: InterviewRooms = Depends(get_rooms)):
    sensitive(response)
    return run(db, lambda: rooms.link(db, user.id, interview_id))


@router.post("/{interview_id}/candidate-link/rotate", response_model=LinkResult)
def rotate_link(interview_id: int, data: ConfirmRoomAction, response: Response, db: Session = Depends(get_db), user: User = Depends(require_interviewer), rooms: InterviewRooms = Depends(get_rooms)):
    sensitive(response)
    return run(db, lambda: rooms.link(db, user.id, interview_id, rotate=True))


@router.post("/{interview_id}/candidate-link/revoke", response_model=InterviewerRoomInfo)
def revoke_link(interview_id: int, data: ConfirmRoomAction, response: Response, db: Session = Depends(get_db), user: User = Depends(require_interviewer), rooms: InterviewRooms = Depends(get_rooms)):
    sensitive(response)
    return run(db, lambda: rooms.revoke(db, user.id, interview_id))


@router.post("/{interview_id}/admit", response_model=InterviewerRoomInfo)
def admit(interview_id: int, data: ConfirmRoomAction, db: Session = Depends(get_db), user: User = Depends(require_interviewer), rooms: InterviewRooms = Depends(get_rooms)):
    return run(db, lambda: rooms.admit(db, user.id, interview_id))


@router.post("/{interview_id}/media-token", response_model=MediaAccess)
def interviewer_media(interview_id: int, data: EmptyRoomAction, response: Response, db: Session = Depends(get_db), user: User = Depends(require_interviewer), rooms: InterviewRooms = Depends(get_rooms)):
    sensitive(response)
    return run(db, lambda: rooms.media_access(db, user_id=user.id, interview_id=interview_id))


@router.post("/{interview_id}/connected", response_model=InterviewerRoomInfo)
def interviewer_connected(interview_id: int, data: EmptyRoomAction, db: Session = Depends(get_db), user: User = Depends(require_interviewer), rooms: InterviewRooms = Depends(get_rooms)):
    return run(db, lambda: rooms.connected(db, user_id=user.id, interview_id=interview_id))


@router.post("/{interview_id}/leave", response_model=InterviewerRoomInfo)
def interviewer_leave(interview_id: int, data: EmptyRoomAction, db: Session = Depends(get_db), user: User = Depends(require_interviewer), rooms: InterviewRooms = Depends(get_rooms)):
    return run(db, lambda: rooms.leave(db, user_id=user.id, interview_id=interview_id))


@router.post("/{interview_id}/end", response_model=InterviewerRoomInfo)
def end(interview_id: int, data: ConfirmRoomAction, db: Session = Depends(get_db), user: User = Depends(require_interviewer), rooms: InterviewRooms = Depends(get_rooms)):
    return run(db, lambda: rooms.end(db, user.id, interview_id))
