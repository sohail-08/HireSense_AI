import json
import secrets
from datetime import datetime, timedelta, timezone, date
from types import SimpleNamespace
import jwt
import pytest
from sqlalchemy import select, func
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.exceptions import RequestValidationError
from pydantic import SecretStr
from icalendar import Calendar
from app.database import get_db
from app.models.interview import InterviewBatch, InterviewSchedule, InterviewDelivery, CandidateInterviewSession
from app.models.user import User, UserRole
from app.services.interview_rooms import InterviewRooms, RoomAccessError, RoomConflict
from app.services.interview_links import InterviewLinks, JOIN_PLACEHOLDER, secret_hash, redact_join_links
from app.services.interview_content import utc
from app.integrations.livekit_media import LiveKitMedia, MediaUnavailable
from app.routes import interview_rooms as routes
from app.schemas.interview import RescheduleRequest
from app.security import create_access_token
from test_interviews import setup, records, prepared, confirm_data, schedule_data

UTC = timezone.utc


class FakeMedia:
    def __init__(self, settings):
        self.settings, self.created, self.closed, self.tokens, self.present = settings, [], [], [], []
        self.fail_close = False
    identity = staticmethod(LiveKitMedia.identity)
    def ensure_room(self, name): self.created.append(name)
    def close_room(self, name):
        if self.fail_close: raise MediaUnavailable("Mock media unavailable")
        self.closed.append(name)
        self.present = []
    def participants(self, name): return self.present
    def token(self, room, role, expires):
        self.tokens.append((room, role))
        return LiveKitMedia(self.settings).token(room, role, expires)


@pytest.fixture
def room_setup(setup):
    db, owner, other, posting, apps, run, service, sender = setup
    config = service.settings.model_copy(update={"livekit_cloud_api_key": "test-room-key",
        "livekit_cloud_url": "wss://test-project.livekit.cloud",
        "livekit_cloud_api_secret": SecretStr("test-only-media-secret-" + "x" * 40),
        "interview_link_secret": SecretStr("test-only-invite-secret-" + "y" * 40),
        "candidate_cookie_secure": False, "frontend_url": "http://testserver"})
    service.settings, service.links = config, InterviewLinks(config)
    preview = prepared(setup, count=1)
    service.confirm(db, owner.id, preview["id"], confirm_data(preview))
    row = db.scalar(select(InterviewSchedule))
    clock = SimpleNamespace(value=row.start_utc.replace(tzinfo=UTC) - timedelta(minutes=10))
    media = FakeMedia(config)
    rooms = InterviewRooms(config, media=media, now=lambda: clock.value)
    token = preview["recipients"][0]["join_url"].rsplit("/", 1)[-1]
    return setup, rooms, media, clock, row, token, preview


def test_join_link_and_candidate_session_are_hash_only_and_scoped(room_setup):
    setup, rooms, _, _, row, token, preview = room_setup
    db, owner, _, _, _, _, service, _ = setup
    assert row.join_token_hash == secret_hash(token) and row.join_token_hash != token
    other_material = rooms.links.material(row.application_id, row.start_utc, row.end_utc)
    assert rooms.links.token(other_material) != token
    session_token, expires, info = rooms.exchange(db, token)
    persisted = db.scalar(select(CandidateInterviewSession))
    assert persisted.session_hash == secret_hash(session_token) and persisted.application_id == row.application_id
    assert persisted.interview_id == row.id and utc(persisted.expires_at) == expires
    assert "candidate_name" not in info and "email" not in json.dumps(info, default=str)
    assert rooms.link(db, owner.id, row.id, retrieve_only=True)["join_url"] == preview["recipients"][0]["join_url"]
    for entity in (db.scalar(select(InterviewBatch)), db.scalar(select(InterviewDelivery))):
        values = {column.name: getattr(entity, column.name) for column in entity.__table__.columns}
        assert token not in json.dumps(values, default=str)
    assert session_token not in str(persisted.__dict__)
    with pytest.raises(RoomAccessError): rooms.exchange(db, secrets.token_urlsafe(32))
    with pytest.raises(RoomAccessError): rooms.session(db, secrets.token_urlsafe(32))
    rooms.waiting(db, session_token)
    rooms.admit(db, owner.id, row.id)
    with pytest.raises(RoomAccessError): rooms.media_access(db, candidate_token=session_token, interview_id=row.id + 1)


