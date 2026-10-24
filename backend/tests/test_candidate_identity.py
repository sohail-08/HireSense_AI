"""Privacy/state tests use generated blank pixels and deterministic vectors, not people."""
import io
import json
from datetime import timedelta
from types import SimpleNamespace
import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.database import get_db
from app.identity.face import FaceError, image_bytes, checked_model_paths
from app.models.identity import FaceReference, IdentityCheck
from app.routes import candidate_identity as routes
from app.routes.interview_rooms import COOKIE_NAME
from app.security import require_interviewer
from app.services.candidate_identity import CandidateIdentityService, NOTICE, cosine
from app.services.interview_rooms import RoomAccessError, RoomConflict
from test_interview_rooms import room_setup  # noqa: F401
from test_interviews import setup, records  # noqa: F401


def pixels():
    out = io.BytesIO()
    Image.new("RGB", (320, 320), "gray").save(out, format="PNG")
    return out.getvalue()


class Engine:
    version = "unit-test-vector-v1"
    def __init__(self):
        self.calls, self.hook, self.error = [], None, None
        self.vector = [1.] + [0.] * 127
    def embedding(self, data):
        self.calls.append(data)
        if self.hook:
            hook, self.hook = self.hook, None
            hook()
        if self.error:
            raise FaceError(self.error)
        return self.vector


class Reader:
    def __init__(self): self.downloads = 0
    def get_file(self, file_id):
        return SimpleNamespace(mime_type="image/png", size=len(pixels()))
    def download_file(self, *, file_id, destination, max_bytes):
        self.downloads += 1
        destination.write_bytes(pixels())


@pytest.fixture
def identity(room_setup, tmp_path):
    setup, rooms, media, clock, row, token, _ = room_setup
    db, owner, other = setup[:3]
    engine, reader = Engine(), Reader()
    service = CandidateIdentityService(settings=rooms.settings.model_copy(update={"storage_root": str(tmp_path)}),
        rooms=rooms, engine=engine, session_factory=lambda: Session(db.get_bind(), expire_on_commit=False))
    app = next(a for a in setup[4] if a.id == row.application_id)
    service.import_photo(db, app, reader, ["private-drive-file"])
    db.commit()
    cookie, _, _ = rooms.exchange(db, token)
    return SimpleNamespace(db=db, owner=owner, other=other, service=service, rooms=rooms,
        row=row, clock=clock, engine=engine, reader=reader, cookie=cookie, application=app, media=media)


def prepare(t, admit=True):
    state = t.service.live_consent(t.db, t.cookie, True)
    ref = t.service.reference(t.db, t.application.id)
    t.db.commit()
    t.service.process_reference(ref.id)
    t.db.expire_all()
    if admit:
        t.rooms.waiting(t.db, t.cookie)
        t.rooms.admit(t.db, t.owner.id, t.row.id)
    return t.service.candidate_state(t.db, t.cookie)


def test_import_encrypts_photo_but_never_embeds_before_app_consent(identity):
    t = identity
    ref = t.service.reference(t.db, t.application.id)
    assert ref.status == "pending_consent" and ref.consent == "pending"
    assert ref.photo_cipher and ref.embedding_cipher is None
    assert t.service.cipher().decrypt(ref.photo_cipher.encode()).startswith(b"\xff\xd8")
    t.db.commit()
    t.service.process_reference(ref.id)
    assert not t.engine.calls
    assert not t.service.candidate_state(t.db, t.cookie)["consented"]
    # The private runtime key is persistent and independent of JWT/link secrets.
    assert CandidateIdentityService(settings=t.service.settings).cipher().decrypt(ref.photo_cipher.encode())
    t.service.import_photo(t.db, t.application, t.reader, ["private-drive-file"])
    assert t.reader.downloads == 1


def test_consent_is_prejoin_but_match_requires_admission(identity):
    t = identity
    state = prepare(t, admit=False)
    assert state["consented"] and state["reference_ready"]
    ref = t.service.reference(t.db, t.application.id)
    assert ref.photo_cipher is None and ref.embedding_cipher
    with pytest.raises(RoomAccessError):
        t.service.verify(t.db, t.cookie, [pixels()] * 3, state["version"])
    assert len(t.engine.calls) == 1


@pytest.mark.parametrize("case", ["matched", "low_similarity", "no_face", "multiple_faces", "poor_image", "model_unavailable"])
def test_results_are_explicit_and_do_not_expose_templates(identity, case):
    t = identity
    state = prepare(t)
    if case == "low_similarity": t.engine.vector = [0., 1.] + [0.] * 126
    elif case != "matched": t.engine.error = case
    result = t.service.verify(t.db, t.cookie, [pixels()] * 3, state["version"])
    assert result["status"] == case
    assert "similarity" not in result and "embedding" not in json.dumps(result, default=str)
    own = t.service.interviewer_state(t.db, t.owner.id, t.row.id)
    assert own["status"] == case
    if case == "matched": assert own["similarity"] == 1
    with pytest.raises(RoomConflict):
        t.service.verify(t.db, t.cookie, [pixels()] * 3, state["version"])


@pytest.mark.parametrize("choice", ["decline", "withdraw"])
def test_decline_and_withdraw_destroy_data_and_resync_cannot_reenroll(identity, choice):
    t = identity
    prepare(t)
    if choice == "decline": t.service.live_consent(t.db, t.cookie, False)
    else: t.service.withdraw(t.db, t.cookie)
    ref = t.service.reference(t.db, t.application.id)
    assert ref.consent == "withdrawn" and not ref.embedding_cipher and not ref.photo_cipher
    t.service.import_photo(t.db, t.application, t.reader, ["changed-drive-file"])
    assert t.reader.downloads == 1
    with pytest.raises(RoomConflict): t.service.live_consent(t.db, t.cookie, True)
    t.db.rollback()
    assert not t.service.candidate_state(t.db, t.cookie)["consented"]


