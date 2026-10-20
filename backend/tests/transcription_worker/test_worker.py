import asyncio
import logging
from types import SimpleNamespace
import pytest
from transcription_worker.runner import trusted_microphone, Publisher
from transcription_worker.transport import Backend, BackendUnavailable, PersistenceQueue
from transcription_worker.provider import TranscriptEvent, failure_code


def test_only_trusted_microphones_are_subscribed():
    mapping = {"opaque-i": "INTERVIEWER", "opaque-c": "CANDIDATE"}
    assert trusted_microphone("opaque-i", 2, mapping)
    assert trusted_microphone("opaque-c", 2, mapping)
    assert not trusted_microphone("opaque-i", 1, mapping)
    assert not trusted_microphone("opaque-i", 4, mapping)
    assert not trusted_microphone("Interviewer", 2, mapping)


def test_interim_revisions_are_coalesced_per_speaker():
    publisher = Publisher(None, "session")
    publisher.put({"kind": "interim", "speaker": "INTERVIEWER", "text": "First"})
    publisher.put({"kind": "interim", "speaker": "INTERVIEWER", "text": "Revised"})
    publisher.put({"kind": "interim", "speaker": "CANDIDATE", "text": "Overlap"})
    assert len(publisher.interim) == 2
    assert publisher.interim["INTERVIEWER"]["text"] == "Revised"
    assert publisher.finals.empty()


def test_persistence_is_bounded_and_only_publishes_after_commit():
    async def scenario():
        events = []
        class Fake:
            async def post(self, operation, data):
                assert operation == "segments"
                return {"id": "saved-id", "text": data["text"], "speaker": "CANDIDATE"}
        metrics = {}
        queue = PersistenceQueue(Fake(), events.append, 2, metrics)
        queue.submit({"stream_id": "one", "text": "Final"})
        assert events == []
        task = asyncio.create_task(queue.run())
        await queue.drain(1)
        assert events[0]["saved"] is True and metrics["final_segments"] == 1
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for _ in range(2): queue.submit({"text": "bounded"})
        with pytest.raises(BackendUnavailable): queue.submit({"text": "overflow"})
        assert queue.failed.is_set()
    asyncio.run(scenario())


def test_persistence_failure_isolated_and_never_reports_saved():
    async def scenario():
        class Fake:
            async def post(self, *args): raise RuntimeError("private provider response")
        events = []
        queue = PersistenceQueue(Fake(), events.append, 2, {})
        queue.submit({"text": "Never log this"})
        await queue.run()
        assert queue.failed.is_set() and events == []
    asyncio.run(scenario())


def test_safe_error_categories():
    assert failure_code(SimpleNamespace(status_code=401)) == "provider_authentication_failed"
    assert failure_code(SimpleNamespace(status_code=429)) == "provider_rate_limited"
    assert failure_code(RuntimeError("private")) == "provider_unavailable"


def test_retry_budget_is_bounded(monkeypatch):
    from pydantic import SecretStr
    async def scenario():
        settings = SimpleNamespace(transcription_max_retries=2, transcription_backend_url="http://backend:8000",
            transcription_worker_secret=SecretStr("test-only"))
        backend = Backend(settings, "session", "claim")
        calls = []
        async def fail(*args, **kwargs):
            import httpx
            calls.append(1)
            return httpx.Response(503)
        async def no_delay(*args): pass
        monkeypatch.setattr(backend.client, "post", fail)
        monkeypatch.setattr(asyncio, "sleep", no_delay)
        with pytest.raises(BackendUnavailable): await backend.post("segments")
        assert len(calls) == 3
        await backend.close()
    asyncio.run(scenario())