def test_link_lifetime_and_nested_snapshot_redaction(room_setup):
    _, rooms, _, clock, row, token, preview = room_setup
    url = preview["recipients"][0]["join_url"]
    state = redact_join_links({"messages": [{"body": "Join: " + url}], "link": url})
    assert token not in json.dumps(state) and JOIN_PLACEHOLDER in state["link"]
    far = clock.value + timedelta(days=rooms.settings.interview_link_max_days + 1)
    material = rooms.links.material(row.application_id, far, far + timedelta(minutes=30))
    assert datetime.fromisoformat(material["expires_at"]) == clock.value + timedelta(days=rooms.settings.interview_link_max_days)


def test_public_website_reports_missing_cloud_settings_and_outdated_links(room_setup):
    setup, rooms, media, _, row, token, _ = room_setup
    db, owner, _, _, _, _, _, _ = setup
    rooms.settings = rooms.settings.model_copy(update={'frontend_url': 'https://demo.trycloudflare.com',
        'interview_join_base_url': 'https://demo.trycloudflare.com', 'candidate_cookie_secure': True,
        'livekit_cloud_url': ''})
    rooms.links = InterviewLinks(rooms.settings, rooms.now)
    info = rooms.info(db, row, interviewer=True)
    assert 'LIVEKIT_CLOUD_URL' in info['media_notice'] and info['link_origin_outdated']
    cookie, _, _ = rooms.exchange(db, token)
    rooms.waiting(db, cookie); rooms.admit(db, owner.id, row.id)
    with pytest.raises(MediaUnavailable, match='LIVEKIT_CLOUD_URL'):
        rooms.media_access(db, candidate_token=cookie)
    with pytest.raises(MediaUnavailable): rooms.media_access(db, user_id=owner.id, interview_id=row.id)
    assert not media.created and not media.tokens
    rooms.settings = rooms.settings.model_copy(update={'livekit_cloud_url': 'wss://test-project.livekit.cloud'})
    assert rooms.media_notice() is None


def test_explicit_rotation_updates_invitation_to_demo_origin(room_setup):
    setup, rooms, _, _, row, token, _ = room_setup
    db, owner, _, _, _, _, _, _ = setup
    rooms.settings = rooms.settings.model_copy(update={'interview_join_base_url': 'https://demo.trycloudflare.com'})
    rooms.links = InterviewLinks(rooms.settings, rooms.now)
    replacement = rooms.link(db, owner.id, row.id, rotate=True)
    assert replacement['join_url'].startswith('https://demo.trycloudflare.com/interview/join/')
    assert not rooms.info(db, row, interviewer=True)['link_origin_outdated']
    with pytest.raises(RoomAccessError): rooms.exchange(db, token)


def test_cloud_room_uses_cloud_credentials_and_preserves_admission_and_end(room_setup):
    setup, rooms, media, _, row, token, _ = room_setup
    db, owner, _, _, _, _, _, _ = setup
    rooms.settings = rooms.settings.model_copy(update={
        'livekit_cloud_url': 'wss://test-project.livekit.cloud',
        'livekit_cloud_api_key': 'test-cloud-key', 'livekit_cloud_api_secret': SecretStr('cloud-test-secret-' + 'c' * 32),
        'frontend_url': 'https://demo.trycloudflare.com'})
    media.settings = rooms.settings
    assert rooms.info(db, row)['media_notice'] is None
    cookie, _, _ = rooms.exchange(db, token)
    with pytest.raises(RoomAccessError): rooms.media_access(db, candidate_token=cookie)
    rooms.waiting(db, cookie); rooms.admit(db, owner.id, row.id)
    access = rooms.media_access(db, candidate_token=cookie)
    assert access['server_url'] == 'wss://test-project.livekit.cloud'
    decoded = jwt.decode(access['participant_token'], rooms.settings.livekit_cloud_api_secret.get_secret_value(),
                         algorithms=['HS256'], issuer='test-cloud-key')
    assert decoded['sub'] == row.room_name + '-c'
    assert decoded['video']['room'] == row.room_name and not decoded['video']['roomAdmin']
    rooms.end(db, owner.id, row.id)
    with pytest.raises(RoomAccessError): rooms.media_access(db, candidate_token=cookie)


