"""Consent/lifecycle and trusted persistence boundary; audio never enters this service."""
import hashlib
import hmac
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import delete, func, select
from app.config import get_settings
from app.integrations.livekit_media import LiveKitMedia, MediaUnavailable
from app.models.interview import InterviewSchedule
from app.models.job import JobDescription, JobPosting, RequirementProfile
from app.models.transcription import TranscriptionConsent, TranscriptionSession, TranscriptionStream, TranscriptSegment
from app.services.interview_content import utc
from caption_protocol import validate_public_key

NOTICE_VERSION = "transcription-v1"
NOTICE = ("With your consent, microphone audio is sent to Deepgram for live English transcription. "
          "HireSense stores final text, speaker labels and timestamps, not audio or video. "
          "Both participants see live captions; only the assigned interviewer can retrieve saved history.")
OPEN = {"starting", "active", "stopping"}


class TranscriptionConflict(ValueError):
    pass


def keyterms(values):
    """Conservative <=200 ASCII characters bounds well below Deepgram's 500-token limit.

    Only short structured job title/skill names; no CV text, candidate names or prose.
    These values are lexical hints, never instructions to an LLM or worker.
    """
    result, seen, budget = [], set(), 200
    for value in values:
        if not isinstance(value, str):
            continue
        value = re.sub(r"[\x00-\x1f\x7f]", " ", value)
        value = " ".join(value.split())
        if not value or len(value) > 50 or not re.fullmatch(r"[A-Za-z0-9 .+#/_()-]+", value):
            continue
        if value.casefold() in seen or len(value) + 1 > budget:
            continue
        seen.add(value.casefold())
        result.append(value)
        budget -= len(value) + 1
    return result


def segment_payload(segment):
    return {key: getattr(segment, key) for key in (
        "id", "session_id", "speaker", "sequence", "text", "start_offset_ms", "end_offset_ms",
        "start_at", "end_at", "confidence", "language", "words")}


