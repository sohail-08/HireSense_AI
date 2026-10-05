from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.rag.embeddings import OllamaEmbeddingProvider
from app.rag.service import KnowledgeBaseService
from app.schemas.knowledge import (
    KnowledgeDocumentCreate,
    KnowledgeDocumentResponse,
)
from app.security import require_interviewer


router = APIRouter(prefix="/api/knowledge", tags=["Knowledge Base"])


def _service() -> KnowledgeBaseService:
    return KnowledgeBaseService(OllamaEmbeddingProvider())


@router.post(
    "/documents",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_knowledge_document(
    data: KnowledgeDocumentCreate,
    db: Session = Depends(get_db),
    interviewer: User = Depends(require_interviewer),
):
    try:
        return _service().ingest_document(
            db,
            title=data.title,
            content=data.content,
            source_type=data.source_type,
            source_uri=data.source_uri,
            metadata=data.metadata,
            created_by_user_id=interviewer.id,
        )
    except RuntimeError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This knowledge document has already been added",
        ) from None


@router.get("/documents", response_model=list[KnowledgeDocumentResponse])
def list_knowledge_documents(
    db: Session = Depends(get_db),
    _interviewer: User = Depends(require_interviewer),
):
    return _service().list_documents(db)


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_knowledge_document(
    document_id: int,
    db: Session = Depends(get_db),
    _interviewer: User = Depends(require_interviewer),
):
    try:
        _service().delete_document(db, document_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