def test_withdrawal_during_inference_prevents_late_match(identity):
    t = identity
    state = prepare(t)
    def withdraw():
        with t.service.factory() as db:
            t.service.withdraw(db, t.cookie)
    t.engine.hook = withdraw
    with pytest.raises(RoomConflict, match="changed"):
        t.service.verify(t.db, t.cookie, [pixels()] * 3, state["version"])
    t.db.rollback()
    assert t.service.candidate_state(t.db, t.cookie)["status"] == "withdrawn"


def test_rejoin_and_reference_replacement_cannot_reuse_badge(identity):
    t = identity
    state = prepare(t)
    t.service.verify(t.db, t.cookie, [pixels()] * 3, state["version"])
    t.service.import_photo(t.db, t.application, t.reader, ["new-file"])
    t.db.commit()
    assert t.service.candidate_state(t.db, t.cookie)["status"] == "pending_consent"
    state = prepare(t)
    t.service.verify(t.db, t.cookie, [pixels()] * 3, state["version"])
    t.service.invalidate(t.db, t.row.id)
    t.db.commit()
    current = t.service.candidate_state(t.db, t.cookie)
    assert current["status"] == "not_checked" and not current["consented"]


def test_expiry_and_manual_fallback_are_separate_from_matching(identity):
    t = identity
    state = prepare(t)
    t.service.verify(t.db, t.cookie, [pixels()] * 3, state["version"])
    ref = t.service.reference(t.db, t.application.id)
    ref.expires_at = t.clock.value - timedelta(seconds=1)
    t.db.commit(); t.service.tick(); t.db.expire_all()
    assert t.service.candidate_state(t.db, t.cookie)["status"] == "expired"
    ref = t.service.reference(t.db, t.application.id)
    assert not ref.photo_cipher and not ref.embedding_cipher
    with pytest.raises(RoomConflict): t.service.manual(t.db, t.owner.id, t.row.id, "Confirmed in person")
    t.db.rollback()
    t.row.candidate_joined_at, t.row.room_status = t.clock.value, "active"
    t.db.commit()
    result = t.service.manual(t.db, t.owner.id, t.row.id, "Confirmed using the interview introduction.")
    assert result["status"] == "manual" and result["similarity"] is None
    with pytest.raises((RoomAccessError, LookupError, PermissionError)):
        t.service.interviewer_state(t.db, t.other.id, t.row.id)


def test_payload_bounds_and_cookie_origin_authorization(identity):
    t = identity
    app = FastAPI(); app.include_router(routes.router); app.add_middleware(routes.IdentityBodyLimit)
    app.dependency_overrides[get_db] = lambda: t.db
    app.dependency_overrides[routes.service] = lambda: t.service
    app.dependency_overrides[require_interviewer] = lambda: t.owner
    with TestClient(app) as client:
        assert client.get("/api/interview-rooms/candidate/identity").status_code == 401
        client.cookies.set(COOKIE_NAME, t.cookie)
        response = client.get("/api/interview-rooms/candidate/identity")
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        url = "/api/interview-rooms/candidate/identity/consent"
        assert client.post(url, json={"allow": True, "notice_version": NOTICE}, headers={"Origin": "https://evil.test"}).status_code == 403
        assert client.post(url, content=b"x" * 2_200_001).status_code == 413
        assert client.post(url, json={"allow": "yes", "notice_version": NOTICE}).status_code == 422
        verify = "/api/interview-rooms/candidate/identity/verify"
        assert client.post(verify, json={"frames": ["%%%"] * 3, "version": 1}).status_code in {403, 422}


def test_pixel_validation_and_model_integrity_fail_closed(tmp_path):
    assert image_bytes(pixels()).startswith(b"\xff\xd8")
    for data in (b"", b"not an image", b"x" * (3 * 1024 * 1024 + 1)):
        with pytest.raises(FaceError): image_bytes(data)
    with pytest.raises(FaceError, match="model_unavailable"): checked_model_paths(tmp_path)
    with pytest.raises(FaceError): cosine([float("nan")] * 128, [1.] * 128)
    with pytest.raises(FaceError): cosine([0.] * 128, [1.] * 128)


def test_intake_photo_is_optional_and_bound_to_existing_application_email(identity):
    from app.services.google_forms_intake_service import GoogleFormsIntakeService
    from app.models.candidate import Candidate
    t = identity
    intake = GoogleFormsIntakeService(t.reader, t.service.settings)
    warnings = []
    intake._import_face(t.db, t.application, [], {}, warnings)
    candidate = t.db.get(Candidate, t.application.candidate_id)
    intake._import_face(t.db, t.application, ["other@example.test", "private-drive-file"], {"email": 0, "photo": 1}, warnings)
    assert "identity needs review" in warnings[0]
    assert t.reader.downloads == 1
    warnings.clear()
    # An unchanged photo is idempotent and does not generate an embedding.
    intake._import_face(t.db, t.application, [candidate.email, "private-drive-file"], {"email": 0, "photo": 1}, warnings)
    assert not warnings and t.reader.downloads == 1 and not t.engine.calls


def test_disabled_feature_and_missing_models_never_return_a_match(identity):
    t = identity
    prepare(t)
    t.service.settings = t.service.settings.model_copy(update={"identity_enabled": False})
    current = t.service.candidate_state(t.db, t.cookie)
    assert current["status"] == "model_unavailable" and not current["reference_ready"]
    with pytest.raises(RoomConflict): t.service.verify(t.db, t.cookie, [pixels()]*3, current["version"])
