"""Two independent microphone pipelines; failures cannot disconnect human media."""
import asyncio
import hashlib
import json
import random
import time
import logging
from collections import deque
from uuid import uuid4
from .provider import failure_code
from .transport import BackendUnavailable, PersistenceQueue

TOPIC = "hiresense.transcript.v1"


def trusted_microphone(participant_identity, source, participants):
    # Callers pass rtc.TrackSource.SOURCE_MICROPHONE; never use display name/metadata.
    return source == 2 and participant_identity in participants


class Publisher:
    """Coalesce interim revisions, bound final notifications, and never block STT."""
    def __init__(self, room, session_id):
        self.room, self.session_id = room, session_id
        self.interim, self.finals = {}, asyncio.Queue(maxsize=128)
        self.wake = asyncio.Event()

    def put(self, event):
        event = {"session_id": self.session_id, **event}
        if event["kind"] == "interim":
            self.interim[event["speaker"]] = event
        else:
            self.interim.pop(event.get("speaker"), None)
            try:
                self.finals.put_nowait(event)
            except asyncio.QueueFull:
                # Saved finals remain recoverable through the interviewer's API.
                self.finals.get_nowait()
                self.finals.task_done()
                self.finals.put_nowait(event)
        self.wake.set()

    async def run(self):
        while True:
            await self.wake.wait()
            self.wake.clear()
            while not self.finals.empty():
                event = self.finals.get_nowait()
                try:
                    await asyncio.wait_for(self.room.local_participant.send_text(json.dumps(event, default=str), topic=TOPIC), 2)
                except Exception:
                    pass  # Persistence and media are independent of text transport.
                finally:
                    self.finals.task_done()
            events, self.interim = list(self.interim.values()), {}
            for event in events:
                try:
                    await asyncio.wait_for(self.room.local_participant.send_text(json.dumps(event), topic=TOPIC), 1)
                except Exception:
                    pass


