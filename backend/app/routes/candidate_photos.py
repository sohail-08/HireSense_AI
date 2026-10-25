"""Application photos are served only to the owning interviewer, never public URLs."""
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import require_interviewer
from app.services.candidate_photo import CandidatePhotoService, CandidatePhotoUnavailable

router = APIRouter(tags=["Candidate information"])


def service():
    return CandidatePhotoService()


@router.get("/api/interview-rooms/{interview_id}/candidate-photo")
def photo(interview_id: int, db: Session = Depends(get_db), user=Depends(require_interviewer), photos=Depends(service)):
    try:
        data = photos.photo(db, user.id, interview_id)
    except (LookupError, PermissionError):
        raise HTTPException(404, "Candidate photo is not available") from None
    except CandidatePhotoUnavailable:
        raise HTTPException(503, "Candidate photo is temporarily unavailable") from None
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, no-store", "Pragma": "no-cache",
        "Vary": "Authorization", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
        "Content-Disposition": 'inline; filename="candidate-photo.jpg"'})
