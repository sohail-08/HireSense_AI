"""Opt-in real-server tests; synthetic identities/media, no email or business DB.

Run from backend on the Docker host with LIVEKIT_CLOUD_INTEGRATION=1. The RTC
test requires requirements-room-test.txt. Cloud tests consume media usage.
Normal CI skips both tests. Never print the generated connection credentials.
"""
import asyncio
import gc
import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from app.config import get_settings
from app.integrations.livekit_media import LiveKitMedia

pytestmark = pytest.mark.skipif(os.environ.get("LIVEKIT_CLOUD_INTEGRATION") != "1", reason="Opt-in real Cloud media tests")


def integration_media():
    media = LiveKitMedia(get_settings())
    media.configured()
    return media


def test_real_room_admin_operations_are_idempotent():
    media = integration_media()
    name = "hs-test-" + uuid4().hex
    try:
        media.ensure_room(name)
        media.ensure_room(name)
        assert media.participants(name) == []
        media.close_room(name)
        media.close_room(name)
        assert media.participants(name) == []
    finally:
        media.close_room(name)


def test_two_real_rtc_clients_exchange_synthetic_media_and_room_delete_disconnects():
    rtc = pytest.importorskip("livekit.rtc", reason="Install requirements-room-test.txt")
    # SDK diagnostics are not allowed to echo signaling credentials.
    logging.getLogger("livekit").setLevel(logging.CRITICAL)
    media = integration_media()
    name = "hs-test-" + uuid4().hex
    media.ensure_room(name)
    deadline = datetime.now(timezone.utc) + timedelta(minutes=2)
    credentials = [media.token(name, role, deadline) for role in ("interviewer", "candidate")]

    async def scenario():
        rooms = [rtc.Room(), rtc.Room()]
        subscriptions = asyncio.Queue()
        disconnected = [asyncio.Event(), asyncio.Event()]
        receivers = []
        sources = []
        for index, room in enumerate(rooms):
            room.on("disconnected", lambda _reason, index=index: disconnected[index].set())
        rooms[1].on("track_subscribed", lambda track, _publication, _participant: subscriptions.put_nowait(track))
        try:
            for room, access in zip(rooms, credentials):
                await asyncio.wait_for(room.connect(access["server_url"], access["participant_token"]), 20)
            for _ in range(100):
                if all(len(room.remote_participants) == 1 for room in rooms): break
                await asyncio.sleep(0.05)
            assert len(rooms[0].remote_participants) == len(rooms[1].remote_participants) == 1
            source = rtc.VideoSource(160, 120)
            sources.append(source)
            track = rtc.LocalVideoTrack.create_video_track("synthetic-camera", source)
            options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_CAMERA)
            await rooms[0].local_participant.publish_track(track, options)
            subscribed = await asyncio.wait_for(subscriptions.get(), 15)
            stream = rtc.VideoStream(subscribed)
            receivers.append(stream)
            frame_received = asyncio.create_task(stream.__anext__())
            frame = rtc.VideoFrame(160, 120, rtc.VideoBufferType.RGBA, bytes([40, 80, 160, 255]) * 160 * 120)
            for _ in range(80):
                source.capture_frame(frame)
                await asyncio.sleep(0.05)
                if frame_received.done(): break
            event = await asyncio.wait_for(frame_received, 5)
            assert event.frame.width == 160 and event.frame.height == 120
            audio_source = rtc.AudioSource(48000, 1)
            sources.append(audio_source)
            microphone = rtc.LocalAudioTrack.create_audio_track("synthetic-microphone", audio_source)
            await rooms[0].local_participant.publish_track(microphone,
                rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
            audio_track = await asyncio.wait_for(subscriptions.get(), 15)
            audio_stream = rtc.AudioStream(audio_track)
            receivers.append(audio_stream)
            audio_received = asyncio.create_task(audio_stream.__anext__())
            audio_frame = rtc.AudioFrame(bytes([100, 0, 156, 255]) * 480, 48000, 1, 960)
            for _ in range(80):
                await audio_source.capture_frame(audio_frame)
                await asyncio.sleep(0.02)
                if audio_received.done(): break
            audio_event = await asyncio.wait_for(audio_received, 5)
            assert audio_event.frame.samples_per_channel > 0
            microphone.mute(); track.mute()
            assert microphone.muted and track.muted
            microphone.unmute(); track.unmute()
            assert not microphone.muted and not track.muted
            await asyncio.to_thread(media.close_room, name)
            await asyncio.wait_for(asyncio.gather(*(event.wait() for event in disconnected)), 10)
            # Explicit Cloud identity revocation prevents a cached JWT from
            # recreating the retired room.
            with pytest.raises(Exception):
                await asyncio.wait_for(rooms[1].connect(credentials[1]["server_url"], credentials[1]["participant_token"]), 10)
        finally:
            for stream in receivers: await stream.aclose()
            for room in rooms: await room.disconnect()
            for source in sources: await source.aclose()
    try:
        asyncio.run(scenario())
    finally:
        media.close_room(name)
        gc.collect()
