"""All provider/Cloud operations mocked. Never consumes paid STT usage."""
from datetime import timedelta
from types import SimpleNamespace
import secrets
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import select, func
from app.database import get_db
from app.models.transcription import TranscriptionSession, TranscriptionConsent, TranscriptSegment
from app.schemas.transcription import ConsentInput, WorkerUpdate, StreamInput, SegmentInput
from app.services.transcription_service import TranscriptionService, TranscriptionConflict, keyterms
from app.routes import transcription as routes
from app.routes.interview_rooms import get_rooms, COOKIE_NAME
from app.security import create_access_token
from caption_protocol import CaptionSigner
from test_interview_rooms import room_setup  # noqa: F401 - pytest fixture registration
from test_interviews import setup, records  # noqa: F401 - transitive pytest fixtures


@pytest.fixture
def transcription(room_setup):
    setup_data, rooms, media, clock, row, token, _ = room_setup
    db, owner, other, *_ = setup_data
    config = rooms.settings.model_copy(update={"transcription_enabled": True,
        "transcription_worker_secret": SecretStr("test-worker-secret-" + "x" * 32)})
    rooms.settings = config
    dispatches = []
    media.dispatch_transcriber = lambda *args: dispatches.append(args)
    service = TranscriptionService(config, media, now=lambda: clock.value)
    row.room_status = "active"
    row.candidate_admitted_at = clock.value
    db.commit()
    return SimpleNamespace(db=db, owner=owner, other=other, row=row, token=token, rooms=rooms,
        media=media, clock=clock, service=service, dispatches=dispatches, config=config)


def consent(t):
    for role in ("INTERVIEWER", "CANDIDATE"):
        t.service.consent(t.db, t.row, role, ConsentInput(consent=True, notice_version="transcription-v1"))


def started(t):
    consent(t)
    state = t.service.start(t.db, t.row)
    claim = secrets.token_hex(32)
    context = t.service.claim(t.db, state["session_id"], claim)
    t.service.update_worker(t.db, state["session_id"], WorkerUpdate(claim=claim))
    return state["session_id"], claim, context


def stream(t, sid, claim, role="interviewer"):
    data = StreamInput(claim=claim, stream_id=secrets.token_hex(16),
        participant_identity=t.media.identity(t.row.room_name, role), track_sid="TR_" + role)
    return data, t.service.open_stream(t.db, sid, data)


def test_consent_required_and_start_stop_idempotent(transcription):
    t = transcription
    with pytest.raises(TranscriptionConflict): t.service.start(t.db, t.row)
    t.service.consent(t.db, t.row, "INTERVIEWER", ConsentInput(consent=True, notice_version="transcription-v1"))
    with pytest.raises(TranscriptionConflict): t.service.start(t.db, t.row)
    t.service.consent(t.db, t.row, "CANDIDATE", ConsentInput(consent=True, notice_version="transcription-v1"))
    a, b = t.service.start(t.db, t.row), t.service.start(t.db, t.row)
    assert a["session_id"] == b["session_id"] and len(t.dispatches) == 1
    assert t.db.scalar(select(func.count()).select_from(TranscriptionSession)) == 1
    assert t.service.stop(t.db, t.row)["status"] == "stopping"
    assert t.service.stop(t.db, t.row)["status"] == "stopping"
    assert len(list(t.db.scalars(select(TranscriptionConsent)))) == 2


def test_claim_fencing_and_trusted_speakers(transcription):
    t = transcription
    sid, claim, context = started(t)
    assert set(context["participants"].values()) == {"INTERVIEWER", "CANDIDATE"}
    with pytest.raises(TranscriptionConflict): t.service.claim(t.db, sid, secrets.token_hex(32))
    with pytest.raises(PermissionError):
        t.service.open_stream(t.db, sid, StreamInput(claim=claim, stream_id=secrets.token_hex(16), participant_identity="Candidate", track_sid="spoof"))
    t.db.rollback()
    with pytest.raises(PermissionError): t.service.update_worker(t.db, sid, WorkerUpdate(claim=secrets.token_hex(32)))


