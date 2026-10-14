from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.integrations.google_workspace import GoogleServiceAccountReader
from app.models.user import User
from app.schemas.candidate import (
    CandidateApplicationSummary,
    CandidateJobPostingOption,
    GoogleFormsConfigurationResponse,
    GoogleFormsSyncRequest,
    GoogleFormsSyncResponse,
    ApplicationNotificationsResponse,
)
from app.security import require_interviewer
from app.services.candidate_application_service import CandidateApplicationService
from app.services.google_forms_intake_service import GoogleFormsIntakeService


router = APIRouter(prefix="/api/candidates", tags=["Candidates"])


def _service() -> GoogleFormsIntakeService:
    settings = get_settings()
    return GoogleFormsIntakeService(
        GoogleServiceAccountReader(settings.google_service_account_file),
        settings,
    )


def _notification_service() -> GoogleFormsIntakeService:
    settings = get_settings()
    return GoogleFormsIntakeService(
        GoogleServiceAccountReader(settings.google_service_account_file, sheet_timeout_seconds=15), settings)


@router.get("/notifications", response_model=ApplicationNotificationsResponse)
def application_notifications(response: Response, db: Session = Depends(get_db),
                              interviewer: User = Depends(require_interviewer)):
    response.headers["Cache-Control"] = "no-store"
    settings = get_settings()
    if not settings.google_forms_spreadsheet_id or not Path(settings.google_service_account_file).is_file():
        return {"status": "not_configured", "pending_count": None, "unmatched_count": None,
            "jobs": [], "checked_at": None, "message": "Configure Google Forms response collection to receive application notifications."}
    try:
        return _notification_service().pending_responses(db, interviewer_user_id=interviewer.id)
    except (RuntimeError, ValueError, OSError):
        return {"status": "unavailable", "pending_count": None, "unmatched_count": None,
            "jobs": [], "checked_at": None,
            "message": "Could not check new applications. Verify Google Sheets access and the response-sheet columns, then retry."}


@router.get(
    "/google-forms/configuration",
    response_model=GoogleFormsConfigurationResponse,
)
def google_forms_configuration(
    _interviewer: User = Depends(require_interviewer),
):
    settings = get_settings()
    missing: list[str] = []
    if not settings.google_forms_spreadsheet_id:
        missing.append("GOOGLE_FORMS_SPREADSHEET_ID")
    if not Path(settings.google_service_account_file).is_file():
        missing.append("GOOGLE_SERVICE_ACCOUNT_FILE")
    return {
        "configured": not missing,
        "form_url": settings.google_form_url,
        "sheet_name": settings.google_forms_sheet_name,
        "job_column": settings.google_forms_job_column,
        "missing_settings": missing,
    }


@router.get(
    "/job-postings",
    response_model=list[CandidateJobPostingOption],
)
def list_candidate_job_postings(
    db: Session = Depends(get_db),
    interviewer: User = Depends(require_interviewer),
):
    return GoogleFormsIntakeService.list_postings(
        db,
        interviewer_user_id=interviewer.id,
    )


@router.get(
    "/applications",
    response_model=list[CandidateApplicationSummary],
)
def list_candidate_applications(
    job_posting_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    interviewer: User = Depends(require_interviewer),
):
    return GoogleFormsIntakeService.list_applications(
        db,
        interviewer_user_id=interviewer.id,
        job_posting_id=job_posting_id,
    )


@router.delete(
    "/applications/{application_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_candidate_application(
    application_id: int,
    db: Session = Depends(get_db),
    interviewer: User = Depends(require_interviewer),
):
    try:
        CandidateApplicationService(get_settings()).delete(
            db,
            application_id=application_id,
            interviewer_user_id=interviewer.id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from None
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/google-forms/sync",
    response_model=GoogleFormsSyncResponse,
)
def sync_google_form_responses(
    data: GoogleFormsSyncRequest,
    db: Session = Depends(get_db),
    interviewer: User = Depends(require_interviewer),
):
    try:
        return _service().sync(
            db,
            interviewer_user_id=interviewer.id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from None
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from None
