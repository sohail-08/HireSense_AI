"""Opt-in Cloud text transport probe. No microphone, STT, candidate or DB access.

Creates/deletes only a fresh opaque hs-caption-check-* room. Does not touch existing
interview rooms. Run explicitly: python -m transcription_worker.check_caption_transport --run-cloud-probe
"""
import argparse
import asyncio
import json
import logging
import base64
from datetime import timedelta
from uuid import uuid4
from livekit import api, rtc
from .config import WorkerSettings
from caption_protocol import CaptionSigner
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature


async def probe(settings):
    name = "hs-caption-check-" + uuid4().hex
    sender_identity = name + "-agent"
    sender, receiver = rtc.Room(), rtc.Room()
    arrived = asyncio.Event()
    observations = []
    signer = CaptionSigner()
    def decoded(value):
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    jwk = signer.public_key
    public_key = ec.EllipticCurvePublicNumbers(int.from_bytes(decoded(jwk["x"]), "big"),
        int.from_bytes(decoded(jwk["y"]), "big"), ec.SECP256R1()).public_key()
    def incoming(reader, identity):
        async def consume():
            text = await reader.read_all()
            envelope = json.loads(text)
            signature = decoded(envelope["signature"])
            verified = False
            try:
                public_key.verify(encode_dss_signature(int.from_bytes(signature[:32], "big"),
                    int.from_bytes(signature[32:], "big")), decoded(envelope["payload"]), ec.ECDSA(hashes.SHA256()))
                verified = True
            except Exception:
                pass
            observations.append({"sender_matches": identity == sender_identity,
                "sender_missing": not bool(identity), "sender_type": type(identity).__name__,
                "signature_verified": verified,
                "payload_matches": json.loads(decoded(envelope["payload"])) == {"probe": True}})
            arrived.set()
        asyncio.create_task(consume())
    receiver.register_text_stream_handler("hiresense.transcript.v1", incoming)
    def token(identity, hidden):
        return api.AccessToken(settings.livekit_cloud_api_key, settings.livekit_cloud_api_secret.get_secret_value()).with_identity(
            identity).with_ttl(timedelta(minutes=2)).with_grants(api.VideoGrants(room_join=True, room=name,
                can_publish=False, can_subscribe=True, can_publish_data=hidden, hidden=hidden, agent=hidden)).to_jwt()
    url = settings.livekit_cloud_url
    results = []
    async with api.LiveKitAPI("https://" + url.removeprefix("wss://"), settings.livekit_cloud_api_key,
            settings.livekit_cloud_api_secret.get_secret_value()) as client:
        try:
            await client.room.create_room(api.CreateRoomRequest(name=name, max_participants=2, empty_timeout=30))
            await receiver.connect(url, token(name + "-receiver", False))
            await sender.connect(url, token(sender_identity, True))
            for compress in (True, False):
                arrived.clear()
                observations.clear()
                try:
                    await asyncio.wait_for(sender.local_participant.send_text(json.dumps(signer.envelope({"probe": True})),
                        topic="hiresense.transcript.v1", compress=compress), 8)
                    await asyncio.wait_for(arrived.wait(), 5)
                    results.append({"compress": compress, "delivered": True, **observations[-1]})
                except Exception as error:
                    results.append({"compress": compress, "delivered": False, "error_type": type(error).__name__})
        finally:
            await sender.disconnect()
            await receiver.disconnect()
            await client.room.delete_room(api.DeleteRoomRequest(room=name))
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-cloud-probe", action="store_true", required=True)
    parser.parse_args()
    logging.disable(logging.CRITICAL)
    try:
        print(json.dumps(asyncio.run(probe(WorkerSettings()))))
    except Exception as error:
        print(json.dumps({"probe_failed": True, "error_type": type(error).__name__}))
        raise SystemExit(1) from None