def test_pinned_sdk_contracts_and_word_metadata():
    pytest.importorskip("livekit.agents")
    import inspect
    from livekit import agents, rtc, api
    from livekit.plugins.deepgram import STT
    from livekit.agents.stt import SpeechData
    assert rtc.TrackSource.SOURCE_MICROPHONE == 2
    for name in ("utterance_end_ms", "keyterm", "endpointing_ms", "enable_diarization", "detect_language"):
        assert name in inspect.signature(STT).parameters
    assert "words" in SpeechData.__dataclass_fields__
    assert "start_time" in SpeechData.__dataclass_fields__
    assert "auto_subscribe" in inspect.signature(agents.JobContext.connect).parameters
    assert hasattr(api, "CreateAgentDispatchRequest")
    permissions = agents.WorkerPermissions(hidden=True, can_publish=False, can_publish_data=True)
    assert permissions.hidden and not permissions.can_publish


@pytest.mark.parametrize("restart_microphone", [False, True])
def test_two_track_streams_overlap_and_flush_finals_on_stop(monkeypatch, restart_microphone):
    pytest.importorskip("livekit.rtc")
    from livekit import rtc
    class FakeAudio:
        def __init__(self, *args, **kwargs): self.first = True
        def __aiter__(self): return self
        async def __anext__(self):
            if self.first:
                self.first = False
                return SimpleNamespace(frame=SimpleNamespace(samples_per_channel=320, sample_rate=16000))
            await asyncio.Future()
        async def aclose(self): pass
    monkeypatch.setattr(rtc, "AudioStream", FakeAudio)
    async def scenario():
        from transcription_worker.runner import Runner
        published, saved, opened, updates = [], [], [], []
        class FakeBackend:
            async def post(self, operation, payload):
                if operation == "streams":
                    opened.append(payload)
                    return {"start_offset_ms": 1000}
                if operation == "update":
                    updates.append(payload)
                    return {"stop": False}
                saved.append(payload)
                return {"id": payload["stream_id"], "speaker": "INTERVIEWER", "text": payload["text"]}
        class Connection:
            def __init__(self): self.frame, self.finished = asyncio.Event(), asyncio.Event()
            def push(self, frame): self.frame.set()
            def finish(self): self.finished.set()
            async def close(self): pass
            async def events(self):
                await self.frame.wait()
                yield TranscriptEvent("Interim", False, 0, 10, "request", .9, [])
                await self.finished.wait()
                yield TranscriptEvent("Final", True, 0, 20, "request", .9, [])
        connections = []
        class Provider:
            def open(self, context):
                connection = Connection()
                connections.append(connection)
                return connection
        async def send_text(value, **kwargs): published.append(value)
        room = SimpleNamespace(local_participant=SimpleNamespace(send_text=send_text))
        context = {"session_id": "session", "participants": {"opaque-i": "INTERVIEWER", "opaque-c": "CANDIDATE"}}
        settings = SimpleNamespace(transcription_queue_size=4, transcription_flush_seconds=1, transcription_max_retries=0)
        runner = Runner(room, FakeBackend(), context, Provider(), settings)
        a, b = SimpleNamespace(sid="TR_i", source=2, track=object(), muted=False), SimpleNamespace(sid="TR_c", source=2, track=object(), muted=False)
        runner.subscribed(object(), a, SimpleNamespace(identity="opaque-i"))
        runner.subscribed(object(), a, SimpleNamespace(identity="opaque-i"))  # duplicate track event
        runner.subscribed(object(), b, SimpleNamespace(identity="opaque-c"))
        runner.subscribed(object(), SimpleNamespace(sid="screen", source=4), SimpleNamespace(identity="opaque-i"))
        task = asyncio.create_task(runner.run())
        for _ in range(100):
            if len(connections) == 2 and all(c.frame.is_set() for c in connections): break
            await asyncio.sleep(.001)
        if restart_microphone:
            a.muted = True
            runner.unpublished(a, SimpleNamespace(identity="opaque-i"))
            a.muted = False
            runner.resume(a, SimpleNamespace(identity="opaque-i"))
            for _ in range(100):
                if len(connections) == 3 and connections[-1].frame.is_set(): break
                await asyncio.sleep(.001)
        runner.stop.set()
        await asyncio.wait_for(task, 3)
        expected = 3 if restart_microphone else 2
        assert len(opened) == len(connections) == expected
        assert all(c.finished.is_set() for c in connections)
        assert len(saved) == expected and all(p["text"] == "Final" for p in saved)
        assert updates[-1]["state"] == "completed"
        assert all("Interim" not in p["text"] for p in saved)
    asyncio.run(scenario())