def test_missing_cloud_credentials_keep_joining_disabled(room_setup):
    setup, rooms, media, _, row, _, _ = room_setup
    db, owner, _, _, _, _, _, _ = setup
    rooms.settings = rooms.settings.model_copy(update={'livekit_cloud_url': '',
        'livekit_cloud_api_key': '', 'livekit_cloud_api_secret': SecretStr('')})
    assert 'LIVEKIT_CLOUD_URL' in rooms.info(db, row)['media_notice']
    with pytest.raises(MediaUnavailable): rooms.media_access(db, user_id=owner.id, interview_id=row.id)
    assert not media.created and not media.tokens


@pytest.mark.parametrize("case,code", [("expired", "expired_link"), ("revoked", "revoked_link"),
    ("cancelled", "cancelled"), ("ended", "ended")])
def test_invalid_lifecycle_and_expired_credentials_reject_candidate(room_setup, case, code):
    setup, rooms, _, clock, row, token, _ = room_setup
    db = setup[0]
    if case == "expired": row.join_token_expires_at = clock.value - timedelta(seconds=1)
    elif case == "revoked": row.join_token_revoked_at = clock.value
    elif case == "cancelled": row.status = "cancelled"
    elif case == "ended": row.room_status = "ended"
    db.commit()
    with pytest.raises(RoomAccessError) as error: rooms.exchange(db, token)
    assert error.value.code == code and "Candidate" not in str(error.value)


@pytest.mark.parametrize("offset", [timedelta(days=-1), timedelta(days=2)])
def test_candidates_and_interviewers_can_join_outside_the_booked_slot(room_setup, offset):
    setup, rooms, media, clock, row, token, _ = room_setup
    db, owner, _, _, _, _, _, _ = setup
    clock.value = utc(row.start_utc) + offset
    cookie, expiry, info = rooms.exchange(db, token)
    assert expiry == min(clock.value + timedelta(minutes=rooms.settings.candidate_session_minutes), utc(row.join_token_expires_at))
    assert "join_opens_at" not in info and "join_closes_at" not in info
    assert rooms.waiting(db, cookie)["waiting"]
    with pytest.raises(RoomAccessError): rooms.media_access(db, candidate_token=cookie)
    rooms.admit(db, owner.id, row.id)
    assert rooms.media_access(db, candidate_token=cookie)["role"] == "candidate"
    assert rooms.media_access(db, user_id=owner.id, interview_id=row.id)["role"] == "interviewer"
    # Link operations must also work after the booked slot, not require a reschedule.
    assert rooms.link(db, owner.id, row.id, retrieve_only=True)["join_url"].endswith(token)


def test_expired_link_can_be_regenerated_after_the_scheduled_end(room_setup):
    setup, rooms, _, clock, row, token, _ = room_setup
    db, owner, _, _, _, _, _, _ = setup
    clock.value = utc(row.end_utc) + timedelta(days=2)
    row.join_token_expires_at = clock.value - timedelta(seconds=1); db.commit()
    fresh = rooms.link(db, owner.id, row.id)
    assert fresh["join_url"].rsplit("/", 1)[-1] != token
    assert datetime.fromisoformat(fresh["expires_at"]) == clock.value + timedelta(days=rooms.settings.interview_link_max_days)


def test_old_time_restricted_invitation_preview_requires_a_fresh_preview(setup):
    db, owner, _, _, _, _, service, _ = setup
    preview = prepared(setup, count=1)
    batch = db.get(InterviewBatch, preview["id"])
    from app.services.scoring_service import fingerprint
    from copy import deepcopy
    snapshot = deepcopy(batch.snapshot)
    snapshot["recipients"][0]["join_material"].pop("access_policy")
    batch.snapshot = snapshot; batch.confirmation_hash = fingerprint(snapshot); db.commit()
    legacy = service.batch(db, owner.id, batch.id)
    legacy["confirmation_token"] = service.token("invitation", {"batch_id": batch.id, "hash": batch.confirmation_hash}, owner.id)
    with pytest.raises(ValueError, match="older interview-access rules"):
        service.confirm(db, owner.id, batch.id, confirm_data(legacy))


