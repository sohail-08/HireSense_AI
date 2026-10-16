"""Offline Cloud routing, token privacy and strict retirement tests."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from pydantic import SecretStr
from livekit import api

from app.config import Settings
from app.check_livekit import media_status
from app.integrations.livekit_media import LiveKitMedia, MediaUnavailable


def config(**values):
    defaults = dict(_env_file=None, database_url='sqlite://',
        jwt_secret_key='cloud-test-jwt-key-' + 'j' * 32,
        interviewer_email='test@example.com', interviewer_password='TestPassword123!',
        livekit_cloud_url='wss://test-project.livekit.cloud/',
        livekit_cloud_api_key='test-cloud-key', livekit_cloud_api_secret=SecretStr('test-cloud-secret-' + 'c' * 32))
    defaults.update(values)
    return Settings(**defaults)


class FakeAPI:
    def __init__(self, events, *, delete_missing=False, removal_error=None):
        self.events, self.delete_missing, self.removal_error = events, delete_missing, removal_error
        self.room = self
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def list_rooms(self, request):
        self.events.append(('list', request))
        return SimpleNamespace(rooms=[])
    async def create_room(self, request): self.events.append(('create', request))
    async def list_participants(self, request): return SimpleNamespace(participants=[])
    async def remove_participant(self, request):
        self.events.append(('revoke', request))
        if self.removal_error: raise self.removal_error
    async def delete_room(self, request):
        self.events.append(('delete', request))
        if self.delete_missing: raise api.TwirpError('not_found', 'private-provider-body', status=404)


def fake_client(monkeypatch, **options):
    events = []
    def construct(url, key, secret, **kwargs):
        events.append(('client', url, key, secret))
        return FakeAPI(events, **options)
    monkeypatch.setattr(api, 'LiveKitAPI', construct)
    return events


def test_cloud_uses_own_project_for_sdk_and_tokens_not_application_credentials(monkeypatch):
    settings = config()
    media = LiveKitMedia(settings)
    events = fake_client(monkeypatch)
    media.ensure_room('hs-test-cloud-room')
    assert events[0] == ('client', 'https://test-project.livekit.cloud', 'test-cloud-key', settings.livekit_cloud_api_secret.get_secret_value())
    request = events[-1][1]
    assert request.max_participants == 2 and request.empty_timeout == 300
    access = media.token('hs-test-cloud-room', 'candidate', datetime.now(timezone.utc) + timedelta(minutes=2))
    assert access['server_url'] == 'wss://test-project.livekit.cloud'
    claims = jwt.decode(access['participant_token'], settings.livekit_cloud_api_secret.get_secret_value(),
                        algorithms=['HS256'], issuer='test-cloud-key')
    assert claims['sub'] == 'hs-test-cloud-room-c'
    assert claims['exp'] - claims['nbf'] <= 120
    assert claims['video']['roomJoin'] and claims['video']['room'] == 'hs-test-cloud-room'
    assert not claims['video']['roomAdmin'] and not claims['video']['roomCreate']
    assert claims['video']['canPublishSources'] == ['camera', 'microphone']
    assert settings.livekit_cloud_api_secret.get_secret_value() not in str(access)
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(access['participant_token'], settings.jwt_secret_key.get_secret_value(), algorithms=['HS256'])
    with pytest.raises(ValueError): media.token('hs-test-cloud-room', 'admin', datetime.now(timezone.utc) + timedelta(minutes=2))


@pytest.mark.parametrize('url', ['', 'ws://test-project.livekit.cloud', 'wss://localhost:7880',
    'wss://evil.example', 'wss://test-project.livekit.cloud.evil.example',
    'wss://user:private@test-project.livekit.cloud', 'wss://test-project.livekit.cloud/path',
    'wss://test-project.livekit.cloud?token=private', 'wss://test-project.livekit.cloud#private',
    'wss://test-project.livekit.cloud:443', 'wss://test-project.livekit.cloud:bad', 'wss://[invalid'])
def test_invalid_cloud_endpoint_is_rejected_without_network_or_secret_echo(monkeypatch, url):
    events = fake_client(monkeypatch)
    media = LiveKitMedia(config(livekit_cloud_url=url))
    with pytest.raises(MediaUnavailable, match='LIVEKIT_CLOUD_URL') as error: media.check_connection()
    assert 'private' not in str(error.value) and not events


@pytest.mark.parametrize('values', [dict(livekit_cloud_api_key=''), dict(livekit_cloud_api_secret=SecretStr('')),
    dict(livekit_cloud_api_key='your-private-api-key')])
def test_missing_cloud_credentials_fail_closed(values):
    status = media_status(settings=config(**values))
    assert not status['configured'] and 'LIVEKIT_CLOUD_API_KEY' in status['notice']
    assert not status['remote_media_verified']


def test_cloud_retires_both_identities_before_deletion_with_explicit_cutoff(monkeypatch):
    events = fake_client(monkeypatch)
    before = int(datetime.now(timezone.utc).timestamp())
    LiveKitMedia(config()).close_room('hs-test-cloud-room')
    assert [item[0] for item in events] == ['client', 'revoke', 'revoke', 'delete']
    requests = [item[1] for item in events if item[0] == 'revoke']
    assert {request.identity for request in requests} == {'hs-test-cloud-room-c', 'hs-test-cloud-room-i'}
    assert all(request.room == 'hs-test-cloud-room' and before < request.revoke_token_ts <= before + 60 for request in requests)


@pytest.mark.parametrize('code', ['not_found', 'permission_denied', 'unavailable'])
def test_cloud_revocation_failure_is_not_misclassified_as_deleted_room(monkeypatch, code, caplog):
    events = fake_client(monkeypatch, removal_error=api.TwirpError(code, 'private-provider-body', status=500))
    with pytest.raises(MediaUnavailable) as error: LiveKitMedia(config()).close_room('hs-test-cloud-room')
    assert not any(item[0] == 'delete' for item in events)
    assert 'private-provider-body' not in str(error.value) + caplog.text


def test_already_deleted_cloud_room_is_idempotent_after_successful_revocation(monkeypatch):
    events = fake_client(monkeypatch, delete_missing=True)
    media = LiveKitMedia(config())
    media.close_room('hs-test-cloud-room'); media.close_room('hs-test-cloud-room')
    assert len([item for item in events if item[0] == 'revoke']) == 4


def test_cloud_probe_is_read_only_and_does_not_claim_media_connectivity(monkeypatch):
    events = fake_client(monkeypatch)
    status = media_status(check_api=True, settings=config())
    assert status['configured'] and status['api_reachable'] and status['notice'] is None
    assert status['remote_media_verified'] is False
    assert [item[0] for item in events] == ['client', 'list']
    assert list(events[-1][1].names) == ['hs-connectivity-check-no-room-created']
