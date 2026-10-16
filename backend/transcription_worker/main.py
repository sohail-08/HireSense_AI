"""Run: python -m transcription_worker.main start (explicit named dispatch only)."""
import asyncio
import json
import logging
import secrets
from livekit import agents
from .config import WorkerSettings
from .provider import DeepgramProvider
from .transport import Backend, BackendUnavailable
from .runner import Runner


class SafeLogFilter(logging.Filter):
    """Third-party SDK exceptions may contain provider payloads/URLs; suppress them.

    Application metrics contain only numeric data and opaque IDs. SDK health is
    available from its HTTP endpoint, not verbose logging of room traffic.
    """
    def filter(self, record):
        return record.name == "hiresense.transcription" and not record.exc_info


def configure_safe_logs():
    original_handle = logging.Handler.handle
    if getattr(original_handle, "_hiresense_safe", False):
        return
    def safe_handle(handler, record):
        if SafeLogFilter().filter(record):
            return original_handle(handler, record)
        return False
    safe_handle._hiresense_safe = True
    logging.Handler.handle = safe_handle


async def request(job):
    try:
        metadata = json.loads(job.job.metadata)
        sid = metadata["session_id"]
        if len(sid) != 32 or any(c not in "0123456789abcdef" for c in sid):
            raise ValueError()
        await job.accept(identity="hs-transcriber-" + sid, name="Transcription")
    except (ValueError, KeyError, TypeError):
        await job.reject()


async def entrypoint(ctx):
    configure_safe_logs()  # Applies inside the spawned job process as well.
    settings = WorkerSettings()
    backend = Backend(settings, json.loads(ctx.job.metadata)["session_id"], secrets.token_hex(32))
    runner = None
    finished = asyncio.Event()
    try:
        context = await backend.post("claim")
        if context["room_name"] != ctx.room.name or context["worker_identity"] != "hs-transcriber-" + context["session_id"]:
            return
        if not settings.deepgram_api_key.get_secret_value().strip():
            await backend.post("update", {"state": "failed", "connection_status": "failed", "failure_code": "missing_deepgram_key"})
            return
        runner = Runner(ctx.room, backend, context, DeepgramProvider(settings.deepgram_api_key.get_secret_value()), settings)
        ctx.room.on("track_published", runner.published)
        ctx.room.on("track_subscribed", runner.subscribed)
        ctx.room.on("track_unpublished", runner.unpublished)
        ctx.room.on("track_unsubscribed", lambda track, publication, participant: runner.unpublished(publication, participant))
        # A muted track can stop delivering PCM. Restart its provider clock on
        # unmute rather than compressing a long silent gap out of the timeline.
        ctx.room.on("track_muted", runner.unpublished)
        ctx.room.on("track_unmuted", runner.resume)
        ctx.room.on("reconnecting", runner.pause_tracks)
        def reconnected():
            for participant in ctx.room.remote_participants.values():
                for publication in participant.track_publications.values():
                    runner.resume(publication, participant)
        ctx.room.on("reconnected", reconnected)
        def disconnected(*_):
            if not runner.stop.is_set():
                runner.failure = "worker_disconnected"
            runner.stop.set()
        ctx.room.on("disconnected", disconnected)
        async def shutdown():
            runner.stop.set()
            try:
                await asyncio.wait_for(finished.wait(), settings.transcription_flush_seconds * 2 + 2)
            except asyncio.TimeoutError:
                pass
        ctx.add_shutdown_callback(shutdown)
        await ctx.connect(auto_subscribe=agents.AutoSubscribe.SUBSCRIBE_NONE)
        for participant in ctx.room.remote_participants.values():
            for publication in participant.track_publications.values():
                runner.published(publication, participant)
                if publication.track:
                    runner.subscribed(publication.track, publication, participant)
        await runner.run()
    except BackendUnavailable:
        pass  # Duplicate dispatch, revoked lease or unavailable DB: do not send audio.
    except Exception:
        try:
            await backend.post("update", {"state": "failed", "connection_status": "failed", "failure_code": "worker_disconnected"})
        except Exception:
            pass
    finally:
        if runner:
            runner.stop.set()
        await backend.close()
        finished.set()
        await ctx.room.disconnect()
        ctx.shutdown(reason="transcription_finished")


def main():
    settings = WorkerSettings()
    # CLI configures handlers after startup; install a filter on the handler factory
    # as well as existing handlers so SDK payloads never reach stdout/stderr.
    configure_safe_logs()
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint, request_fnc=request,
        agent_name=settings.transcription_agent_name, ws_url=settings.livekit_cloud_url,
        api_key=settings.livekit_cloud_api_key, api_secret=settings.livekit_cloud_api_secret.get_secret_value(),
        permissions=agents.WorkerPermissions(hidden=True, can_publish=False, can_subscribe=True,
            can_publish_data=True, can_update_metadata=False), num_idle_processes=0,
        port=8081, host="0.0.0.0", drain_timeout=15, shutdown_process_timeout=12, max_retry=3))


if __name__ == "__main__":
    main()