def test_only_assigned_interviewer_can_admit_and_candidate_media_is_gated(room_setup):
    setup, rooms, media, clock, row, token, _ = room_setup
    db, owner, other, _, _, _, _, _ = setup
    session_token, _, _ = rooms.exchange(db, token)
    with pytest.raises(RoomAccessError, match="not available"): rooms.media_access(db, candidate_token=session_token)
    assert not media.created and not media.tokens
    with pytest.raises(RoomConflict): rooms.admit(db, owner.id, row.id)
    # The current schema permits one interviewer account; simulate a different
    # assignment without weakening that existing account constraint.
    row.created_by_user_id = other.id; db.commit()
    with pytest.raises(LookupError): rooms.owned(db, owner.id, row.id)
    row.created_by_user_id = owner.id; db.commit()
    with pytest.raises(PermissionError): rooms.owned(db, other.id, row.id)
    rooms.waiting(db, session_token)
    first = rooms.admit(db, owner.id, row.id)
    clock.value += timedelta(seconds=1)
    second = rooms.admit(db, owner.id, row.id)
    assert first["room_version"] == second["room_version"] and row.candidate_admitted_at is not None
    access = rooms.media_access(db, candidate_token=session_token)
    decoded = jwt.decode(access["participant_token"], rooms.settings.livekit_cloud_api_secret.get_secret_value(), algorithms=["HS256"], issuer=rooms.settings.livekit_cloud_api_key)
    assert decoded["sub"] == row.room_name + "-c" and decoded["video"]["room"] == row.room_name
    assert decoded["video"]["roomJoin"] is True and decoded["video"]["canPublishSources"] == ["camera", "microphone"]
    assert decoded["video"]["canPublishData"] is False and decoded["video"]["roomAdmin"] is False
    assert decoded["video"]["roomCreate"] is False and decoded["video"]["roomRecord"] is False
    assert decoded["video"]["canUpdateOwnMetadata"] is False
    assert decoded["exp"] - decoded["nbf"] <= 120
    assert json.loads(decoded["metadata"]) == {"role": "candidate"}
    assert "@" not in decoded["sub"] and "Candidate" not in row.room_name
    assert rooms.media_access(db, user_id=owner.id, interview_id=row.id)["role"] == "interviewer"


def test_server_verified_join_times_leave_rejoin_and_end_idempotency(room_setup):
    setup, rooms, media, clock, row, token, _ = room_setup
    db, owner, _, _, _, _, _, _ = setup
    session_token, _, _ = rooms.exchange(db, token)
    rooms.waiting(db, session_token); rooms.admit(db, owner.id, row.id)
    with pytest.raises(RoomConflict): rooms.connected(db, candidate_token=session_token)
    media.present = [media.identity(row.room_name, role) for role in ("candidate", "interviewer")]
    rooms.connected(db, candidate_token=session_token)
    assert row.room_status == "active" and row.interview_started_at and row.interviewer_joined_at and row.candidate_joined_at
    rooms.leave(db, candidate_token=session_token)
    assert row.status == "scheduled" and row.room_status == "active"
    assert rooms.media_access(db, candidate_token=session_token)["role"] == "candidate"
    first = rooms.end(db, owner.id, row.id)
    second = rooms.end(db, owner.id, row.id)
    assert first["room_status"] == second["room_status"] == "ended" and len(media.closed) == 1
    assert row.status == "completed" and row.ended_by_user_id == owner.id and row.interview_ended_at
    with pytest.raises(RoomAccessError): rooms.media_access(db, candidate_token=session_token)
    with pytest.raises(RoomAccessError): rooms.media_access(db, user_id=owner.id, interview_id=row.id)
    with pytest.raises(RoomAccessError): rooms.exchange(db, token)


def test_failed_end_blocks_access_until_safe_retry(room_setup):
    setup, rooms, media, _, row, token, _ = room_setup
    db, owner, _, _, _, _, _, _ = setup
    session_token, _, _ = rooms.exchange(db, token)
    media.fail_close = True
    with pytest.raises(MediaUnavailable): rooms.end(db, owner.id, row.id)
    db.refresh(row)
    assert row.room_status == "ending" and row.interview_ended_at is None
    with pytest.raises(RoomAccessError): rooms.media_access(db, candidate_token=session_token)
    media.fail_close = False
    assert rooms.end(db, owner.id, row.id)["room_status"] == "ended"


