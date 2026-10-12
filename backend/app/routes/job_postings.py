from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.agents.job_posting import GeminiPostingCommandModel
from app.config import get_settings
from app.database import get_db
from app.integrations.discord_mcp import (
    DiscordConfigurationError,
    DiscordDeliveryUncertainError,
    DiscordPublishError,
)
from app.models.user import User
from app.schemas.job_posting import (
    DiscordJobPostResponse,
    DiscordPostingAssistantRequest,
    DiscordPostingAssistantResponse,
    DiscordPostDefaultsResponse,
    DiscordPostPreviewRequest,
    DiscordPublishRequest,
)
from app.security import require_interviewer
from app.services.job_posting_assistant_service import JobPostingAssistantService
from app.services.job_posting_service import (
    DiscordJobPostingService,
    PublicationConflictError,
    StaleJobDescriptionError,
)


router = APIRouter(
    prefix="/api/job-postings",
    tags=["Job Postings"],
)


def _service() -> DiscordJobPostingService:
    return DiscordJobPostingService()


def _assistant_service() -> JobPostingAssistantService:
    return JobPostingAssistantService(GeminiPostingCommandModel())


@router.post(
    "/discord/assistant",
    response_model=DiscordPostingAssistantResponse,
)
def chat_with_discord_posting_assistant(
    data: DiscordPostingAssistantRequest,
    db: Session = Depends(get_db),
    interviewer: User = Depends(require_interviewer),
):
    try:
        return _assistant_service().chat(
            db,
            job_description_id=data.job_description_id,
            interviewer_user_id=interviewer.id,
            message=data.message,
            posting_id=data.posting_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except (PublicationConflictError, StaleJobDescriptionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except DiscordConfigurationError as exc:
        raise HTTPException(status_code=503, detail=exc.safe_message) from None
    except DiscordDeliveryUncertainError as exc:
        raise HTTPException(status_code=504, detail=exc.safe_message) from None
    except DiscordPublishError as exc:
        raise HTTPException(status_code=502, detail=exc.safe_message) from None
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"The job-posting assistant is unavailable: {exc}",
        ) from None


@router.get(
    "/discord/defaults",
    response_model=DiscordPostDefaultsResponse,
)
def get_discord_post_defaults(
    _interviewer: User = Depends(require_interviewer),
):
    settings = get_settings()
    service = _service()
    return DiscordPostDefaultsResponse(
        heading=settings.discord_default_heading,
        application_url=settings.job_post_default_application_url,
        contact_email=settings.job_post_default_contact_email,
        location=settings.job_post_default_location,
        application_deadline=settings.job_post_default_application_deadline,
        additional_instructions=settings.job_post_default_instructions,
        mcp_configured=service.publisher.is_configured(),
    )


@router.get(
    "/discord",
    response_model=list[DiscordJobPostResponse],
)
def list_discord_job_posts(
    job_description_id: int,
    db: Session = Depends(get_db),
    interviewer: User = Depends(require_interviewer),
):
    try:
        return _service().list_for_job(
            db,
            job_description_id=job_description_id,
            interviewer_user_id=interviewer.id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@router.post(
    "/discord/preview",
    response_model=DiscordJobPostResponse,
    status_code=status.HTTP_201_CREATED,
)
def preview_discord_job_post(
    data: DiscordPostPreviewRequest,
    db: Session = Depends(get_db),
    interviewer: User = Depends(require_interviewer),
):
    try:
        return _service().preview(
            db,
            data=data,
            interviewer_user_id=interviewer.id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except PublicationConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post(
    "/{posting_id}/publish",
    response_model=DiscordJobPostResponse,
)
def publish_discord_job_post(
    posting_id: int,
    _confirmation: DiscordPublishRequest,
    db: Session = Depends(get_db),
    interviewer: User = Depends(require_interviewer),
):
    try:
        return _service().publish(
            db,
            posting_id=posting_id,
            interviewer_user_id=interviewer.id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except (PublicationConflictError, StaleJobDescriptionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except DiscordConfigurationError as exc:
        raise HTTPException(status_code=503, detail=exc.safe_message) from None
    except DiscordDeliveryUncertainError as exc:
        raise HTTPException(status_code=504, detail=exc.safe_message) from None
    except DiscordPublishError as exc:
        raise HTTPException(status_code=502, detail=exc.safe_message) from None
