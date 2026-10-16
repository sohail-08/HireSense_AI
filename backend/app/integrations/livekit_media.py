"""Official LiveKit server SDK; no media transport or custom signaling in FastAPI."""
import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from aiohttp import ClientTimeout
from livekit import api
from app.config import get_settings

logger = logging.getLogger(__name__)


class MediaUnavailable(RuntimeError):
    pass


class LiveKitMedia:
    def __init__(self, settings=None):
        self.settings = settings or get_settings()

    @property
    def public_url(self):
        return self.settings.livekit_cloud_url.strip().rstrip('/')

    @property
    def api_url(self):
        # Cloud has one endpoint; derive HTTPS from its validated WSS address.
        return 'https://' + self.public_url[6:]

    @property
    def api_key(self):
        return self.settings.livekit_cloud_api_key

    @property
    def api_secret(self):
        return self.settings.livekit_cloud_api_secret.get_secret_value()

    def configured(self):
        try:
            parsed = urlsplit(self.public_url)
            valid = (parsed.scheme == 'wss' and parsed.hostname and
                re.fullmatch(r'[a-z0-9-]+\.livekit\.cloud', parsed.hostname) and
                parsed.port is None and not any((parsed.path, parsed.query, parsed.fragment, parsed.username, parsed.password)))
        except ValueError:
            valid = False
        if not valid:
            raise MediaUnavailable("Configure LIVEKIT_CLOUD_URL with your LiveKit Cloud wss:// Project URL in the root .env")
        if not self.api_key.strip() or not self.api_secret.strip() or any(
            value.lower().startswith(('replace-', 'your-', 'change-me')) for value in (self.api_key, self.api_secret)):
            raise MediaUnavailable("Add LIVEKIT_CLOUD_API_KEY and LIVEKIT_CLOUD_API_SECRET from your Cloud project to the root .env")

    @staticmethod
    def identity(room_name, role):
        return room_name + ("-c" if role == "candidate" else "-i")

    def token(self, room_name, role, expires_at):
        self.configured()
        if role not in {'candidate', 'interviewer'}:
            raise ValueError('Invalid interview participant role')
        ttl = min(self.settings.livekit_token_ttl_seconds,
            int((expires_at - datetime.now(timezone.utc)).total_seconds()))
        if ttl <= 0:
            raise ValueError("The interview access credential has expired")
        token = (api.AccessToken(self.api_key, self.api_secret)
            .with_identity(self.identity(room_name, role)).with_name(role.capitalize())
            .with_metadata(json.dumps({"role": role})).with_ttl(timedelta(seconds=ttl))
            .with_grants(api.VideoGrants(room_join=True, room=room_name,
                room_create=False, room_admin=False, room_list=False, room_record=False,
                can_publish=True, can_subscribe=True, can_publish_data=False,
                can_publish_sources=["camera", "microphone"], can_update_own_metadata=False,
                ingress_admin=False, recorder=False, agent=False)).to_jwt())
        return {"server_url": self.public_url, "participant_token": token,
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=ttl), "role": role}

    def _call(self, operation, room_name):
        self.configured()
        async def invoke():
            async with api.LiveKitAPI(self.api_url, self.api_key, self.api_secret,
                timeout=ClientTimeout(total=self.settings.livekit_api_timeout_seconds)) as client:
                if operation == "probe":
                    # Read-only authenticated check; never create a room or list
                    # real candidate rooms in diagnostics.
                    await client.room.list_rooms(api.ListRoomsRequest(names=[room_name]))
                    return True
                if operation == "ensure":
                    rooms = await client.room.list_rooms(api.ListRoomsRequest(names=[room_name]))
                    if not rooms.rooms:
                        await client.room.create_room(api.CreateRoomRequest(name=room_name,
                            max_participants=2, empty_timeout=300, departure_timeout=120))
                    return None
                if operation == "close":
                    # Revoke even refreshed tokens and absent identities.
                    # A 30s future margin covers issuance within this second
                    # and small clock skew (Cloud permits a 60s window).
                    # This retired room will never receive new app tokens.
                    cutoff = int(datetime.now(timezone.utc).timestamp()) + 30
                    for role in ('candidate', 'interviewer'):
                        await client.room.remove_participant(api.RoomParticipantIdentity(
                            room=room_name, identity=self.identity(room_name, role), revoke_token_ts=cutoff))
                    try:
                        await client.room.delete_room(api.DeleteRoomRequest(room=room_name))
                    except api.TwirpError as exc:
                        if exc.code != 'not_found':
                            raise
                    return None
                participants = await client.room.list_participants(api.ListParticipantsRequest(room=room_name))
                return [item.identity for item in participants.participants]
        try:
            return asyncio.run(invoke())
        except api.TwirpError as exc:
            # A Cloud revocation failure must not be swallowed as an already
            # deleted room; fail closed and let the existing ending state retry.
            if getattr(exc, "code", None) == "not_found" and operation == "participants":
                return []
            logger.warning("LiveKit room operation failed: %s", operation)
            raise MediaUnavailable("Live media server is unavailable; please retry") from None
        except MediaUnavailable:
            raise
        except Exception:
            logger.warning("LiveKit room connection failed: %s", operation)
            raise MediaUnavailable("Live media server is unavailable; please retry") from None

    def ensure_room(self, room_name):
        return self._call("ensure", room_name)

    def close_room(self, room_name):
        return self._call("close", room_name)

    def participants(self, room_name):
        return self._call("participants", room_name)

    def check_connection(self):
        return self._call("probe", "hs-connectivity-check-no-room-created")