def test_restart_recovers_only_durably_requested_endings(room_setup):
    from sqlalchemy.orm import sessionmaker
    setup, rooms, media, _, row, token, _ = room_setup
    db, owner, _, _, _, _, _, _ = setup
    media.fail_close = True
    with pytest.raises(MediaUnavailable): rooms.end(db, owner.id, row.id)
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    rooms.recover_ending(factory)
    db.refresh(row)
    assert row.room_status == "ending"
    media.fail_close = False
    rooms.recover_ending(factory)
    db.refresh(row)
    assert row.room_status == "ended" and row.status == "completed"
    rooms.recover_ending(factory)
    assert len(media.closed) == 1


def test_rotation_revokes_old_link_and_session_and_never_sends_email(room_setup):
    setup, rooms, media, _, row, token, _ = room_setup
    db, owner, _, _, _, _, _, sender = setup
    session_token, _, _ = rooms.exchange(db, token)
    old_room, old_generation = row.room_name, row.join_generation
    replacement = rooms.link(db, owner.id, row.id, rotate=True)
    assert replacement["generation"] == old_generation + 1 and row.room_name != old_room
    assert media.closed == [old_room] and not sender.calls
    with pytest.raises(RoomAccessError): rooms.exchange(db, token)
    with pytest.raises(RoomAccessError): rooms.session(db, session_token)
    rooms.revoke(db, owner.id, row.id)
    with pytest.raises(RoomAccessError) as error: rooms.exchange(db, replacement["join_url"].rsplit("/", 1)[-1])
    assert error.value.code == "revoked_link"


def test_rescheduling_preserves_valid_link_but_retires_old_media_and_cookie(room_setup):
    setup, rooms, media, clock, row, token, preview = room_setup
    db, owner, _, _, _, _, service, sender = setup
    cookie, _, _ = rooms.exchange(db, token)
    old_room = row.room_name
    data = RescheduleRequest.model_validate({**schedule_data("placeholder-token").model_dump(exclude={"selection_token"}),
        "date": date.today() + timedelta(days=21), "schedule_ids": [row.id]})
    moved = service.preview_reschedule(db, owner.id, data)
    assert moved["recipients"][0]["join_url"] == preview["recipients"][0]["join_url"]
    service.confirm_reschedule(db, owner.id, confirm_data(moved, "room-reschedule"))
    db.refresh(row)
    assert row.room_name != old_room and old_room in row.media_cleanup_rooms
    assert row.join_token_hash == secret_hash(token)
    clock.value = row.start_utc.replace(tzinfo=UTC) - timedelta(minutes=10)
    with pytest.raises(RoomAccessError): rooms.session(db, cookie)
    new_cookie, _, _ = rooms.exchange(db, token)
    rooms.waiting(db, new_cookie); rooms.admit(db, owner.id, row.id)
    rooms.media_access(db, candidate_token=new_cookie)
    assert old_room in media.closed and not row.media_cleanup_rooms
    assert not sender.calls


def test_rescheduling_rotates_revoked_link_and_transports_approved_url_without_storage(room_setup):
    setup, rooms, _, _, row, token, _ = room_setup
    db, owner, _, _, _, _, service, sender = setup
    rooms.revoke(db, owner.id, row.id)
    data = RescheduleRequest.model_validate({**schedule_data("placeholder-token").model_dump(exclude={"selection_token"}),
        "date": date.today() + timedelta(days=21), "schedule_ids": [row.id]})
    moved = service.preview_reschedule(db, owner.id, data)
    url = moved["recipients"][0]["join_url"]
    assert url.rsplit("/", 1)[-1] != token
    batch = service.confirm_reschedule(db, owner.id, confirm_data(moved, "room-rotated-reschedule"))
    service.deliver_pending(db, batch["id"])
    assert url in sender.calls[0][2]
    event = Calendar.from_ical(sender.calls[0][3]).walk("VEVENT")[0]
    assert url in str(event["description"])
    delivery = db.scalar(select(InterviewDelivery).where(InterviewDelivery.batch_id == batch["id"]))
    assert url not in delivery.body and JOIN_PLACEHOLDER in delivery.body
    assert url not in delivery.calendar_text and delivery.calendar_checksum


