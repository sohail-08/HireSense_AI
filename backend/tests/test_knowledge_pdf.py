from io import BytesIO
from pathlib import Path

import pytest
from fastapi import UploadFile
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, StreamObject
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from starlette.datastructures import Headers

from app.config import Settings
from app.database import Base
from app.models import KnowledgeChunk, KnowledgeDocument, User, UserRole
from app.rag.embeddings import HashEmbeddingProvider
from app.rag.service import KnowledgeBaseService
from app.services.knowledge_pdf_service import KnowledgePDFService


def _settings(storage_root: Path) -> Settings:
    return Settings(
        database_url="sqlite://",
        jwt_secret_key="test-jwt-secret-key-with-at-least-32-characters",
        interviewer_email="interviewer@example.com",
        interviewer_password="StrongInterviewerPassword123!",
        storage_root=str(storage_root),
    )


def _upload(filename: str = "Backend Engineer.pdf") -> UploadFile:
    return UploadFile(
        file=BytesIO(b"%PDF-synthetic-test"),
        filename=filename,
        headers=Headers({"content-type": "application/pdf"}),
    )


def _text_pdf_upload() -> UploadFile:
    output = BytesIO()
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): writer._add_object(font)}
            )
        }
    )
    content = StreamObject()
    content.set_data(
        b"BT /F1 12 Tf 72 720 Td "
        b"(Backend engineer builds Python APIs and PostgreSQL services.) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(content)
    writer.write(output)
    output.seek(0)
    return UploadFile(
        file=output,
        filename="Previous Backend JD.pdf",
        headers=Headers({"content-type": "application/pdf"}),
    )


def test_pdf_upload_indexes_text_and_delete_removes_file(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'knowledge-pdf.db'}")
    Base.metadata.create_all(engine)
    settings = _settings(tmp_path / "storage")
    service = KnowledgePDFService(
        settings,
        KnowledgeBaseService(HashEmbeddingProvider()),
    )
    service._extract_text = lambda _path: (
        "Backend engineers build Python APIs and PostgreSQL services.",
        2,
        [],
    )

    with Session(engine) as db:
        interviewer = User(
            name="Interviewer",
            email="pdf@example.com",
            password_hash="hashed-password",
            role=UserRole.INTERVIEWER,
        )
        db.add(interviewer)
        db.commit()

        document = service.upload(
            db,
            file=_upload(),
            title=None,
            interviewer_user_id=interviewer.id,
        )

        assert document.title == "Backend Engineer"
        assert document.metadata_json["uploaded_pdf"] is True
        assert document.metadata_json["page_count"] == 2
        stored = Path(settings.storage_root) / str(document.source_uri)
        assert stored.read_bytes() == b"%PDF-synthetic-test"
        assert db.scalar(select(func.count(KnowledgeChunk.id))) == 1

        document_id = document.id
        service.delete(db, document_id)

        assert db.get(KnowledgeDocument, document_id) is None
        assert db.scalar(select(func.count(KnowledgeChunk.id))) == 0
        assert not stored.exists()


def test_pdf_upload_rejects_non_pdf_extension(tmp_path):
    service = KnowledgePDFService(
        _settings(tmp_path / "storage"),
        KnowledgeBaseService(HashEmbeddingProvider()),
    )

    with pytest.raises(ValueError, match="Only PDF"):
        service.upload(
            Session(create_engine("sqlite://")),
            file=_upload("previous-job-description.txt"),
            title=None,
            interviewer_user_id=1,
        )


def test_pdf_text_extraction_uses_real_pypdf_document(tmp_path):
    service = KnowledgePDFService(
        _settings(tmp_path / "storage"),
        KnowledgeBaseService(HashEmbeddingProvider()),
    )
    pdf = _text_pdf_upload()
    source = tmp_path / "previous-jd.pdf"
    source.write_bytes(pdf.file.read())

    content, page_count, warnings = service._extract_text(source)

    assert page_count == 1
    assert warnings == []
    assert "Backend engineer builds Python APIs" in content