class TranscriptionService:
    def __init__(self, settings=None, media=None, now=None):
        self.settings = settings or get_settings()
        self.media = media or LiveKitMedia(self.settings)
        self.now = now or (lambda: datetime.now(timezone.utc))

    def latest(self, db, interview_id, lock=False):
        query = select(TranscriptionSession).where(TranscriptionSession.interview_id == interview_id).order_by(
            TranscriptionSession.created_at.desc(), TranscriptionSession.id.desc()).limit(1)
        return db.scalar(query.with_for_update() if lock else query)

    def expire_stale(self, session):
        if session and session.status in OPEN:
            limit = self.settings.transcription_lease_seconds if session.claim_hash else self.settings.transcription_start_timeout_seconds
            anchor = session.heartbeat_at or session.started_at
            if (self.now() - utc(anchor)).total_seconds() > limit:
                session.status, session.connection_status = "failed", "failed"
                session.failure_code, session.ended_at = "worker_timeout", self.now()

    def consents(self, db, row):
        references = {"INTERVIEWER": row.created_by_user_id, "CANDIDATE": row.application_id}
        return {consent.role: consent for consent in db.scalars(select(TranscriptionConsent).where(
            TranscriptionConsent.interview_id == row.id)) if consent.revoked_at is None
            and consent.notice_version == NOTICE_VERSION and consent.participant_reference == references.get(consent.role)}

    def status(self, db, row, role):
        session = self.latest(db, row.id, lock=True)
        self.expire_stale(session)
        consents = self.consents(db, row)
        result = {"enabled": self.settings.transcription_enabled, "notice": NOTICE, "notice_version": NOTICE_VERSION,
            "retention_days": self.settings.transcription_retention_days,
            "consented": role in consents, "both_consented": len(consents) == 2,
            "status": session.status if session else "not_started", "session_id": session.id if session else None,
            "worker_identity": session.worker_identity if session else None,
            "caption_public_key": (session.configuration or {}).get("caption_public_key") if session else None,
            "connection_status": session.connection_status if session else "stopped",
            "failure_code": session.failure_code if session else None,
            "started_at": session.started_at if session else None,
            "can_start": role == "INTERVIEWER" and row.room_status == "active" and len(consents) == 2
                and self.settings.transcription_enabled and (not session or session.status not in OPEN)}
        if role == "INTERVIEWER":
            result["metrics"] = session.metrics if session else {}
        db.commit()
        return result

    def consent(self, db, row, role, data):
        if row.room_status not in {"scheduled", "waiting", "ready", "active"}:
            raise TranscriptionConflict("This interview is closed")
        consent = db.scalar(select(TranscriptionConsent).where(TranscriptionConsent.interview_id == row.id,
            TranscriptionConsent.role == role).with_for_update())
        if consent is None:
            consent = TranscriptionConsent(interview_id=row.id, role=role,
                participant_reference=row.created_by_user_id if role == "INTERVIEWER" else row.application_id,
                notice_version=NOTICE_VERSION)
            db.add(consent)
        consent.consented_at, consent.notice_version = self.now(), data.notice_version
        consent.revoked_at = None if data.consent else self.now()
        if not data.consent:
            self.request_stop(db, row)
        db.commit()
        return self.status(db, row, role)

    def start(self, db, row):
        if not self.settings.transcription_enabled:
            raise TranscriptionConflict("Transcription is disabled. Configure the worker and enable it first.")
        if len(self.settings.transcription_worker_secret.get_secret_value()) < 32:
            raise TranscriptionConflict("Transcription worker authentication is not configured")
        current = self.latest(db, row.id, lock=True)
        self.expire_stale(current)
        if current and current.status in OPEN:
            return self.status(db, row, "INTERVIEWER")
        if row.room_status != "active":
            raise TranscriptionConflict("Both participants must join the active interview first")
        if len(self.consents(db, row)) != 2:
            raise TranscriptionConflict("Both participants must explicitly consent first")
        job = db.get(JobDescription, db.get(JobPosting, row.job_posting_id).job_description_id)
        profile = db.get(RequirementProfile, job.requirement_profile_id)
        terms = keyterms([job.title, *[item.get("name", "") for item in (profile.required_skills + profile.preferred_skills)]])
        sid = uuid4().hex
        current = TranscriptionSession(id=sid, interview_id=row.id, model=self.settings.deepgram_model,
            language=self.settings.deepgram_language, started_by=row.created_by_user_id, started_at=self.now(),
            expires_at=self.now() + timedelta(days=self.settings.transcription_retention_days), keyterms=terms,
            worker_identity="hs-transcriber-" + sid, configuration={
                "endpointing_ms": self.settings.deepgram_endpointing_ms,
                "utterance_end_ms": self.settings.deepgram_utterance_end_ms,
                "interim_results": self.settings.transcription_interim_results, "keyterms_applied": bool(terms),
                "notice_version": NOTICE_VERSION, "punctuate": True, "smart_format": True, "diarize": False})
        db.add(current)
        db.commit()  # Durable single start under the interview lock before external dispatch.
        try:
            self.media.dispatch_transcriber(row.room_name, sid, self.settings.transcription_agent_name)
        except MediaUnavailable:
            current.status, current.connection_status = "failed", "failed"
            current.failure_code, current.ended_at = "dispatch_failed", self.now()
            db.commit()
        return self.status(db, row, "INTERVIEWER")

    def request_stop(self, db, row):
        session = self.latest(db, row.id, lock=True)
        if session and session.status in {"starting", "active"}:
            session.status, session.stop_requested_at = "stopping", self.now()
        return session

    def stop(self, db, row):
        self.request_stop(db, row)
        db.commit()
        return self.status(db, row, "INTERVIEWER")

    def history(self, db, row, after=None):
        query = select(TranscriptSegment).join(TranscriptionSession).where(
            TranscriptSegment.interview_id == row.id, TranscriptionSession.expires_at > self.now())
        if after:
            query = query.where(TranscriptSegment.created_at >= after)
        # Bounded response; cursor-based pagination uses the last returned ID.
        return list(db.scalars(query.order_by(TranscriptSegment.start_at, TranscriptSegment.sequence).limit(5001)))

    def worker_session(self, db, sid, claim=None):
        session = db.scalar(select(TranscriptionSession).where(TranscriptionSession.id == sid).with_for_update())
        if session is None:
            raise LookupError("Session not found")
        if claim is not None and (not session.claim_hash or not hmac.compare_digest(session.claim_hash,
                hashlib.sha256(claim.encode()).hexdigest())):
            raise PermissionError("Worker lease unavailable")
        self.expire_stale(session)
        if session.status not in OPEN:
            raise TranscriptionConflict("Transcription session is closed")
        return session

    def claim(self, db, sid, claim, caption_public_key=None):
        session = self.worker_session(db, sid)
        digest = hashlib.sha256(claim.encode()).hexdigest()
        if session.claim_hash and not hmac.compare_digest(session.claim_hash, digest):
            raise TranscriptionConflict("Session already claimed")
        if caption_public_key is not None:
            try:
                caption_public_key = validate_public_key(caption_public_key)
            except ValueError:
                raise TranscriptionConflict("Invalid caption verification key") from None
            previous = session.configuration.get("caption_public_key")
            if previous and previous != caption_public_key:
                raise TranscriptionConflict("Caption verification key cannot change during a session")
            session.configuration = {**session.configuration, "caption_public_key": caption_public_key}
        row = db.get(InterviewSchedule, session.interview_id)
        if row.room_status != "active" or len(self.consents(db, row)) != 2 or session.status == "stopping":
            raise TranscriptionConflict("Interview is not available for transcription")
        session.claim_hash, session.heartbeat_at = digest, self.now()
        db.commit()
        return {"session_id": sid, "room_name": row.room_name, "worker_identity": session.worker_identity,
            "started_at": utc(session.started_at), "language": session.language, "model": session.model,
            "keyterms": session.keyterms, "configuration": session.configuration,
            "participants": {LiveKitMedia.identity(row.room_name, "interviewer"): "INTERVIEWER",
                             LiveKitMedia.identity(row.room_name, "candidate"): "CANDIDATE"}}

    def update_worker(self, db, sid, data):
        session = self.worker_session(db, sid, data.claim)
        row = db.get(InterviewSchedule, session.interview_id)
        if row.room_status != "active" or len(self.consents(db, row)) != 2:
            session.status = "stopping"
            session.stop_requested_at = session.stop_requested_at or self.now()
        session.heartbeat_at = self.now()
        session.connection_status = data.connection_status
        if data.keyterms_applied is False:
            session.configuration = {**session.configuration, "keyterms_applied": False,
                                     "keyterm_fallback": "provider_rejected_options"}
        allowed = {"reconnections", "empty_results", "low_confidence", "final_segments", "dropped_audio_frames",
                   "interim_latency_ms", "final_latency_ms", "persistence_latency_ms", "connection_duration_ms",
                   "persistence_failures", "audio_frames", "caption_messages_sent", "caption_publish_failures"}
        session.metrics = {k: v for k, v in data.metrics.items() if k in allowed}
        if data.state == "failed":
            session.status, session.failure_code, session.ended_at = "failed", data.failure_code or "provider_unavailable", self.now()
        elif data.state == "completed":
            session.status, session.connection_status, session.ended_at = "completed", "stopped", self.now()
        elif session.status == "starting":
            session.status = "active"
        db.commit()
        return {"status": session.status, "stop": session.status not in {"starting", "active"}}

    def open_stream(self, db, sid, data):
        session = self.worker_session(db, sid, data.claim)
        row = db.get(InterviewSchedule, session.interview_id)
        if session.status == "stopping" or row.room_status != "active" or len(self.consents(db, row)) != 2:
            raise TranscriptionConflict("Transcription is stopping")
        roles = {LiveKitMedia.identity(row.room_name, "interviewer"): "INTERVIEWER",
                 LiveKitMedia.identity(row.room_name, "candidate"): "CANDIDATE"}
        role = roles.get(data.participant_identity)
        if role is None:
            raise PermissionError("Unknown interview participant")
        existing = db.get(TranscriptionStream, data.stream_id)
        if existing:
            if existing.session_id != sid or existing.participant_identity != data.participant_identity or existing.track_sid != data.track_sid:
                raise TranscriptionConflict("Stream identity conflict")
            db.commit()
            return {"stream_id": existing.id, "start_offset_ms": existing.start_offset_ms, "speaker": role}
        if db.scalar(select(func.count()).select_from(TranscriptionStream).where(TranscriptionStream.session_id == sid)) >= 512:
            raise TranscriptionConflict("Stream limit reached")
        last_end = db.scalar(select(func.max(TranscriptSegment.end_offset_ms)).where(
            TranscriptSegment.session_id == sid, TranscriptSegment.speaker == role)) or 0
        offset = max(last_end, int((self.now() - utc(session.started_at)).total_seconds() * 1000), 0)
        db.add(TranscriptionStream(id=data.stream_id, session_id=sid, speaker=role,
            participant_reference=row.created_by_user_id if role == "INTERVIEWER" else row.application_id,
            participant_identity=data.participant_identity, track_sid=data.track_sid, start_offset_ms=offset))
        db.commit()
        return {"stream_id": data.stream_id, "start_offset_ms": offset, "speaker": role}

    def persist(self, db, sid, data):
        session = self.worker_session(db, sid, data.claim)
        stream = db.get(TranscriptionStream, data.stream_id)
        if not stream or stream.session_id != sid:
            raise PermissionError("Unknown track stream")
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", data.text).strip()
        if not text:
            return None
        existing = db.scalar(select(TranscriptSegment).where(TranscriptSegment.stream_id == stream.id,
            TranscriptSegment.provider_segment_id == data.provider_segment_id))
        if existing:
            if existing.text != text or existing.provider_timing != {"start_ms": data.start_ms, "end_ms": data.end_ms}:
                raise TranscriptionConflict("Final segment conflict")
            db.commit()
            return segment_payload(existing)
        previous_end = db.scalar(select(func.max(TranscriptSegment.end_offset_ms)).where(
            TranscriptSegment.session_id == sid, TranscriptSegment.speaker == stream.speaker)) or 0
        start = max(stream.start_offset_ms + data.start_ms, stream.last_end_ms, previous_end)
        end = max(start, stream.start_offset_ms + data.end_ms)
        # Late finalization can finish buffered speech, but cannot invent post-stop audio.
        ceiling = int(((utc(session.stop_requested_at) if session.stop_requested_at else self.now())
                       - utc(session.started_at)).total_seconds() * 1000) + 2000
        if start > ceiling or end > ceiling:
            raise TranscriptionConflict("Segment is outside the transcription timeline")
        segment = TranscriptSegment(id=hashlib.sha256(f"{sid}|{stream.id}|{data.provider_segment_id}".encode()).hexdigest(),
            session_id=sid, interview_id=session.interview_id, stream_id=stream.id, speaker=stream.speaker,
            participant_reference=stream.participant_reference, participant_identity=stream.participant_identity,
            track_sid=stream.track_sid, provider_request_id=data.provider_request_id, provider_segment_id=data.provider_segment_id,
            sequence=session.next_sequence, text=text, start_offset_ms=start, end_offset_ms=end,
            stream_start_offset_ms=stream.start_offset_ms, start_at=utc(session.started_at) + timedelta(milliseconds=start),
            end_at=utc(session.started_at) + timedelta(milliseconds=end), confidence=data.confidence, language=session.language,
            words=[{**word.model_dump(), "start_offset_ms": stream.start_offset_ms + word.start_ms,
                    "end_offset_ms": stream.start_offset_ms + word.end_ms} for word in data.words],
            provider_timing={"start_ms": data.start_ms, "end_ms": data.end_ms})
        session.next_sequence += 1
        stream.last_end_ms = end
        db.add(segment)
        db.commit()
        return segment_payload(segment)

    def delete_history(self, db, row):
        session = self.latest(db, row.id, lock=True)
        if session and session.status in OPEN:
            raise TranscriptionConflict("Stop transcription and wait for it to finish before deleting")
        self.delete_for_interviews(db, [row.id])
        db.commit()

    @staticmethod
    def delete_for_interviews(db, ids):
        from app.services.work_sample import WorkSampleService
        WorkSampleService.delete_discussion_sources(db, ids)
        from app.services.interview_analysis import InterviewAnalysisService
        InterviewAnalysisService.delete_for_interviews(db, ids)
        session_ids = select(TranscriptionSession.id).where(TranscriptionSession.interview_id.in_(ids))
        db.execute(delete(TranscriptSegment).where(TranscriptSegment.interview_id.in_(ids)))
        db.execute(delete(TranscriptionStream).where(TranscriptionStream.session_id.in_(session_ids)))
        db.execute(delete(TranscriptionSession).where(TranscriptionSession.interview_id.in_(ids)))
        db.execute(delete(TranscriptionConsent).where(TranscriptionConsent.interview_id.in_(ids)))