@pytest.mark.parametrize("muted_role", ["INTERVIEWER", "CANDIDATE"])
@pytest.mark.parametrize("initially_muted", [False, True])
def test_sdk_mute_events_resume_both_speakers_without_stopping_transcription(monkeypatch, muted_role, initially_muted):
    pytest.importorskip("livekit.agents")
    from livekit import rtc
    from transcription_worker.main import register_track_handlers
    from transcription_worker.runner import Runner

    class FakeAudio:
        def __init__(self, track, **kwargs):
            self.track, self.first = track, True

        async def __anext__(self):
            if self.first:
                self.first = False
                return SimpleNamespace(frame=SimpleNamespace(samples_per_channel=320, sample_rate=16000,
                    role=self.track.role))
            await asyncio.Future()

        async def aclose(self):
            pass

    monkeypatch.setattr(rtc, "AudioStream", FakeAudio)

    async def scenario():
        room = rtc.Room()
        sent, saved, streams, connections = [], [], {}, []

        async def send_text(value, **kwargs):
            import json
            sent.append(json.loads(value))

        # Use the SDK's actual event emitter, while isolating network/provider IO.
        room._local_participant = SimpleNamespace(send_text=send_text)

        class FakeBackend:
            async def post(self, operation, payload):
                if operation == "streams":
                    role = participants[payload["participant_identity"]]
                    streams[payload["stream_id"]] = role
                    return {"start_offset_ms": 1000}
                if operation == "update":
                    return {"stop": False}
                role = streams[payload["stream_id"]]
                saved.append(role)
                return {"id": payload["stream_id"], "speaker": role, "text": payload["text"]}

        class Connection:
            def __init__(self):
                self.frame, self.finished = asyncio.Event(), asyncio.Event()
                self.role = None

            def push(self, frame):
                self.role = frame.role
                self.frame.set()

            def finish(self):
                self.finished.set()

            async def close(self):
                pass

            async def events(self):
                await self.frame.wait()
                yield TranscriptEvent(f"{self.role} draft", False, 0, 10, "request", .9, [])
                yield TranscriptEvent(f"{self.role} final", True, 0, 20, "request", .9, [])
                await self.finished.wait()

        class Provider:
            def open(self, context):
                connection = Connection()
                connections.append(connection)
                return connection

        participants = {"opaque-i": "INTERVIEWER", "opaque-c": "CANDIDATE"}
        context = {"session_id": "session", "participants": participants}
        settings = SimpleNamespace(transcription_queue_size=8, transcription_flush_seconds=1, transcription_max_retries=0)
        runner = Runner(room, FakeBackend(), context, Provider(), settings)
        register_track_handlers(room, runner)
        pubs, people = {}, {}
        for identity, role in participants.items():
            people[role] = SimpleNamespace(identity=identity)
            pub = SimpleNamespace(sid=f"TR_{role}", source=2, track=SimpleNamespace(role=role),
                muted=initially_muted and role == muted_role)
            pubs[role] = pub
            room.emit("track_subscribed", pub.track, pub, people[role])
        task = asyncio.create_task(runner.run())

        async def wait_until(predicate):
            async def poll():
                while not predicate():
                    await asyncio.sleep(.001)
            await asyncio.wait_for(poll(), 2)

        try:
            await wait_until(lambda: len(saved) == (1 if initially_muted else 2))
            if not initially_muted:
                pubs[muted_role].muted = True
                room.emit("track_muted", people[muted_role], pubs[muted_role])
                await wait_until(lambda: pubs[muted_role].sid not in runner.tracks)
            pubs[muted_role].muted = False
            room.emit("track_unmuted", people[muted_role], pubs[muted_role])
            await wait_until(lambda: len(saved) == (2 if initially_muted else 3))
            await wait_until(lambda: {event["speaker"] for event in sent if event["kind"] == "final"}
                == {"INTERVIEWER", "CANDIDATE"})
            assert not runner.stop.is_set() and not task.done()
            assert set(saved) == {"INTERVIEWER", "CANDIDATE"}
            assert len(connections) == (2 if initially_muted else 3)
            other_role = "CANDIDATE" if muted_role == "INTERVIEWER" else "INTERVIEWER"
            assert pubs[other_role].sid in runner.tracks
        finally:
            runner.stop.set()
            await asyncio.wait_for(task, 3)
            await room.disconnect()

    asyncio.run(scenario())