@pytest.mark.parametrize("transition", ["admit", "end"])
def test_reschedule_preview_cannot_reopen_an_admitted_or_ended_interview(room_setup, transition):
    setup, rooms, _, _, row, token, _ = room_setup
    db, owner, _, _, _, _, service, _ = setup
    data = RescheduleRequest.model_validate({**schedule_data("placeholder-token").model_dump(exclude={"selection_token"}),
        "date": date.today() + timedelta(days=21), "schedule_ids": [row.id]})
    preview = service.preview_reschedule(db, owner.id, data)
    if transition == "admit":
        cookie, _, _ = rooms.exchange(db, token)
        rooms.waiting(db, cookie); rooms.admit(db, owner.id, row.id)
    else:
        rooms.end(db, owner.id, row.id)
    with pytest.raises(ValueError):
        service.confirm_reschedule(db, owner.id, confirm_data(preview, "cannot-reopen"))
    db.rollback(); db.refresh(row)
    assert row.room_status == ("ready" if transition == "admit" else "ended")


def test_cookie_api_auth_origin_rate_limits_and_generic_errors(room_setup, monkeypatch):
    setup, rooms, _, _, row, token, _ = room_setup
    db, owner, other, _, _, _, _, _ = setup
    from app import security
    from app.main import safe_candidate_validation
    monkeypatch.setattr(routes, "get_settings", lambda: rooms.settings)
    monkeypatch.setattr(security, "get_settings", lambda: rooms.settings)
    api = FastAPI(); api.include_router(routes.router)
    api.dependency_overrides[get_db] = lambda: db
    api.dependency_overrides[routes.get_rooms] = lambda: rooms
    api.add_exception_handler(RequestValidationError, safe_candidate_validation)
    routes.limiter.buckets.clear()
    with TestClient(api) as client:
        origin = {"Origin": rooms.settings.frontend_url}
        assert client.post("/api/interview-rooms/candidate/exchange", json={"token": token}).status_code == 403
        assert client.get(f"/api/interview-rooms/{row.id}").status_code == 401
        denied = {"Authorization": "Bearer " + create_access_token(other.id)}
        assert client.get(f"/api/interview-rooms/{row.id}", headers=denied).status_code == 403
        malformed = client.post("/api/interview-rooms/candidate/exchange", headers=origin, json={"token": "do-not-echo-this-private-input"})
        assert malformed.status_code == 422 and "private-input" not in malformed.text
        response = client.post("/api/interview-rooms/candidate/exchange", headers=origin, json={"token": token})
        assert response.status_code == 200 and token not in response.text
        assert "HttpOnly" in response.headers["set-cookie"] and "SameSite=strict" in response.headers["set-cookie"]
        assert response.headers["cache-control"] == "no-store"
        public = "/api/interview-rooms/candidate/"
        assert client.post(public + "media-token", headers=origin, json={}).status_code == 403
        assert client.post(public + "waiting", headers=origin, json={}).status_code == 200
        assert client.post(f"/api/interview-rooms/{row.id}/end", json={"confirmed": True}).status_code == 401
        headers = {"Authorization": "Bearer " + create_access_token(owner.id)}
        assert client.post(f"/api/interview-rooms/{row.id}/admit", headers=headers, json={"confirmed": True}).status_code == 200
        assert client.post(public + "media-token", headers=origin, json={}).status_code == 200
        assert client.post(public + "media-token", headers=origin, json={"interview_id": row.id + 1}).status_code == 422
        assert client.post(f"/api/interview-rooms/{row.id}/end", headers=headers, json={"confirmed": False}).status_code == 422
        assert client.post(f"/api/interview-rooms/{row.id}/end", headers=headers, json={"confirmed": True}).status_code == 200
        assert client.get(public + "status").json()["code"] == "ended"
    budget = routes.PublicRateLimiter(clock=lambda: 10)
    assert budget.allow("source", 1) and not budget.allow("source", 1)


