"""Profile-image display uses ordinary pixel sanitization, never face inference."""
from types import SimpleNamespace
import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.database import get_db
from app.models.candidate import ApplicationSource
from app.routes import candidate_photos as routes
from app.routes.interview_rooms import COOKIE_NAME
from app.security import create_access_token
from app.services.candidate_photo import CandidatePhotoService, CandidatePhotoUnavailable
from test_candidate_identity import identity, Reader, pixels, prepare  # noqa: F401
from test_interview_rooms import room_setup  # noqa: F401
from test_interviews import setup, records  # noqa: F401


def test_main_app_registers_candidate_photo_route():
    from app.main import app
    assert "get" in app.openapi()["paths"]["/api/interview-rooms/{interview_id}/candidate-photo"]


@pytest.fixture
def photo(identity):
    t = identity
    t.application.source = ApplicationSource.GOOGLE_FORM
    t.application.response_data = {"Candidate photo": "https://drive.google.com/open?id=profile-photo-file-12345"}
    t.db.commit()
    t.photo_reader = Reader()
    t.photos = CandidatePhotoService(t.service.settings, reader=t.photo_reader, rooms=t.rooms)
    return t


def test_uploaded_photo_is_sanitized_and_available_after_biometric_copy_is_deleted(photo):
    t = photo
    prepare(t)  # Mock face engine only; no real person or external provider.
    assert t.service.reference(t.db, t.application.id).photo_cipher is None
    calls = len(t.engine.calls)
    result = t.photos.photo(t.db, t.owner.id, t.row.id)
    with Image.open(io.BytesIO(result)) as image:
        assert image.format == "JPEG" and image.size == (320, 320)
        assert not image.getexif()
    assert t.photo_reader.downloads == 1 and len(t.engine.calls) == calls
    # This is an original application upload, not a retained biometric photo.
    assert t.service.reference(t.db, t.application.id).photo_cipher is None


def test_profile_photo_does_not_reenroll_or_restore_withdrawn_biometrics(photo):
    t = photo
    t.service.withdraw(t.db, t.cookie)
    t.photos.photo(t.db, t.owner.id, t.row.id)
    ref = t.service.reference(t.db, t.application.id)
    assert ref.consent == "withdrawn" and ref.photo_cipher is None and ref.embedding_cipher is None
    assert not t.engine.calls


@pytest.mark.parametrize("record", [{}, {"Candidate photo": ""},
    {"Candidate photo": "https://drive.google.com/open?id=first-file-12345, https://drive.google.com/open?id=second-file-12345"}])
def test_missing_or_ambiguous_photo_never_contacts_google(photo, record):
    t = photo
    t.application.response_data = record; t.db.commit()
    with pytest.raises(LookupError):
        t.photos.photo(t.db, t.owner.id, t.row.id)
    assert t.photo_reader.downloads == 0


def test_wrong_interview_owner_is_rejected_before_reading_files(photo):
    t = photo
    t.row.created_by_user_id = t.other.id
    t.db.commit()
    with pytest.raises(LookupError): t.photos.photo(t.db, t.owner.id, t.row.id)
    assert t.photo_reader.downloads == 0


@pytest.mark.parametrize("problem", ["oversized", "wrong_type", "invalid_bytes", "provider_error"])
def test_unavailable_images_fail_without_exposing_private_provider_details(photo, problem):
    t = photo
    if problem == "oversized":
        t.photo_reader.get_file = lambda file_id: SimpleNamespace(mime_type="image/png", size=4*1024*1024)
    elif problem == "wrong_type":
        t.photo_reader.get_file = lambda file_id: SimpleNamespace(mime_type="text/html", size=20)
    elif problem == "invalid_bytes":
        t.photo_reader.download_file = lambda **kwargs: kwargs["destination"].write_bytes(b"not an image")
    elif problem == "provider_error":
        t.photo_reader.get_file = lambda file_id: (_ for _ in ()).throw(RuntimeError("PRIVATE file ID and credential path"))
    with pytest.raises(CandidatePhotoUnavailable) as failure:
        t.photos.photo(t.db, t.owner.id, t.row.id)
    assert "PRIVATE" not in str(failure.value) and not t.engine.calls


def test_changed_source_during_download_cannot_show_stale_photo(photo):
    t = photo
    def replace(**kwargs):
        kwargs["destination"].write_bytes(pixels())
        t.application.response_data = {"Candidate photo": "https://drive.google.com/open?id=replaced-photo-12345"}
        t.db.commit()
    t.photo_reader.download_file = replace
    with pytest.raises(LookupError, match="changed"):
        t.photos.photo(t.db, t.owner.id, t.row.id)


def test_photo_route_is_interviewer_only_and_never_publicly_cached(photo):
    t = photo
    app = FastAPI(); app.include_router(routes.router)
    app.dependency_overrides[get_db] = lambda: t.db
    app.dependency_overrides[routes.service] = lambda: t.photos
    url = f"/api/interview-rooms/{t.row.id}/candidate-photo"
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, t.cookie)
        assert client.get(url).status_code == 401
        assert t.photo_reader.downloads == 0
        denied = client.get(url, headers={"Authorization": "Bearer " + create_access_token(t.other.id)})
        assert denied.status_code == 403 and t.photo_reader.downloads == 0
        response = client.get(url, headers={"Authorization": "Bearer " + create_access_token(t.owner.id)})
        assert response.status_code == 200 and response.headers["content-type"] == "image/jpeg"
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["vary"] == "Authorization"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.content.startswith(b"\xff\xd8")
        assert "drive.google" not in response.text
