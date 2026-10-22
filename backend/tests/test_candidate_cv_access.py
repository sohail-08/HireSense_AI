import hashlib
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.routes import candidates
from app.security import create_access_token, require_interviewer
from test_screening import _records, _application_with_docx, _settings


@pytest.fixture
def files(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        owner, other, posting = _records(db)
        app, document = _application_with_docx(db, tmp_path, posting, 1)
        another, other_document = _application_with_docx(db, tmp_path, posting, 2)
        db.commit()
        settings = _settings(tmp_path)
        monkeypatch.setattr(candidates, "get_settings", lambda: settings)
        api = FastAPI(); api.include_router(candidates.router)
        api.dependency_overrides[get_db] = lambda: db
        with TestClient(api) as client:
            yield db, owner, other, app, document, another, other_document, tmp_path, client, api
    engine.dispose()


def url(application, document):
    return f"/api/candidates/applications/{application.id}/cvs/{document.id}"


def test_cv_requires_authentication_and_interviewer_role(files):
    db, owner, other, app, doc, _, _, _, client, _ = files
    assert client.get(url(app, doc)).status_code == 401
    assert client.get(url(app, doc), headers={"Authorization": "Bearer " + create_access_token(other.id)}).status_code == 403


def test_owned_docx_download_is_private_and_preserves_bytes(files):
    _, owner, _, app, doc, _, _, root, client, _ = files
    response = client.get(url(app, doc), headers={"Authorization": "Bearer " + create_access_token(owner.id)})
    assert response.status_code == 200
    assert response.content == (root / doc.storage_path).read_bytes()
    assert response.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["vary"] == "Authorization"


def test_pdf_opens_inline_or_downloads_without_exposing_a_storage_path(files):
    db, owner, _, app, doc, _, _, root, client, _ = files
    relative = f"cvs/{app.id}/synthetic.pdf"
    writer = PdfWriter(); writer.add_blank_page(width=200, height=200)
    with (root / relative).open("wb") as target: writer.write(target)
    doc.storage_path = relative; doc.original_filename = "Synthetic CV.pdf"
    doc.mime_type = "text/html"  # Stored MIME is never trusted for serving.
    content = (root / relative).read_bytes()
    doc.sha256 = hashlib.sha256(content).hexdigest(); doc.file_size_bytes = len(content)
    db.commit()
    headers = {"Authorization": "Bearer " + create_access_token(owner.id)}
    response = client.get(url(app, doc), headers=headers)
    assert response.status_code == 200 and response.content == content
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline;")
    assert str(root) not in str(response.headers)
    assert client.get(url(app, doc) + "?download=true", headers=headers).headers["content-disposition"].startswith("attachment;")


def test_mismatched_application_or_unowned_posting_is_not_found(files):
    db, owner, other, app, doc, another, _, root, client, api = files
    headers = {"Authorization": "Bearer " + create_access_token(owner.id)}
    assert client.get(url(another, doc), headers=headers).status_code == 404
    # Supply a different interviewer identity without weakening the role guard in production.
    api.dependency_overrides[require_interviewer] = lambda: other
    assert client.get(url(app, doc), headers=headers).status_code == 404


@pytest.mark.parametrize("reference", ["../outside.docx", "outside.docx", "cvs/missing.docx"])
def test_invalid_or_missing_private_reference_never_leaks_paths(files, reference):
    db, owner, _, app, doc, _, _, root, client, _ = files
    doc.storage_path = reference; db.commit()
    response = client.get(url(app, doc), headers={"Authorization": "Bearer " + create_access_token(owner.id)})
    assert response.status_code == 404
    assert str(root) not in response.text and reference not in response.text


def test_tampered_file_is_not_served(files):
    _, owner, _, app, doc, _, _, root, client, _ = files
    with (root / doc.storage_path).open("ab") as target: target.write(b"tampered")
    response = client.get(url(app, doc), headers={"Authorization": "Bearer " + create_access_token(owner.id)})
    assert response.status_code == 409 and "could not be verified" in response.text


def test_deleted_document_and_cross_candidate_reference_are_not_served(files):
    db, owner, _, app, doc, _, other_doc, _, client, _ = files
    headers = {"Authorization": "Bearer " + create_access_token(owner.id)}
    assert client.get(url(app, other_doc), headers=headers).status_code == 404
    db.delete(doc); db.commit()
    assert client.get(url(app, doc), headers=headers).status_code == 404


def test_a_zip_renamed_to_docx_is_not_served(files):
    db, owner, _, app, doc, _, _, root, client, _ = files
    path = root / doc.storage_path
    with zipfile.ZipFile(path, "w") as archive: archive.writestr("not-a-cv.txt", "Synthetic non-Word archive")
    doc.sha256 = hashlib.sha256(path.read_bytes()).hexdigest(); db.commit()
    assert client.get(url(app, doc), headers={"Authorization": "Bearer " + create_access_token(owner.id)}).status_code == 409


def test_filename_is_sanitized_without_leaking_directories(files):
    db, owner, _, app, doc, _, _, _, client, _ = files
    doc.original_filename = "private/folder/Synthetic\r\n CV.docx"; db.commit()
    response = client.get(url(app, doc), headers={"Authorization": "Bearer " + create_access_token(owner.id)})
    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert "private" not in disposition and "folder" not in disposition and "\r" not in disposition and "\n" not in disposition


def test_symlink_cannot_escape_the_cv_directory(files):
    db, owner, _, app, doc, _, _, root, client, _ = files
    link = root / "cvs" / "escape"
    try: link.symlink_to(root, target_is_directory=True)
    except OSError: pytest.skip("Creating symlinks requires permission on this host")
    (root / "other.docx").write_bytes((root / doc.storage_path).read_bytes())
    doc.storage_path = "cvs/escape/other.docx"; db.commit()
    response = client.get(url(app, doc), headers={"Authorization": "Bearer " + create_access_token(owner.id)})
    assert response.status_code == 404
