import logging
import re
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.knowledge import KnowledgeDocument, KnowledgeSourceType
from app.rag.chunking import normalize_text
from app.rag.service import KnowledgeBaseService


ALLOWED_PDF_CONTENT_TYPES = {
    "application/pdf",
    "application/octet-stream",
}
logger = logging.getLogger(__name__)


class KnowledgePDFService:
    def __init__(
        self,
        settings: Settings,
        knowledge_base: KnowledgeBaseService,
    ):
        self.settings = settings
        self.knowledge_base = knowledge_base

    def upload(
        self,
        db: Session,
        *,
        file: UploadFile,
        title: str | None,
        interviewer_user_id: int,
    ) -> KnowledgeDocument:
        supplied_filename = Path(file.filename or "").name
        if Path(supplied_filename).suffix.lower() != ".pdf":
            raise ValueError("Only PDF knowledge documents are accepted")
        original_filename = self._safe_filename(supplied_filename)
        if (
            file.content_type
            and file.content_type not in ALLOWED_PDF_CONTENT_TYPES
        ):
            raise ValueError("The uploaded file is not a PDF")

        root = self._knowledge_root()
        token = uuid4().hex
        temporary = (root / f".{token}.upload").resolve()
        final = (root / f"{token}_{original_filename}").resolve()
        max_bytes = self.settings.knowledge_pdf_max_file_size_mb * 1024 * 1024

        try:
            size = self._copy_upload(file, temporary, max_bytes)
            with temporary.open("rb") as source:
                if source.read(5) != b"%PDF-":
                    raise ValueError("The uploaded file is not a valid PDF")

            content, page_count, warnings = self._extract_text(temporary)
            temporary.replace(final)
            relative_path = final.relative_to(
                Path(self.settings.storage_root).expanduser().resolve()
            ).as_posix()
            resolved_title = (title or "").strip() or Path(original_filename).stem
            document = self.knowledge_base.ingest_document(
                db,
                title=resolved_title,
                content=content,
                source_type=KnowledgeSourceType.PREVIOUS_JOB_DESCRIPTION,
                source_uri=relative_path,
                metadata={
                    "uploaded_pdf": True,
                    "original_filename": original_filename,
                    "mime_type": "application/pdf",
                    "file_size_bytes": size,
                    "page_count": page_count,
                    "extracted_characters": len(content),
                    "extraction_warnings": warnings,
                },
                created_by_user_id=interviewer_user_id,
            )
            if document.source_uri != relative_path:
                final.unlink(missing_ok=True)
            return document
        except Exception:
            temporary.unlink(missing_ok=True)
            if final.exists():
                final.unlink(missing_ok=True)
            raise
        finally:
            file.file.close()

    def delete(self, db: Session, document_id: int) -> None:
        document = db.get(KnowledgeDocument, document_id)
        if document is None:
            raise LookupError("Knowledge document not found")
        stored_path = self._stored_pdf_path(document.source_uri)
        self.knowledge_base.delete_document(db, document_id)
        if stored_path is not None:
            try:
                stored_path.unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "Could not remove deleted knowledge PDF %s",
                    stored_path,
                )

    def _copy_upload(
        self,
        file: UploadFile,
        destination: Path,
        max_bytes: int,
    ) -> int:
        total = 0
        with destination.open("wb") as target:
            while chunk := file.file.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(
                        "PDF exceeds the configured "
                        f"{self.settings.knowledge_pdf_max_file_size_mb} MB limit"
                    )
                target.write(chunk)
        if total == 0:
            raise ValueError("The uploaded PDF is empty")
        return total

    def _extract_text(self, path: Path) -> tuple[str, int, list[str]]:
        try:
            reader = PdfReader(str(path))
            if reader.is_encrypted:
                raise ValueError("Password-protected PDFs are not supported")
            page_count = len(reader.pages)
            if page_count == 0:
                raise ValueError("The PDF does not contain any pages")
            if page_count > self.settings.knowledge_pdf_max_pages:
                raise ValueError(
                    "PDF exceeds the configured "
                    f"{self.settings.knowledge_pdf_max_pages}-page limit"
                )

            page_text: list[str] = []
            empty_pages: list[int] = []
            for index, page in enumerate(reader.pages, start=1):
                extracted = normalize_text(page.extract_text() or "")
                if extracted:
                    page_text.append(extracted)
                else:
                    empty_pages.append(index)
        except PdfReadError as exc:
            raise ValueError("The uploaded PDF could not be read") from exc

        content = normalize_text("\n\n".join(page_text))
        if not content:
            raise ValueError(
                "No selectable text was found in the PDF. "
                "Scanned image-only PDFs require OCR before upload."
            )
        warnings = (
            [
                "No selectable text was found on page(s): "
                + ", ".join(str(page) for page in empty_pages)
            ]
            if empty_pages
            else []
        )
        return content, page_count, warnings

    def _knowledge_root(self) -> Path:
        storage_root = Path(self.settings.storage_root).expanduser().resolve()
        root = (storage_root / "knowledge").resolve()
        if storage_root not in root.parents:
            raise ValueError("Knowledge storage escaped the private storage root")
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _stored_pdf_path(self, source_uri: str | None) -> Path | None:
        if not source_uri or not source_uri.startswith("knowledge/"):
            return None
        storage_root = Path(self.settings.storage_root).expanduser().resolve()
        path = (storage_root / source_uri).resolve()
        knowledge_root = (storage_root / "knowledge").resolve()
        if knowledge_root not in path.parents:
            raise ValueError("Knowledge PDF path escaped private storage")
        return path

    @staticmethod
    def _safe_filename(value: str) -> str:
        stem = Path(Path(value).name).stem
        stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", stem).strip(" .")
        return f"{(stem or 'previous-job-description')[:240]}.pdf"
