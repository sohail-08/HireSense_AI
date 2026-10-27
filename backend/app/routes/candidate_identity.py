"""No biometric templates, raw images or other candidates' identities leave the backend."""
import base64
from typing import Literal
from fastapi import APIRouter, Depends, Request, Response, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from app.database import get_db
from app.security import require_interviewer
from app.routes.interview_rooms import COOKIE_NAME, candidate_origin, sensitive, run, limiter
from app.services.candidate_identity import CandidateIdentityService

router = APIRouter(tags=["Candidate identity"])


def service():
    return CandidateIdentityService()


class Consent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allow: bool = Field(strict=True)
    notice_version: Literal["hiresense-face-v1"]


class Verify(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frames: list[str] = Field(min_length=3, max_length=3)
    version: int = Field(strict=True, ge=1)


class Manual(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    confirmed: Literal[True]
    note: str = Field(min_length=10, max_length=500)


class Confirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: Literal[True]


class CaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(strict=True, ge=1)


@router.get("/api/interview-rooms/candidate/identity")
def state(request: Request, response: Response, db: Session = Depends(get_db), identity=Depends(service)):
    sensitive(response)
    return run(db, lambda: identity.candidate_state(db, request.cookies.get(COOKIE_NAME)))


@router.post("/api/interview-rooms/candidate/identity/consent")
def consent(data: Consent, request: Request, response: Response, db: Session = Depends(get_db), identity=Depends(service)):
    candidate_origin(request); sensitive(response)
    return run(db, lambda: identity.live_consent(db, request.cookies.get(COOKIE_NAME), data.allow))


@router.post("/api/interview-rooms/candidate/identity/verify")
def verify(data: Verify, request: Request, response: Response, db: Session = Depends(get_db), identity=Depends(service)):
    candidate_origin(request); sensitive(response)
    if not limiter.allow(("identity", request.client.host if request.client else "unknown"), 12):
        raise HTTPException(429, "Please wait before retrying face verification.")
    frames = []
    try:
        for encoded in data.frames:
            if len(encoded) > 700000:
                raise ValueError()
            frame = base64.b64decode(encoded, validate=True)
            if not frame or len(frame) > 500000:
                raise ValueError()
            frames.append(frame)
    except (ValueError, TypeError):
        raise HTTPException(422, "Invalid camera sample. No image was saved.") from None
    return run(db, lambda: identity.verify(db, request.cookies.get(COOKIE_NAME), frames, data.version))


@router.post("/api/interview-rooms/candidate/identity/withdraw")
def withdraw(data: Confirm, request: Request, response: Response, db: Session = Depends(get_db), identity=Depends(service)):
    candidate_origin(request); sensitive(response)
    return run(db, lambda: identity.withdraw(db, request.cookies.get(COOKIE_NAME)))


@router.get("/api/interview-rooms/{interview_id}/identity")
def private_state(interview_id: int, response: Response, db: Session = Depends(get_db), user=Depends(require_interviewer), identity=Depends(service)):
    sensitive(response)
    return run(db, lambda: identity.interviewer_state(db, user.id, interview_id))


@router.post("/api/interview-rooms/{interview_id}/identity/manual")
def manual(interview_id: int, data: Manual, response: Response, db: Session = Depends(get_db), user=Depends(require_interviewer), identity=Depends(service)):
    sensitive(response)
    return run(db, lambda: identity.manual(db, user.id, interview_id, data.note))


@router.post("/api/interview-rooms/{interview_id}/identity/capture")
def capture(interview_id: int, data: CaptureRequest, response: Response, db: Session = Depends(get_db),
        user=Depends(require_interviewer), identity=Depends(service)):
    sensitive(response)
    return run(db, lambda: identity.request_capture(db, user.id, interview_id, data.version))


class IdentityBodyLimit:
    """Bound camera JSON before parsing, including chunked uploads without Content-Length."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST" or "/identity/" not in scope.get("path", ""):
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > 2_200_000:
                return await JSONResponse({"detail": "Camera request too large."}, status_code=413,
                    headers={"Cache-Control": "no-store"})(scope, receive, send)
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        delivered = False
        async def replay():
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}
        await self.app(scope, replay, send)