def test_waiting_heartbeat_and_manual_leave_do_not_complete_interview(room_setup):
    setup, rooms, _, clock, row, token, _ = room_setup
    db = setup[0]
    session, _, _ = rooms.exchange(db, token)
    assert rooms.waiting(db, session)["waiting"]
    clock.value += timedelta(seconds=46)
    assert not rooms.info(db, row)["waiting"]
    assert rooms.candidate_status(db, session)["waiting"]
    assert not rooms.leave(db, candidate_token=session)["waiting"]
    assert row.status == "scheduled" and row.room_status == "scheduled"


def legacy_database(source, url, revision):
    from sqlalchemy import create_engine, MetaData
    from app.database import Base
    from test_migrations import run_upgrade
    run_upgrade(url, revision)
    engine = create_engine(url)
    legacy = MetaData(); legacy.reflect(bind=engine)
    # Copy synthetic records using only the legacy schema's columns, exactly as
    # an existing installation has them before 0017.
    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if table.name not in legacy.tables: continue
            target = legacy.tables[table.name]
            rows = list(source.execute(select(table)).mappings())
            if rows:
                connection.execute(target.insert(), [{key: row[key] for key in target.c.keys() if key in row} for row in rows])
    return engine


def test_room_migration_preserves_legacy_business_data(room_setup, tmp_path):
    from sqlalchemy import text
    from test_migrations import run_upgrade
    url = f"sqlite:///{tmp_path / 'legacy-interviews.db'}"
    engine = legacy_database(room_setup[0][0], url, "0016_interview_scheduling")
    with engine.connect() as connection:
        before = {name: connection.execute(text(f"SELECT * FROM {name}")).mappings().all()
            for name in ("users", "candidate_applications", "interview_schedules", "interview_deliveries")}
    run_upgrade(url)
    with engine.connect() as connection:
        for name, original in before.items():
            current = connection.execute(text(f"SELECT * FROM {name}")).mappings().all()
            assert len(current) == len(original)
            assert [{key: row[key] for key in original[0]} for row in current] == original
        assert connection.scalar(text("SELECT room_status FROM interview_schedules")) == "scheduled"
        assert connection.scalar(text("SELECT join_token_hash FROM interview_schedules")) is None
        assert connection.scalar(text("SELECT count(*) FROM candidate_interview_sessions")) == 0
    engine.dispose()


@pytest.mark.parametrize("case", ["valid", "expired", "revoked", "ended", "cancelled", "longer_expiry"])
def test_anytime_migration_preserves_links_without_reactivating_denied_access(room_setup, tmp_path, monkeypatch, case):
    from sqlalchemy.orm import Session
    from test_migrations import run_upgrade
    source, _, _, _, _, _, _, _ = room_setup[0]
    row = room_setup[4]
    now = datetime.now(UTC)
    row.join_token_expires_at = now + timedelta(hours=4)
    if case == "expired": row.join_token_expires_at = now - timedelta(hours=1)
    elif case == "revoked": row.join_token_revoked_at = now
    elif case == "ended": row.room_status, row.status = "ended", "completed"
    elif case == "cancelled": row.room_status, row.status = "cancelled", "cancelled"
    elif case == "longer_expiry": row.join_token_expires_at = now + timedelta(days=45)
    source.commit()
    before_expiry, version = utc(row.join_token_expires_at), row.version
    url = f"sqlite:///{tmp_path / 'anytime-upgrade.db'}"
    engine = legacy_database(source, url, "0017_interview_rooms")
    monkeypatch.setenv("INTERVIEW_LINK_MAX_DAYS", "30")
    run_upgrade(url)
    with Session(engine) as db:
        upgraded = db.get(InterviewSchedule, row.id)
        assert upgraded.join_token_hash == row.join_token_hash and upgraded.join_token_nonce == row.join_token_nonce
        assert upgraded.join_token_id == row.join_token_id and upgraded.join_generation == row.join_generation
        assert upgraded.room_status == row.room_status and upgraded.status == row.status
        if case == "valid":
            assert now + timedelta(days=30) <= utc(upgraded.join_token_expires_at) <= datetime.now(UTC) + timedelta(days=30)
            assert upgraded.version == version + 1
        else:
            assert utc(upgraded.join_token_expires_at) == before_expiry and upgraded.version == version
    engine.dispose()
