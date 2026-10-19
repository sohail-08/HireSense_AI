"""Bounded, authenticated text-only persistence; never logs payloads or HTTP exceptions."""
import asyncio
import random
import time
import httpx


class BackendUnavailable(RuntimeError):
    def __init__(self, status=0):
        self.status = status
        super().__init__("transcription_backend_unavailable")


class Backend:
    def __init__(self, settings, session_id, claim):
        self.session_id, self.claim = session_id, claim
        self.retries = settings.transcription_max_retries
        self.client = httpx.AsyncClient(base_url=settings.transcription_backend_url.rstrip("/"), timeout=3,
            headers={"Authorization": "Bearer " + settings.transcription_worker_secret.get_secret_value()})

    async def post(self, operation, data=None):
        for attempt in range(self.retries + 1):
            try:
                response = await self.client.post(f"/api/internal/transcription/{self.session_id}/{operation}",
                    json={"claim": self.claim, **(data or {})})
                if response.status_code < 400:
                    return response.json()
                if response.status_code < 500 and response.status_code != 429:
                    raise BackendUnavailable(response.status_code)
            except (httpx.TimeoutException, httpx.TransportError):
                pass
            if attempt == self.retries:
                raise BackendUnavailable()
            await asyncio.sleep(min(2, 0.2 * 2**attempt) + random.uniform(0, 0.1))

    async def close(self):
        await self.client.aclose()


class PersistenceQueue:
    def __init__(self, backend, publish, capacity, metrics):
        self.backend, self.publish, self.metrics = backend, publish, metrics
        self.queue = asyncio.Queue(maxsize=capacity)
        self.failed = asyncio.Event()
        self.writing_since = None

    def submit(self, payload):
        try:
            self.queue.put_nowait(payload)
        except asyncio.QueueFull:
            self.failed.set()
            raise BackendUnavailable() from None

    async def run(self):
        while True:
            payload = await self.queue.get()
            try:
                started = time.perf_counter()
                self.writing_since = time.monotonic()
                saved = await self.backend.post("segments", payload)
                self.metrics["persistence_latency_ms"] = (time.perf_counter() - started) * 1000
                if saved:
                    self.metrics["final_segments"] = self.metrics.get("final_segments", 0) + 1
                    self.publish({"kind": "final", **saved, "stream_id": payload["stream_id"], "saved": True})
            except Exception:
                self.metrics["persistence_failures"] = self.metrics.get("persistence_failures", 0) + 1
                self.failed.set()
                return
            finally:
                self.writing_since = None
                self.queue.task_done()

    async def drain(self, timeout):
        await asyncio.wait_for(self.queue.join(), timeout)