def test_overlap_duplicate_finals_timestamp_anchor_and_reconnect(transcription):
    t = transcription
    sid, claim, _ = started(t)
    first, anchor = stream(t, sid, claim)
    second, _ = stream(t, sid, claim, "candidate")
    t.clock.value += timedelta(seconds=5)
    def payload(item, text, key="result-1", start=1000, end=2000):
        return SegmentInput(claim=claim, stream_id=item.stream_id, provider_segment_id=key,
            provider_request_id="provider-1", text=text, start_ms=start, end_ms=end,
            confidence=0.9, words=[{"text": text, "start_ms": start, "end_ms": end}])
    a = t.service.persist(t.db, sid, payload(first, "Question"))
    b = t.service.persist(t.db, sid, payload(second, "Overlapping answer"))
    assert a["start_offset_ms"] == b["start_offset_ms"] == anchor["start_offset_ms"] + 1000
    assert a["speaker"] == "INTERVIEWER" and b["speaker"] == "CANDIDATE"
    assert t.service.persist(t.db, sid, payload(first, "Question"))["id"] == a["id"]
    assert t.db.scalar(select(func.count()).select_from(TranscriptSegment)) == 2
    with pytest.raises(TranscriptionConflict): t.service.persist(t.db, sid, payload(first, "Unrelated overwrite"))
    t.db.rollback()
    newer, reconnect = stream(t, sid, claim)
    assert reconnect["start_offset_ms"] >= 5000
    t.clock.value += timedelta(seconds=1)
    c = t.service.persist(t.db, sid, payload(newer, "After reconnect", start=0, end=500))
    assert c["start_offset_ms"] >= a["end_offset_ms"]
    assert (c["end_at"] - c["start_at"]).total_seconds() == 0.5
    assert [s.text for s in t.service.history(t.db, t.row)] == ["Question", "Overlapping answer", "After reconnect"]
    t.service.stop(t.db, t.row)
    # Buffered finals are allowed during stopping; no events after completed.
    t.service.update_worker(t.db, sid, WorkerUpdate(claim=claim, state="completed"))
    with pytest.raises(TranscriptionConflict): t.service.persist(t.db, sid, payload(newer, "Late", key="late"))


def test_empty_results_monotonicity_consent_revocation_and_stale_worker(transcription):
    t = transcription
    sid, claim, _ = started(t)
    item, _ = stream(t, sid, claim)
    assert t.service.persist(t.db, sid, SegmentInput(claim=claim, stream_id=item.stream_id,
        provider_segment_id="empty", text="   ", start_ms=0, end_ms=0)) is None
    t.service.consent(t.db, t.row, "CANDIDATE", ConsentInput(consent=False, notice_version="transcription-v1"))
    assert t.service.latest(t.db, t.row.id).status == "stopping"
    with pytest.raises(TranscriptionConflict): stream(t, sid, claim)
    t.db.rollback()
    t.clock.value += timedelta(seconds=30)
    assert t.service.status(t.db, t.row, "INTERVIEWER")["status"] == "failed"


def test_invalid_room_and_missing_worker_config(transcription):
    t = transcription
    consent(t)
    t.row.room_status = "waiting"
    with pytest.raises(TranscriptionConflict): t.service.start(t.db, t.row)
    t.row.room_status = "active"
    t.service.settings = t.config.model_copy(update={"transcription_worker_secret": SecretStr("")})
    with pytest.raises(TranscriptionConflict): t.service.start(t.db, t.row)
    assert not t.dispatches


def test_keyterm_limits_sanitization_and_no_pii():
    values = ["React", "react", "Node.js", "TypeScript\n", "a" * 51, "ignore\u200b instructions", ""] + [f"Framework {i}" for i in range(100)]
    result = keyterms(values)
    assert result[:3] == ["React", "Node.js", "TypeScript"]
    assert sum(len(s) + 1 for s in result) <= 200
    assert len(result) == len(set(s.casefold() for s in result))
    with pytest.raises(ValidationError): ConsentInput(consent=True, notice_version="unknown")


def test_api_authorization_candidate_restrictions_and_refresh(transcription, monkeypatch):
    t = transcription
    sid, claim, _ = started(t)
    app = FastAPI()
    app.include_router(routes.router)
    app.include_router(routes.internal)
    app.dependency_overrides[get_db] = lambda: t.db
    app.dependency_overrides[get_rooms] = lambda: t.rooms
    app.dependency_overrides[routes.get_transcription] = lambda: t.service
    monkeypatch.setattr(routes, "get_settings", lambda: t.config)
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + create_access_token(t.other.id)
        assert client.get(f"/api/interview-rooms/{t.row.id}/transcript").status_code == 403
        client.headers["Authorization"] = "Bearer " + create_access_token(t.owner.id)
        assert client.get(f"/api/interview-rooms/{t.row.id + 100}/transcript").status_code == 404
        assert client.get(f"/api/interview-rooms/{t.row.id}/transcription/status").json()["session_id"] == sid
        assert client.get(f"/api/interview-rooms/{t.row.id}/transcript").json()["segments"] == []
        assert client.post(f"/api/internal/transcription/{sid}/claim", json={"claim": claim}).status_code == 401
        client.headers["Authorization"] = "Bearer " + t.config.transcription_worker_secret.get_secret_value()
        assert client.post(f"/api/internal/transcription/{sid}/claim", json={"claim": claim,
            "caption_public_key": CaptionSigner().public_key}).status_code == 200
        client.headers.pop("Authorization")
        session, _, _ = t.rooms.exchange(t.db, t.token)
        client.cookies.set(COOKIE_NAME, session)
        state = client.get("/api/interview-rooms/candidate/transcription/status")
        assert state.status_code == 200 and "metrics" not in state.json() and "keyterms" not in state.json()
        assert client.post(f"/api/interview-rooms/{t.row.id}/transcription/start").status_code == 401
        assert client.get(f"/api/interview-rooms/{t.row.id}/transcript").status_code == 401