def test_sensitive_sdk_logs_are_filtered():
    pytest.importorskip("livekit.agents")
    from transcription_worker.main import SafeLogFilter
    record = logging.LogRecord("livekit.plugins.deepgram", logging.ERROR, "", 0, "private transcript/token", (), None)
    assert not SafeLogFilter().filter(record)
    safe = logging.LogRecord("hiresense.transcription", logging.INFO, "", 0, '{"session_id":"opaque","latency_ms":20}', (), None)
    assert SafeLogFilter().filter(safe)


def test_offline_benchmark_reports_only_measured_observations():
    from transcription_worker.benchmark import report
    result = report({"observations": [{"reference": "React works", "hypothesis": "React works",
        "expected_speaker": "CANDIDATE", "actual_speaker": "CANDIDATE", "reference_start_ms": 100,
        "actual_start_ms": 120, "interim_latency_ms": 30, "finalization_latency_ms": 50}], "technical_terms": ["React"]})
    assert result["word_error_rate"] == 0
    assert result["timestamp_alignment_error_ms"]["median"] == 20
    assert result["interim_latency_ms"]["count"] == 1


def test_caption_signatures_are_session_source_proofs_not_payload_role_claims():
    import base64
    import json
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    from caption_protocol import CaptionSigner, validate_public_key
    signer = CaptionSigner()
    assert validate_public_key(signer.public_key) == signer.public_key
    envelope = signer.envelope({"session_id": "one", "speaker": "CANDIDATE", "text": "Synthetic"})
    def decode(value): return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    key = ec.EllipticCurvePublicNumbers(int.from_bytes(decode(signer.public_key["x"]), "big"),
        int.from_bytes(decode(signer.public_key["y"]), "big"), ec.SECP256R1()).public_key()
    signature = decode(envelope["signature"])
    der = encode_dss_signature(int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big"))
    key.verify(der, decode(envelope["payload"]), ec.ECDSA(hashes.SHA256()))
    with pytest.raises(InvalidSignature):
        key.verify(der, json.dumps({"speaker": "INTERVIEWER"}).encode(), ec.ECDSA(hashes.SHA256()))
    assert "d" not in signer.public_key
    with pytest.raises(ValueError): validate_public_key({**signer.public_key, "x": "invalid"})


def test_publisher_sends_signed_interim_before_stopping_and_counts_failures():
    import json
    import base64
    from caption_protocol import CaptionSigner
    async def scenario():
        sent = []
        async def send_text(text, **options):
            sent.append((json.loads(text), options))
        metrics = {}
        publisher = Publisher(SimpleNamespace(local_participant=SimpleNamespace(send_text=send_text)), "session", CaptionSigner(), metrics)
        task = asyncio.create_task(publisher.run())
        publisher.put({"kind": "interim", "speaker": "CANDIDATE", "text": "During speech", "stream_id": "stream"})
        for _ in range(100):
            if sent: break
            await asyncio.sleep(.001)
        assert len(sent) == 1 and not task.done()
        envelope, options = sent[0]
        payload = json.loads(base64.urlsafe_b64decode(envelope["payload"] + "=" * (-len(envelope["payload"]) % 4)))
        assert payload["kind"] == "interim" and payload["event_index"] == 1
        assert options["compress"] is False
        assert metrics["caption_messages_sent"] == 1
        async def failure(*args, **kwargs): raise RuntimeError("private diagnostics")
        publisher.room.local_participant.send_text = failure
        await publisher.send({"kind": "interim"}, 1)
        assert metrics["caption_publish_failures"] == 1
        assert not publisher.delivery_healthy
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())
