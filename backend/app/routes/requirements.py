from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.agents.requirement_discovery import OllamaRequirementModel
from app.database import get_db
from app.models.user import User
from app.rag.embeddings import OllamaEmbeddingProvider
from app.rag.service import KnowledgeBaseService
from app.schemas.requirements import (
    RequirementChatRequest,
    RequirementChatResponse,
)
from app.security import require_interviewer
from app.services.requirement_discovery_service import RequirementDiscoveryService


router = APIRouter(
    prefix="/api/requirements",
    tags=["Requirements"],
)


@router.post("/chat", response_model=RequirementChatResponse)
def chat_about_requirements(
    data: RequirementChatRequest,
    db: Session = Depends(get_db),
    interviewer: User = Depends(require_interviewer),
):
    service = RequirementDiscoveryService(
        OllamaRequirementModel(),
        KnowledgeBaseService(OllamaEmbeddingProvider()),
    )
    try:
        session, result = service.chat(
            db,
            interviewer_user_id=interviewer.id,
            message=data.message,
            session_id=data.session_id,
        )
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Requirement session not found",
        ) from None
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None

    return RequirementChatResponse(
        session_id=session.id,
        status=result["status"],
        assistant_message=result["assistant_message"],
        profile=result["profile"],
        missing_fields=result["missing_fields"],
        requirement_profile_id=session.requirement_profile_id,
        error=result["error"],
        error_code=result["error_code"],
        knowledge_status=result["knowledge_status"],
        proposal_ready=result["proposal_ready"],
        source_references=result["source_references"],
    )