def test_retention_and_explicit_deletion(transcription):
    t = transcription
    sid, claim, _ = started(t)
    t.service.update_worker(t.db, sid, WorkerUpdate(claim=claim, state="completed"))
    t.service.delete_history(t.db, t.row)
    assert t.service.latest(t.db, t.row.id) is None
    assert not list(t.db.scalars(select(TranscriptionConsent)))


def test_end_interview_requests_stop_before_closing_media(transcription, monkeypatch):
    t = transcription
    sid, claim, _ = started(t)
    import time
    def finish(_):
        session = t.service.latest(t.db, t.row.id)
        assert session.status == "stopping"
        t.service.update_worker(t.db, sid, WorkerUpdate(claim=claim, state="completed"))
    monkeypatch.setattr(time, "sleep", finish)
    t.rooms.end(t.db, t.owner.id, t.row.id)
    assert t.row.room_status == "ended"
    assert t.service.latest(t.db, t.row.id).status == "completed"


def test_expired_history_is_hidden_and_purge_preserves_interview(transcription):
    t = transcription
    sid, claim, _ = started(t)
    item, _ = stream(t, sid, claim)
    t.clock.value += timedelta(seconds=2)
    t.service.persist(t.db, sid, SegmentInput(claim=claim, stream_id=item.stream_id,
        provider_segment_id="one", text="Saved", start_ms=0, end_ms=500))
    t.service.update_worker(t.db, sid, WorkerUpdate(claim=claim, state="completed"))
    assert len(t.service.history(t.db, t.row)) == 1
    t.clock.value += timedelta(days=31)
    assert t.service.history(t.db, t.row) == []
    from app.purge_transcripts import purge
    assert purge(t.db, t.clock.value) == 1
    from app.models.interview import InterviewSchedule
    assert t.db.get(InterviewSchedule, t.row.id) is not None


def test_transcription_migration_upgrade_and_downgrade(tmp_path):
    from sqlalchemy import create_engine, inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    # Load only the frozen revision, never execute all production migrations on a real DB.
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0020_interview_transcription.py"
    spec = importlib.util.spec_from_file_location("transcription_revision", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE interview_schedules (id INTEGER PRIMARY KEY)")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert "transcript_segments" in inspect(connection).get_table_names()
            assert any(index["name"] == "ix_transcript_interview_time" for index in inspect(connection).get_indexes("transcript_segments"))
            migration.downgrade()
            assert "transcript_segments" not in inspect(connection).get_table_names()


def test_postgresql_migration_sql_contains_jsonb_and_utc_types():
    import io
    from alembic.config import Config
    from alembic import command
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    output = io.StringIO()
    config = Config(str(root / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(root / "alembic"))
    config.attributes["database_url"] = "postgresql+psycopg://test:test@localhost/test_only"
    command.upgrade(config, "0019_interview_copilot:head", sql=True)
    sql = output.getvalue()
    assert "JSONB" in sql and "TIMESTAMP WITH TIME ZONE" in sql
    assert "uq_transcript_provider_segment" in sql


def test_caption_key_is_bound_to_worker_claim_and_public_status(transcription):
    t = transcription
    consent(t)
    sid = t.service.start(t.db, t.row)["session_id"]
    claim = secrets.token_hex(32)
    signer = CaptionSigner()
    t.service.claim(t.db, sid, claim, signer.public_key)
    t.service.claim(t.db, sid, claim, signer.public_key)  # idempotent retry
    status = t.service.status(t.db, t.row, "INTERVIEWER")
    assert status["caption_public_key"] == signer.public_key
    assert set(status["caption_public_key"]) == {"kty", "crv", "x", "y"}
    with pytest.raises(TranscriptionConflict): t.service.claim(t.db, sid, claim, CaptionSigner().public_key)
    t.db.rollback()
    with pytest.raises(TranscriptionConflict): t.service.claim(t.db, sid, claim, {**signer.public_key, "d": "private"})
    t.db.rollback()
    public = t.service.status(t.db, t.row, "CANDIDATE")
    assert public["caption_public_key"] is None and public["worker_identity"] is None