class Runner:
    def __init__(self, room, backend, context, provider, settings):
        self.room, self.backend, self.context, self.provider, self.settings = room, backend, context, provider, settings
        self.stop = asyncio.Event()
        self.metrics = {"reconnections": 0, "empty_results": 0, "low_confidence": 0, "audio_frames": 0}
        self.connection_status, self.failure = "connecting", None
        self.publisher = Publisher(room, context["session_id"])
        self.persistence = PersistenceQueue(backend, self.publisher.put, settings.transcription_queue_size, self.metrics)
        self.tracks, self.role_tracks = {}, {}
        self.resumes = {}
        self.started = time.monotonic()

    def published(self, publication, participant):
        if trusted_microphone(participant.identity, publication.source, self.context["participants"]) and not self.stop.is_set():
            publication.set_subscribed(True)

    def subscribed(self, track, publication, participant):
        if not trusted_microphone(participant.identity, publication.source, self.context["participants"]) or self.stop.is_set() or getattr(publication, "muted", False):
            return
        if publication.sid in self.tracks:
            return
        role = self.context["participants"][participant.identity]
        # Replacing a microphone never creates two simultaneous streams for a role.
        previous = self.role_tracks.get(role)
        if previous:
            previous.set()
        ended = asyncio.Event()
        task = asyncio.create_task(self.track(track, publication.sid, participant.identity, role, ended))
        self.tracks[publication.sid] = (task, ended)
        self.role_tracks[role] = ended

    def unpublished(self, publication, participant):
        if publication.sid in self.tracks:
            self.tracks[publication.sid][1].set()

    def resume(self, publication, participant):
        if not trusted_microphone(participant.identity, publication.source, self.context["participants"]) or self.stop.is_set():
            return
        if publication.sid in self.resumes:
            return
        async def restart():
            try:
                previous = self.tracks.get(publication.sid)
                if previous:
                    previous[1].set()
                    await previous[0]
                if publication.track and not getattr(publication, "muted", False) and not self.stop.is_set():
                    self.subscribed(publication.track, publication, participant)
            finally:
                self.resumes.pop(publication.sid, None)
        self.resumes[publication.sid] = asyncio.create_task(restart())

    def pause_tracks(self):
        self.connection_status = "reconnecting"
        for _, ended in self.tracks.values():
            ended.set()

    async def track(self, track, sid, identity, role, ended):
        from livekit import rtc
        audio = None
        attempt = 0
        try:
            while not ended.is_set() and not self.stop.is_set():
                stream_id = uuid4().hex
                anchor = await self.backend.post("streams", {"stream_id": stream_id, "participant_identity": identity, "track_sid": sid})
                audio = rtc.AudioStream(track, sample_rate=16000, num_channels=1, capacity=100, frame_size_ms=20)
                connection = self.provider.open(self.context)
                connection_started = time.monotonic()
                received, audio_cursor = None, 0
                frame_clock = deque(maxlen=2000)  # 40 seconds, no audio retained.
                # A fresh AudioStream after retries discards old buffered frames.
                async def feed():
                    nonlocal received, audio_cursor
                    try:
                        while not self.stop.is_set() and not ended.is_set():
                            frame_task = asyncio.create_task(audio.__anext__())
                            stop_task, end_task = asyncio.create_task(self.stop.wait()), asyncio.create_task(ended.wait())
                            done, pending = await asyncio.wait([frame_task, stop_task, end_task], return_when=asyncio.FIRST_COMPLETED)
                            for task in pending:
                                task.cancel()
                            await asyncio.gather(*pending, return_exceptions=True)
                            if frame_task not in done or self.stop.is_set() or ended.is_set():
                                break
                            try:
                                event = frame_task.result()
                            except StopAsyncIteration:
                                ended.set()
                                break
                            received = time.monotonic()
                            audio_cursor += event.frame.samples_per_channel / event.frame.sample_rate
                            frame_clock.append((round(audio_cursor * 1000), received))
                            self.metrics["audio_frames"] += 1
                            connection.push(event.frame)
                    finally:
                        connection.finish()

                async def receive():
                    async for event in connection.events():
                        if not event.text.strip():
                            self.metrics["empty_results"] += 1
                            continue
                        now = time.monotonic()
                        if received is not None:
                            # Approximate audio delivery -> event lag using the audio sample clock.
                            frame_time = next((at for offset, at in frame_clock if offset >= event.end_ms), None)
                            if frame_time is not None:
                                lag = max(0, (now - frame_time) * 1000)
                                self.metrics["final_latency_ms" if event.final else "interim_latency_ms"] = lag
                        if event.confidence is not None and event.confidence < 0.7:
                            self.metrics["low_confidence"] += 1
                        if event.final:
                            segment_key = hashlib.sha256(f"{event.request_id}|{event.start_ms}|{event.end_ms}".encode()).hexdigest()
                            self.persistence.submit({"stream_id": stream_id, "provider_request_id": event.request_id,
                                "provider_segment_id": segment_key, "text": event.text, "start_ms": event.start_ms,
                                "end_ms": event.end_ms, "confidence": event.confidence, "words": event.words})
                        elif not self.stop.is_set():
                            self.publisher.put({"kind": "interim", "stream_id": stream_id, "speaker": role,
                                "text": event.text, "start_offset_ms": anchor["start_offset_ms"] + event.start_ms,
                                "end_offset_ms": anchor["start_offset_ms"] + event.end_ms})
                        self.connection_status = "transcribing"

                feed_task, receive_task = asyncio.create_task(feed()), asyncio.create_task(receive())
                try:
                    done, _ = await asyncio.wait([feed_task, receive_task], return_when=asyncio.FIRST_COMPLETED)
                    if feed_task in done:
                        feed_task.result()
                        await asyncio.wait_for(receive_task, self.settings.transcription_flush_seconds)
                    else:
                        receive_task.result()
                        if not ended.is_set() and not self.stop.is_set():
                            raise RuntimeError("provider_closed")
                    break
                except Exception as error:
                    if isinstance(error, BackendUnavailable):
                        self.failure = "persistence_unavailable"
                        self.stop.set()
                        break
                    if self.stop.is_set() or ended.is_set():
                        if isinstance(error, asyncio.TimeoutError):
                            self.failure = "shutdown_timeout"
                        break
                    self.connection_status = "reconnecting"
                    if getattr(error, "status_code", None) == 400 and self.context["keyterms"]:
                        self.context["keyterms"] = []
                        await self.backend.post("update", {"connection_status": "reconnecting", "keyterms_applied": False})
                    attempt += 1
                    self.metrics["reconnections"] += 1
                    if attempt > self.settings.transcription_max_retries or failure_code(error) == "provider_authentication_failed":
                        self.failure = failure_code(error)
                        self.stop.set()
                        break
                    await audio.aclose()
                    await asyncio.sleep(min(2, 0.25 * 2**attempt) + random.uniform(0, 0.1))
                finally:
                    for task in (feed_task, receive_task):
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(feed_task, receive_task, return_exceptions=True)
                    await connection.close()
                    self.metrics["connection_duration_ms"] = (time.monotonic() - connection_started) * 1000
        except BackendUnavailable:
            self.failure = "persistence_unavailable"
            self.stop.set()
        except Exception:
            self.failure = "provider_unavailable"
            self.stop.set()
        finally:
            if audio is not None:
                await audio.aclose()
            self.tracks.pop(sid, None)
            if self.role_tracks.get(role) is ended:
                self.role_tracks.pop(role, None)

    async def run(self):
        persistence_task = asyncio.create_task(self.persistence.run())
        publisher_task = asyncio.create_task(self.publisher.run())
        heartbeat_task = None
        async def heartbeat():
            try:
                while not self.stop.is_set():
                    slow_storage = self.persistence.writing_since is not None and time.monotonic() - self.persistence.writing_since > 1
                    state = "degraded" if slow_storage else self.connection_status
                    result = await self.backend.post("update", {"connection_status": state, "metrics": self.metrics})
                    if result["stop"]:
                        self.stop.set()
                        break
                    if self.persistence.failed.is_set():
                        self.failure, self.connection_status = "persistence_unavailable", "degraded"
                        self.stop.set()
                        break
                    logging.getLogger("hiresense.transcription").info(json.dumps({"event": "transcription_metrics",
                        "session_id": self.context["session_id"], "connection_status": self.connection_status, **self.metrics}))
                    await asyncio.sleep(0.75)
            except Exception:
                self.failure = "persistence_unavailable"
                self.stop.set()
        try:
            heartbeat_task = asyncio.create_task(heartbeat())
            await self.stop.wait()
            tasks = [task for task, _ in list(self.tracks.values())]
            if tasks:
                try:
                    await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), self.settings.transcription_flush_seconds + 1)
                except asyncio.TimeoutError:
                    self.failure = "shutdown_timeout"
            try:
                await self.persistence.drain(self.settings.transcription_flush_seconds)
                await asyncio.wait_for(self.publisher.finals.join(), 2)
            except asyncio.TimeoutError:
                self.failure = "persistence_unavailable"
            await self.backend.post("update", {"state": "failed" if self.failure else "completed",
                "connection_status": "failed" if self.failure else "stopped", "failure_code": self.failure, "metrics": self.metrics})
        finally:
            for task in self.resumes.values():
                task.cancel()
            await asyncio.gather(*list(self.resumes.values()), return_exceptions=True)
            for task in (heartbeat_task, persistence_task, publisher_task):
                if task:
                    task.cancel()
            await asyncio.gather(*[t for t in (heartbeat_task, persistence_task, publisher_task) if t], return_exceptions=True)
