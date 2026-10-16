"""Official plugin adapter. Timestamp metadata is available in pinned 1.8.8.

No plugin-internal reconnection: the runner owns retries and a fresh timeline anchor
for every new Deepgram connection. No diarization or model/language detection.
"""
from dataclasses import dataclass
from typing import Protocol


@dataclass
class TranscriptEvent:
    text: str
    final: bool
    start_ms: int
    end_ms: int
    request_id: str
    confidence: float | None
    words: list


class TranscriptionProvider(Protocol):
    def open(self, context: dict): ...


def failure_code(error):
    status = getattr(error, "status_code", None)
    if status in {401, 403}:
        return "provider_authentication_failed"
    if status == 429:
        return "provider_rate_limited"
    return "provider_unavailable"


class DeepgramProvider:
    def __init__(self, api_key):
        self.api_key = api_key

    def open(self, context):
        from livekit.agents import APIConnectOptions
        from livekit.plugins import deepgram
        config = context["configuration"]
        provider = deepgram.STT(api_key=self.api_key, model=context["model"], language=context["language"],
            detect_language=False, interim_results=config["interim_results"], punctuate=True,
            smart_format=True, endpointing_ms=config["endpointing_ms"], utterance_end_ms=config["utterance_end_ms"],
            keyterm=context["keyterms"], enable_diarization=False, sample_rate=16000, no_delay=True,
            vad_events=True)
        return PluginConnection(provider, provider.stream(conn_options=APIConnectOptions(max_retry=0, timeout=10)))


class PluginConnection:
    def __init__(self, provider, stream):
        self.provider, self.stream = provider, stream

    def push(self, frame):
        self.stream.push_frame(frame)

    def finish(self):
        self.stream.end_input()

    async def close(self):
        await self.stream.aclose()
        await self.provider.aclose()

    async def events(self):
        from livekit.agents.stt import SpeechEventType
        async for event in self.stream:
            if event.type not in {SpeechEventType.INTERIM_TRANSCRIPT, SpeechEventType.FINAL_TRANSCRIPT} or not event.alternatives:
                continue
            alt = event.alternatives[0]
            words = []
            for word in alt.words or []:
                confidence = getattr(word, "confidence", None)
                words.append({"text": str(word), "start_ms": round(word.start_time * 1000),
                    "end_ms": round(word.end_time * 1000), "confidence": confidence if isinstance(confidence, (float, int)) else None})
            yield TranscriptEvent(alt.text, event.type == SpeechEventType.FINAL_TRANSCRIPT,
                round(alt.start_time * 1000), round(alt.end_time * 1000), event.request_id, alt.confidence, words)
