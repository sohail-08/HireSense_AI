from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.agents.job_description import (
    GeminiJobDescriptionEditModel,
    GeminiJobDescriptionModel,
)
from app.agents.job_posting import GeminiPostingCommandModel
from app.agents.requirement_discovery import GeminiRequirementModel
from app.agents.supervisor import GeminiSupervisorModel
from app.database import get_db
from app.config import get_settings
from app.integrations.google_workspace import GoogleServiceAccountReader
from app.routes.screening import _process_batch
from app.models.user import User
from app.rag.embeddings import OllamaEmbeddingProvider
from app.rag.service import KnowledgeBaseService
from app.schemas.supervisor import (
    SupervisorChatRequest,
    SupervisorChatResponse,
)
from app.security import require_interviewer
from app.services.job_description_service import JobDescriptionService
from app.services.job_posting_assistant_service import JobPostingAssistantService
from app.services.requirement_discovery_service import RequirementDiscoveryService
from app.services.supervisor_service import SupervisorService
from app.services.google_forms_intake_service import GoogleFormsIntakeService
from app.services.screening_service import ScreeningService
from app.services.interview_assistant_service import InterviewAssistantService


router = APIRouter(prefix="/api/supervisor", tags=["Supervisor"])


def _service() -> SupervisorService:
    settings = get_settings()
    return SupervisorService(
        model=GeminiSupervisorModel(),
        requirement_service=RequirementDiscoveryService(
            GeminiRequirementModel(),
            KnowledgeBaseService(OllamaEmbeddingProvider()),
        ),
        job_description_service=JobDescriptionService(
            GeminiJobDescriptionModel(),
            KnowledgeBaseService(OllamaEmbeddingProvider()),
        ),
        job_edit_model=GeminiJobDescriptionEditModel(),
        job_posting_service=JobPostingAssistantService(
            GeminiPostingCommandModel(),
        ),
        candidate_intake_factory=lambda: GoogleFormsIntakeService(
            GoogleServiceAccountReader(settings.google_service_account_file), settings,
        ),
        screening_service=ScreeningService(settings),
        interview_service=InterviewAssistantService(),
    )


@router.post("/chat", response_model=SupervisorChatResponse)
def chat_with_supervisor(
    data: SupervisorChatRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    interviewer: User = Depends(require_interviewer),
):
    try:
        result = _service().chat(
            db,
            interviewer_user_id=interviewer.id,
            message=data.message,
            session_id=data.session_id,
            selected_job_description_id=data.selected_job_description_id,
            page_context=data.page_context,
            selected_job_posting_id=data.selected_job_posting_id,
            selected_application_ids=data.selected_application_ids,
        )
        if result.pop("screening_started", False):
            background_tasks.add_task(_process_batch, result["screening_batch"]["id"])
        return result
    except (LookupError, PermissionError) as exc:
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


@router.get(
    "/sessions/{session_id}",
    response_model=SupervisorChatResponse,
)
def get_supervisor_session(
    session_id: str,
    db: Session = Depends(get_db),
    interviewer: User = Depends(require_interviewer),
):
    try:
        return _service().get_session(
            db,
            interviewer_user_id=interviewer.id,
            session_id=session_id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from None
