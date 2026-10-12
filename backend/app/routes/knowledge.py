from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from app.config import get_settings
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
from app.services.knowledge_pdf_service import KnowledgePDFService


router = APIRouter(prefix="/api/knowledge", tags=["Knowledge Base"])


def _service() -> KnowledgeBaseService:
    return KnowledgeBaseService(OllamaEmbeddingProvider())


def _pdf_service() -> KnowledgePDFService:
    return KnowledgePDFService(get_settings(), _service())


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
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except RuntimeError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This knowledge document has already been added",
        ) from None


@router.post(
    "/documents/upload",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_knowledge_document(
    file: UploadFile = File(...),
    title: str | None = Form(default=None, max_length=255),
    db: Session = Depends(get_db),
    interviewer: User = Depends(require_interviewer),
):
    try:
        return _pdf_service().upload(
            db,
            file=file,
            title=title,
            interviewer_user_id=interviewer.id,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from None
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
        _pdf_service().delete(db, document_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
