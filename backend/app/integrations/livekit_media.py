"""Official LiveKit server SDK; no media transport or custom signaling in FastAPI."""
import asyncio
import json
import logging
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

    def configured(self):
        if not self.settings.livekit_api_key or len(self.settings.livekit_api_secret.get_secret_value()) < 32:
            raise MediaUnavailable("Live media server is not configured")
        parsed = urlsplit(self.settings.livekit_public_url)
        if parsed.scheme not in {"ws", "wss"} or not parsed.hostname or parsed.query or parsed.username:
            raise MediaUnavailable("Configure a browser-accessible LiveKit WebSocket URL")
        if parsed.scheme != "wss" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise MediaUnavailable("LiveKit requires secure WebSockets outside localhost")

    @staticmethod
    def identity(room_name, role):
        return room_name + ("-c" if role == "candidate" else "-i")

    def token(self, room_name, role, expires_at):
        self.configured()
        ttl = min(self.settings.livekit_token_ttl_seconds,
            int((expires_at - datetime.now(timezone.utc)).total_seconds()))
        if ttl <= 0:
            raise ValueError("The interview joining window has closed")
        token = (api.AccessToken(self.settings.livekit_api_key, self.settings.livekit_api_secret.get_secret_value())
            .with_identity(self.identity(room_name, role)).with_name(role.capitalize())
            .with_metadata(json.dumps({"role": role})).with_ttl(timedelta(seconds=ttl))
            .with_grants(api.VideoGrants(room_join=True, room=room_name,
                room_create=False, room_admin=False, room_list=False, room_record=False,
                can_publish=True, can_subscribe=True, can_publish_data=False,
                can_publish_sources=["camera", "microphone"], can_update_own_metadata=False,
                ingress_admin=False, recorder=False, agent=False)).to_jwt())
        return {"server_url": self.settings.livekit_public_url, "participant_token": token,
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=ttl), "role": role}

    def _call(self, operation, room_name):
        self.configured()
        async def invoke():
            async with api.LiveKitAPI(self.settings.livekit_api_url, self.settings.livekit_api_key,
                self.settings.livekit_api_secret.get_secret_value(),
                timeout=ClientTimeout(total=self.settings.livekit_api_timeout_seconds)) as client:
                if operation == "ensure":
                    rooms = await client.room.list_rooms(api.ListRoomsRequest(names=[room_name]))
                    if not rooms.rooms:
                        await client.room.create_room(api.CreateRoomRequest(name=room_name,
                            max_participants=2, empty_timeout=300, departure_timeout=120))
                    return None
                if operation == "close":
                    await client.room.delete_room(api.DeleteRoomRequest(room=room_name))
                    return None
                participants = await client.room.list_participants(api.ListParticipantsRequest(room=room_name))
                return [item.identity for item in participants.participants]
        try:
            return asyncio.run(invoke())
        except api.TwirpError as exc:
            if getattr(exc, "code", None) == "not_found" and operation in {"close", "participants"}:
                return [] if operation == "participants" else None
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
