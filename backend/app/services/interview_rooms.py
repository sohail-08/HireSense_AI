"""Authorized room lifecycle, hashed invitation exchange and candidate sessions."""
import hmac
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from app.config import get_settings
from app.models.interview import InterviewSchedule, CandidateInterviewSession
from app.models.user import User, UserRole
from app.models.candidate import CandidateApplication, Candidate, ApplicationStatus
from app.models.job import JobDescription, JobPosting
from app.integrations.livekit_media import LiveKitMedia, MediaUnavailable
from app.services.interview_links import InterviewLinks, secret_hash
from app.services.interview_content import utc

UTC = timezone.utc
OPEN_SCHEDULES = {"scheduled", "rescheduled"}
logger = logging.getLogger(__name__)


class RoomAccessError(ValueError):
    def __init__(self, code="invalid_link", status=403):
        super().__init__("This interview access is not available.")
        self.code, self.status = code, status


class RoomConflict(ValueError):
    pass


class InterviewRooms:
    def __init__(self, settings=None, media=None, now=None):
        self.settings = settings or get_settings()
        self.now = now or (lambda: datetime.now(UTC))
        self.links = InterviewLinks(self.settings, self.now)
        self.media = media or LiveKitMedia(self.settings)

    @staticmethod
    def commit(db):
        try:
            db.commit()
        except SQLAlchemyError:
            db.rollback()
            raise RoomConflict("Interview state changed. Refresh and try again.") from None

    def owned(self, db, user_id, interview_id, lock=False):
        actor = db.get(User, user_id)
        if not actor or not actor.is_active or actor.role != UserRole.INTERVIEWER:
            raise PermissionError("Interviewer access required")
        query = select(InterviewSchedule).where(InterviewSchedule.id == interview_id,
            InterviewSchedule.created_by_user_id == user_id)
        if lock:
            query = query.with_for_update()
        row = db.scalar(query.execution_options(populate_existing=True))
        if not row:
            raise LookupError("Interview not found")
        return row

    def usable(self, db, row, *, link=True):
        if row.room_status == "ending":
            raise RoomAccessError("ending", 410)
        if row.room_status == "ended" or row.status == "completed":
            raise RoomAccessError("ended", 410)
        if row.status == "cancelled" or row.room_status == "cancelled":
            raise RoomAccessError("cancelled", 410)
        if row.status not in OPEN_SCHEDULES:
            raise RoomAccessError()
        if row.room_status not in {"scheduled", "waiting", "ready", "active"}:
            raise RoomAccessError()
        app = db.get(CandidateApplication, row.application_id)
        if not app or not app.candidate_id or app.status in {ApplicationStatus.WITHDRAWN, ApplicationStatus.REJECTED}:
            raise RoomAccessError()
        if not db.get(Candidate, app.candidate_id):
            raise RoomAccessError()
        if link:
            if row.join_token_revoked_at:
                raise RoomAccessError("revoked_link", 410)
            if not row.join_token_hash or not row.join_token_expires_at:
                raise RoomAccessError()
            if utc(row.join_token_expires_at) <= self.now():
                raise RoomAccessError("expired_link", 410)

    def revoke_sessions(self, db, row):
        db.execute(update(CandidateInterviewSession).where(CandidateInterviewSession.interview_id == row.id,
            CandidateInterviewSession.revoked_at.is_(None)).values(revoked_at=self.now()))

    def retire_media(self, row, include_current=False):
        names = list(row.media_cleanup_rooms or [])
        if include_current and row.room_name:
            names.append(row.room_name)
        for name in dict.fromkeys(names):
            self.media.close_room(name)
        row.media_cleanup_rooms = []

    def link(self, db, user_id, interview_id, *, rotate=False, retrieve_only=False):
        row = self.owned(db, user_id, interview_id, lock=True)
        self.usable(db, row, link=False)
        current = self.links.current(row)
        valid = bool(current and not row.join_token_revoked_at and utc(row.join_token_expires_at) > self.now())
        if retrieve_only and not valid:
            raise RoomConflict("Generate a current candidate link first")
        if rotate or not valid:
            if row.room_status in {"ready", "active"}:
                raise RoomConflict("End the active interview before rotating its candidate link")
            # Retire old media credentials by revoking both Cloud identities
            # before deleting the previous room.
            self.retire_media(row, include_current=True)
            material = self.links.material(row.application_id, row.start_utc, row.end_utc, row.join_generation + 1)
            self.links.install(row, material)
            self.revoke_sessions(db, row)
            row.room_status, row.candidate_waiting_at, row.candidate_last_seen_at = "scheduled", None, None
            row.candidate_admitted_at = None
            row.room_version += 1
            row.version += 1
            self.commit(db)
            current = material
        return {"join_url": self.links.url(current), "expires_at": current["expires_at"], "generation": current["generation"]}

    def revoke(self, db, user_id, interview_id):
        row = self.owned(db, user_id, interview_id, lock=True)
        if not row.join_token_revoked_at:
            row.join_token_revoked_at = self.now()
            row.room_version += 1
            row.version += 1
            self.revoke_sessions(db, row)
            self.commit(db)  # Deny new tokens even if closing the media server fails.
        self.retire_media(row, include_current=True)
        self.commit(db)
        return self.info(db, row, interviewer=True)

    def exchange(self, db, token):
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise RoomAccessError()
        digest = secret_hash(token)
        row = db.scalar(select(InterviewSchedule).where(InterviewSchedule.join_token_hash == digest).with_for_update())
        if not row or not hmac.compare_digest(row.join_token_hash, digest):
            raise RoomAccessError()
        self.usable(db, row)
        session_token = secrets.token_urlsafe(32)
        expires = min(self.now() + timedelta(minutes=self.settings.candidate_session_minutes), utc(row.join_token_expires_at))
        db.add(CandidateInterviewSession(interview_id=row.id, application_id=row.application_id,
            session_hash=secret_hash(session_token), join_generation=row.join_generation, expires_at=expires))
        self.commit(db)
        return session_token, expires, self.info(db, row)

    def session(self, db, token, *, lock=False):
        if not token or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise RoomAccessError("invalid_session", 401)
        session = db.scalar(select(CandidateInterviewSession).where(CandidateInterviewSession.session_hash == secret_hash(token)))
        if not session or not hmac.compare_digest(session.session_hash, secret_hash(token)):
            raise RoomAccessError("invalid_session", 401)
        query = select(InterviewSchedule).where(InterviewSchedule.id == session.interview_id)
        if lock:
            query = query.with_for_update()
        row = db.scalar(query.execution_options(populate_existing=True))
        if not row:
            raise RoomAccessError("invalid_session", 401)
        self.usable(db, row)
        if session.revoked_at or utc(session.expires_at) <= self.now() or session.join_generation != row.join_generation or session.application_id != row.application_id:
            raise RoomAccessError("invalid_session", 401)
        return row

    def info(self, db, row, interviewer=False):
        posting = db.get(JobPosting, row.job_posting_id)
        job = db.get(JobDescription, posting.job_description_id)
        waiting = bool(row.candidate_waiting_at and not row.candidate_admitted_at and row.candidate_last_seen_at
            and utc(row.candidate_last_seen_at) > self.now() - timedelta(seconds=self.settings.candidate_waiting_heartbeat_seconds))
        result = {"job_title": job.title, "scheduled_start": utc(row.start_utc), "scheduled_end": utc(row.end_utc),
            "timezone": row.timezone, "room_status": row.room_status, "waiting": waiting,
            "admitted": bool(row.candidate_admitted_at), "link_expires_at": utc(row.join_token_expires_at) if row.join_token_expires_at else None,
            "media_notice": self.media_notice()}
        if interviewer:
            app = db.get(CandidateApplication, row.application_id)
            candidate = db.get(Candidate, app.candidate_id) if app and app.candidate_id else None
            result.update(interview_id=row.id, candidate_name=candidate.name if candidate else "Candidate",
                room_version=row.room_version, has_join_link=bool(row.join_token_hash),
                link_origin_outdated=bool(row.join_token_hash and
                    (row.join_base_url or '').rstrip('/') != self.settings.interview_join_base_url.rstrip('/')),
                link_revoked=bool(row.join_token_revoked_at), candidate_joined_at=row.candidate_joined_at,
                interviewer_joined_at=row.interviewer_joined_at, interview_started_at=row.interview_started_at,
                interview_ended_at=row.interview_ended_at)
        return result

    def media_notice(self):
        try:
            LiveKitMedia(self.settings).configured()
        except MediaUnavailable as exc:
            return str(exc)
        return None

    def candidate_status(self, db, token):
        row = self.session(db, token, lock=True)
        row.candidate_last_seen_at = self.now()
        self.commit(db)
        return self.info(db, row)

    def waiting(self, db, token):
        row = self.session(db, token, lock=True)
        if row.room_status not in {"scheduled", "waiting", "ready", "active"}:
            raise RoomConflict("This interview cannot enter the waiting room")
        row.candidate_waiting_at = row.candidate_waiting_at or self.now()
        row.candidate_last_seen_at = self.now()
        if not row.candidate_admitted_at:
            row.room_status = "waiting"
        row.room_version += 1
        self.commit(db)
        return self.info(db, row)

    def admit(self, db, user_id, interview_id):
        row = self.owned(db, user_id, interview_id, lock=True)
        self.usable(db, row)
        if row.candidate_admitted_at:
            return self.info(db, row, interviewer=True)
        if row.room_status != "waiting" or not self.info(db, row)["waiting"]:
            raise RoomConflict("The candidate is not currently waiting")
        row.candidate_admitted_at, row.room_status = self.now(), "ready"
        row.room_version += 1
        self.commit(db)
        return self.info(db, row, interviewer=True)

    def media_access(self, db, *, candidate_token=None, user_id=None, interview_id=None):
        if user_id is None:
            row, role = self.session(db, candidate_token, lock=True), "candidate"
            if interview_id is not None and interview_id != row.id:
                raise RoomAccessError("invalid_session", 401)
            if not row.candidate_admitted_at:
                raise RoomAccessError("not_admitted", 403)
        else:
            row, role = self.owned(db, user_id, interview_id, lock=True), "interviewer"
            self.usable(db, row)
        if notice := self.media_notice():
            raise MediaUnavailable(notice)
        self.retire_media(row)
        self.media.ensure_room(row.room_name)
        result = self.media.token(row.room_name, role, utc(row.join_token_expires_at))
        self.commit(db)  # Release the row lock after token issuance/lifecycle check.
        return result

    def connected(self, db, *, candidate_token=None, user_id=None, interview_id=None):
        row = self.session(db, candidate_token, lock=True) if user_id is None else self.owned(db, user_id, interview_id, lock=True)
        self.usable(db, row)
        role = "candidate" if user_id is None else "interviewer"
        if role == "candidate" and not row.candidate_admitted_at:
            raise RoomAccessError("not_admitted", 403)
        present = self.media.participants(row.room_name)
        if self.media.identity(row.room_name, role) not in present:
            raise RoomConflict("The participant has not connected yet")
        if self.media.identity(row.room_name, "interviewer") in present:
            row.interviewer_joined_at = row.interviewer_joined_at or self.now()
        if row.candidate_admitted_at and self.media.identity(row.room_name, "candidate") in present:
            row.candidate_joined_at = row.candidate_joined_at or self.now()
        expected = {self.media.identity(row.room_name, role) for role in ("interviewer", "candidate")}
        if expected.issubset(set(present)) and row.candidate_admitted_at:
            row.interview_started_at, row.room_status = row.interview_started_at or self.now(), "active"
        self.commit(db)
        return self.info(db, row, interviewer=role == "interviewer")

    def leave(self, db, *, candidate_token=None, user_id=None, interview_id=None):
        row = self.session(db, candidate_token, lock=True) if user_id is None else self.owned(db, user_id, interview_id, lock=True)
        if user_id is None:
            row.candidate_last_seen_at = None
            if not row.candidate_admitted_at:
                row.candidate_waiting_at, row.room_status = None, "scheduled"
        self.commit(db)
        # Never set completed/ended on participant leave; rejoin remains possible.
        return self.info(db, row, interviewer=user_id is not None)

    def end(self, db, user_id, interview_id):
        row = self.owned(db, user_id, interview_id, lock=True)
        if row.room_status == "ended":
            return self.info(db, row, interviewer=True)
        if row.room_status == "cancelled":
            raise RoomConflict("This interview was cancelled")
        if row.room_status not in {"scheduled", "waiting", "ready", "active", "ending"}:
            raise RoomConflict("Invalid interview-room transition")
        if row.room_status != "ending":
            from app.services.transcription_service import TranscriptionService
            TranscriptionService(self.settings).request_stop(db, row)
            row.room_status, row.end_requested_at = "ending", self.now()
            row.ended_by_user_id = user_id
            row.join_token_revoked_at = row.join_token_revoked_at or self.now()
            row.room_version += 1
            row.version += 1
            self.revoke_sessions(db, row)
            self.commit(db)  # A durable barrier: no more credentials can be issued.
        # Give the worker a bounded chance to drain buffered finals before deleting
        # the media room. A failed STT worker must never block ending the interview.
        from app.models.transcription import TranscriptionSession
        import time
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            pending = db.scalar(select(TranscriptionSession).where(TranscriptionSession.interview_id == row.id,
                TranscriptionSession.status.in_(["starting", "active", "stopping"]))
                .execution_options(populate_existing=True))
            db.commit()
            if not pending:
                break
            time.sleep(0.2)
        for unfinished in db.scalars(select(TranscriptionSession).where(TranscriptionSession.interview_id == row.id,
                TranscriptionSession.status.in_(["starting", "active", "stopping"]))):
            unfinished.status, unfinished.connection_status = "failed", "failed"
            unfinished.failure_code, unfinished.ended_at = "shutdown_timeout", self.now()
        db.commit()
        # Serialize external deletion and finalization. A failed close leaves a
        # durable ending state so End can be safely retried, including after restart.
        row = self.owned(db, user_id, interview_id, lock=True)
        if row.room_status == "ended":
            return self.info(db, row, interviewer=True)
        self.retire_media(row, include_current=True)
        row.room_status, row.status = "ended", "completed"
        row.interview_ended_at = self.now()
        row.room_version += 1
        self.commit(db)
        return self.info(db, row, interviewer=True)

    def recover_ending(self, session_factory):
        """Retry only previously authorized endings, never start or admit a room."""
        with session_factory() as db:
            pending = list(db.execute(select(InterviewSchedule.id, InterviewSchedule.created_by_user_id)
                .where(InterviewSchedule.room_status == "ending")))
        for interview_id, owner_id in pending:
            with session_factory() as db:
                try:
                    self.end(db, owner_id, interview_id)
                except (MediaUnavailable, RoomConflict, RoomAccessError, PermissionError, LookupError, SQLAlchemyError):
                    db.rollback()
                    logger.warning("Interview room %s remains ending; retry End in its console", interview_id)
