"""Optional one-to-one reference-photo matching; never a hiring or identity-proof score."""
import asyncio
import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from cryptography.fernet import Fernet
from sqlalchemy import select, delete
from app.config import get_settings
from app.database import SessionLocal
from app.identity.face import FaceError, get_engine, image_bytes
from app.models.identity import FaceReference, IdentityCheck
from app.models.interview import InterviewSchedule, CandidateInterviewSession
from app.models.candidate import CandidateApplication
from app.services.interview_rooms import InterviewRooms, RoomConflict, RoomAccessError
from app.services.interview_content import utc
from app.services.interview_links import secret_hash

NOTICE = "hiresense-face-v1"
NOTICE_TEXT = "Optional photo-based face verification. With your consent, HireSense converts your encrypted application photo into a face template and compares short camera samples locally, not through Gemini. It does not affect assessment scores or prove legal identity. The photo copy is removed after template extraction; encrypted photos/templates expire after 30 days or 7 days after interview, whichever is sooner. You may decline or withdraw and use manual verification. The original Google Drive upload remains controlled by the application-form owner."
MESSAGES = {
    "matched": "Reference photo matched", "not_checked": "Photo match not checked", "declined": "Face matching declined",
    "pending_consent": "Application photo received · awaiting consent in HireSense",
    "manual": "Manually confirmed by interviewer", "withdrawn": "Face verification consent withdrawn",
    "missing_photo": "No consented application photo available", "queued": "Preparing application photo",
    "processing": "Preparing application photo", "invalid_photo": "Application photo needs attention",
    "model_unavailable": "Face matching is temporarily unavailable", "expired": "Application photo reference expired",
    "no_face": "No clear face found. Face the camera and retry.", "multiple_faces": "More than one face found. Use a photo with only you.",
    "poor_image": "Image unclear. Improve lighting and keep your face visible.", "invalid_image": "Use a clear JPG or PNG image.",
    "low_similarity": "Unable to verify a match. Retry or ask for manual verification.", "unverified": "Unable to verify a photo match",
}


class CandidateIdentityService:
    def __init__(self, settings=None, rooms=None, engine=None, session_factory=None):
        self.settings = settings or get_settings()
        self.rooms = rooms or InterviewRooms(self.settings)
        self.now = self.rooms.now
        self.engine = engine
        self.factory = session_factory or SessionLocal

    def cipher(self):
        configured = self.settings.identity_encryption_key
        if configured and configured.get_secret_value().strip():
            return Fernet(configured.get_secret_value().encode())
        # Independent, persistent runtime key, never a source-controlled secret.
        root = Path(self.settings.storage_root).resolve()
        folder = (root / "identity-secrets").resolve()
        if root not in folder.parents:
            raise FaceError("model_unavailable")
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = folder / "template.key"
        if not path.exists():
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as output:
                    output.write(Fernet.generate_key())
            except FileExistsError:
                pass
        try:
            return Fernet(path.read_bytes())
        except Exception:
            raise FaceError("model_unavailable") from None

    def face_engine(self):
        return self.engine or get_engine(self.settings.identity_models_dir)

    @staticmethod
    def reference(db, application_id):
        return db.scalar(select(FaceReference).where(FaceReference.application_id == application_id)
            .with_for_update().execution_options(populate_existing=True))

    @staticmethod
    def check(db, interview_id):
        return db.scalar(select(IdentityCheck).where(IdentityCheck.interview_id == interview_id)
            .with_for_update().execution_options(populate_existing=True))

    def import_photo(self, db, application, reader, file_ids):
        ref = self.reference(db, application.id)
        if ref and ref.consent == "withdrawn":
            return  # A sheet re-sync cannot undo the candidate's withdrawal.
        fingerprint = hashlib.sha256(json.dumps([file_ids, NOTICE]).encode()).hexdigest()
        if ref and ref.source_hash == fingerprint and ref.status not in {"model_unavailable", "invalid_photo"}:
            return
        if not ref:
            ref = FaceReference(application_id=application.id, status="missing_photo", consent="pending", notice_version=NOTICE,
                source_hash=fingerprint, generation=uuid4().hex, expires_at=self.now() + timedelta(days=self.settings.identity_retention_days))
            db.add(ref)
        ref.source_hash, ref.generation = fingerprint, uuid4().hex
        ref.photo_cipher = ref.embedding_cipher = None
        ref.error = None
        if utc(ref.expires_at) <= self.now():
            ref.status = "expired"
            return
        ref.consent, ref.consented_at, ref.revoked_at = "pending", None, None
        if len(file_ids) != 1:
            ref.status = "missing_photo"
            return
        if not self.settings.identity_enabled:
            ref.status = "model_unavailable"
            return
        try:
            metadata = reader.get_file(file_ids[0])
            if metadata.mime_type not in {"image/jpeg", "image/png"} or (metadata.size is not None and metadata.size > 3 * 1024 * 1024):
                raise FaceError("invalid_image")
            # Drive access is authenticated; never fetch arbitrary user-supplied URLs.
            with tempfile.TemporaryDirectory(prefix="hiresense-photo-") as temporary:
                path = Path(temporary) / "input-image"
                reader.download_file(file_id=file_ids[0], destination=path, max_bytes=3 * 1024 * 1024)
                sanitized = image_bytes(path.read_bytes())
            ref.photo_cipher, ref.status = self.cipher().encrypt(sanitized).decode(), "pending_consent"
        except Exception:
            ref.status, ref.error = "invalid_photo", "invalid_image"

    def process_reference(self, reference_id):
        with self.factory() as db:
            ref = db.scalar(select(FaceReference).where(FaceReference.id == reference_id).with_for_update())
            if not ref or ref.status != "queued" or ref.consent != "given" or utc(ref.expires_at) <= self.now():
                return
            if not self.settings.identity_enabled:
                ref.status, ref.photo_cipher = "model_unavailable", None
                db.commit()
                return
            generation, photo = ref.generation, ref.photo_cipher
            ref.status = "processing"
            db.commit()
        try:
            engine = self.face_engine()
            vector = engine.embedding(self.cipher().decrypt(photo.encode()))
            encrypted = self.cipher().encrypt(json.dumps(vector).encode()).decode()
            status, error, version = "ready", None, engine.version
        except FaceError as exc:
            encrypted, status, error, version = None, "model_unavailable" if str(exc) == "model_unavailable" else "invalid_photo", str(exc), None
        except Exception:
            encrypted, status, error, version = None, "model_unavailable", "model_unavailable", None
        with self.factory() as db:
            ref = db.scalar(select(FaceReference).where(FaceReference.id == reference_id).with_for_update())
            if not ref or ref.generation != generation or ref.status != "processing" or ref.consent != "given":
                return
            ref.photo_cipher = None  # Always discard the encrypted processing copy.
            ref.embedding_cipher, ref.status, ref.error, ref.model_version = encrypted, status, error, version
            if utc(ref.expires_at) <= self.now():
                ref.embedding_cipher, ref.status = None, "expired"
            db.commit()

    def context(self, db, token, *, admitted=False):
        row = self.rooms.session(db, token, lock=True)
        if admitted and not row.candidate_admitted_at:
            raise RoomAccessError("not_admitted", 403)
        session = db.scalar(select(CandidateInterviewSession).where(CandidateInterviewSession.session_hash == secret_hash(token)))
        if session is None:
            raise RoomAccessError("invalid_session", 401)
        return row, session

    def state(self, db, row, session=None):
        ref, check = self.reference(db, row.application_id), self.check(db, row.id)
        active = bool(self.settings.identity_enabled and ref and ref.consent == "given" and ref.status == "ready" and utc(ref.expires_at) > self.now())
        reason = "not_checked" if active else "missing_photo" if not ref else "withdrawn" if ref.consent == "withdrawn" else "expired" if utc(ref.expires_at) <= self.now() else ref.status
        if not self.settings.identity_enabled:
            reason = "model_unavailable"
        valid = bool(check and check.join_generation == row.join_generation and (session is None or check.session_id == session.id))
        if valid and check.status == "manual":
            reason = "manual"
        elif valid and (not active or check.reference_generation == ref.generation):
            if check.status == "declined":
                reason = "declined"
            elif active and check.status in {"matched", "unverified"}:
                reason = "matched" if check.status == "matched" else check.reason
        result = {"enabled": self.settings.identity_enabled, "reference_ready": active,
            "reference_available": bool(self.settings.identity_enabled and ref and ref.consent != "withdrawn" and utc(ref.expires_at) > self.now() and (ref.photo_cipher or active)),
            "status": "matched" if reason == "matched" else "manual" if reason == "manual" else reason,
            "message": MESSAGES.get(reason, MESSAGES["unverified"]), "version": check.version if valid else 0,
            "consented": bool(valid and check.live_consent_at and ref and ref.consent == "given" and utc(ref.expires_at) > self.now() and check.reference_generation == ref.generation), "checked_at": check.checked_at if valid else None,
            "notice_version": NOTICE, "notice": NOTICE_TEXT.replace("30 days", f"{self.settings.identity_retention_days} days").replace("7 days", f"{self.settings.identity_post_interview_days} days"), "reference_expires_at": ref.expires_at if ref else None}
        if session is None:
            result.update(similarity=check.similarity if valid else None, threshold=check.threshold if valid else None,
                manual_note=check.manual_note if valid and check.status == "manual" else None)
        else:
            # Candidate endpoints expose only consent/capture workflow state.
            # A successful match, mismatch and manual decision have the same
            # public completion state; comparison details stay interviewer-only.
            completed = bool(valid and check.checked_at and (check.status == "manual" or
                (active and check.reference_generation == ref.generation and check.status in {"matched", "unverified"})))
            public_status = "submitted" if completed else reason if reason in {"not_checked", "pending_consent", "declined", "withdrawn"} else "preparing" if reason in {"queued", "processing"} else "unavailable"
            messages = {
                "submitted": "Verification submitted. Your interviewer will review it.",
                "not_checked": "Consent saved. Camera samples can be captured after you join.",
                "pending_consent": "Choose whether to allow optional photo verification.",
                "declined": "Photo verification skipped. You can continue with your interview.",
                "withdrawn": "Consent withdrawn. Your HireSense face data has been deleted.",
                "preparing": "Preparing photo verification.",
                "unavailable": "Photo verification is unavailable. You can continue with your interview.",
            }
            result = {key: result[key] for key in ("enabled", "reference_ready", "reference_available", "version",
                "consented", "notice_version", "notice", "reference_expires_at")}
            result.update(status=public_status, message=messages[public_status], capture_available=bool(
                result["consented"] and active and row.candidate_admitted_at and check.status != "manual"))
        return result

    def candidate_state(self, db, token):
        row, session = self.context(db, token)
        result = self.state(db, row, session)
        db.commit()
        return result

    def live_consent(self, db, token, allow):
        row, session = self.context(db, token)
        ref = self.reference(db, row.application_id)
        if allow and (not self.settings.identity_enabled or not ref or ref.consent == "withdrawn" or not (ref.photo_cipher or ref.embedding_cipher) or utc(ref.expires_at) <= self.now()):
            raise RoomConflict("No active application-photo reference is available. Use manual verification.")
        if ref and allow:
            ref.consent, ref.consented_at = "given", self.now()
            if ref.photo_cipher and not ref.embedding_cipher and ref.status != "processing":
                ref.status = "queued"
        elif ref and not allow:
            ref.photo_cipher = ref.embedding_cipher = None
            ref.consent, ref.status, ref.revoked_at, ref.generation = "withdrawn", "withdrawn", self.now(), uuid4().hex
        check = self.check(db, row.id)
        if not check:
            check = IdentityCheck(interview_id=row.id, join_generation=row.join_generation, notice_version=NOTICE, version=0)
            db.add(check)
        check.join_generation, check.session_id = row.join_generation, session.id
        check.reference_generation = ref.generation if ref else None
        check.live_consent_at = self.now() if allow else None
        check.status, check.reason = ("not_checked", "not_checked") if allow else ("declined", "declined")
        check.similarity, check.checked_at, check.manual_note, check.manual_by = None, None, None, None
        check.version += 1
        db.commit()
        return self.state(db, row, session)

    def verify(self, db, token, frames, version):
        if len(frames) != 3:
            raise RoomConflict("Provide three camera samples for this verification.")
        row, session = self.context(db, token, admitted=True)
        ref, check = self.reference(db, row.application_id), self.check(db, row.id)
        if not self.settings.identity_enabled or not ref or ref.status != "ready" or ref.consent != "given" or utc(ref.expires_at) <= self.now():
            raise RoomConflict("No active application-photo reference is available.")
        if not check or not check.live_consent_at or check.reference_generation != ref.generation or check.session_id != session.id or check.join_generation != row.join_generation or check.version != version:
            raise RoomConflict("Confirm consent again before capturing camera samples.")
        generation, encrypted, model_version = ref.generation, ref.embedding_cipher, ref.model_version
        db.rollback()  # Never hold room locks during local model inference.
        similarity, reason = None, "model_unavailable"
        try:
            engine = self.face_engine()
            if engine.version != model_version:
                raise FaceError("model_unavailable")
            reference = json.loads(self.cipher().decrypt(encrypted.encode()))
            vectors = [engine.embedding(frame) for frame in frames]
            similarity = min(cosine(reference, vector) for vector in vectors)
            reason = "matched" if similarity >= self.settings.identity_similarity_threshold else "low_similarity"
        except FaceError as exc:
            reason = str(exc) if str(exc) in MESSAGES else "model_unavailable"
        except Exception:
            reason = "model_unavailable"
        row, session = self.context(db, token, admitted=True)
        ref, check = self.reference(db, row.application_id), self.check(db, row.id)
        if (not ref or ref.generation != generation or ref.consent != "given" or utc(ref.expires_at) <= self.now()
                or not check or check.version != version or not check.live_consent_at or check.session_id != session.id
                or check.reference_generation != generation or check.join_generation != row.join_generation):
            raise RoomConflict("Consent or the reference changed. No result was saved.")
        check.reference_generation = generation
        check.status, check.reason = ("matched" if reason == "matched" else "unverified"), reason
        check.similarity, check.threshold, check.model_version = similarity, self.settings.identity_similarity_threshold, model_version
        check.checked_at, check.version = self.now(), check.version + 1
        db.commit()
        return self.state(db, row, session)

    def withdraw(self, db, token):
        row, session = self.context(db, token)
        ref = self.reference(db, row.application_id)
        if ref:
            ref.photo_cipher = ref.embedding_cipher = None
            ref.consent, ref.status, ref.revoked_at, ref.generation = "withdrawn", "withdrawn", self.now(), uuid4().hex
        self.invalidate(db, row.id)
        db.commit()
        return self.state(db, row, session)

    def interviewer_state(self, db, user_id, interview_id):
        row = self.rooms.owned(db, user_id, interview_id, lock=True)
        result = self.state(db, row)
        db.commit()
        return result

    def manual(self, db, user_id, interview_id, note):
        row = self.rooms.owned(db, user_id, interview_id, lock=True)
        if not row.candidate_joined_at or row.room_status not in {"active", "ready"}:
            raise RoomConflict("Confirm the candidate manually only after they join the interview.")
        session = db.scalar(select(CandidateInterviewSession).where(CandidateInterviewSession.interview_id == row.id,
            CandidateInterviewSession.join_generation == row.join_generation, CandidateInterviewSession.revoked_at.is_(None),
            CandidateInterviewSession.expires_at > self.now()).order_by(CandidateInterviewSession.id.desc()))
        if not session:
            raise RoomConflict("No active candidate session is available.")
        check = self.check(db, row.id)
        if not check:
            check = IdentityCheck(interview_id=row.id, join_generation=row.join_generation, notice_version=NOTICE, version=0)
            db.add(check)
        check.status, check.reason, check.session_id, check.join_generation = "manual", "manual", session.id, row.join_generation
        check.checked_at, check.manual_by, check.manual_note = self.now(), user_id, note
        check.similarity, check.threshold = None, None
        check.version += 1
        db.commit()
        return self.state(db, row)

    @staticmethod
    def invalidate(db, interview_id):
        check = CandidateIdentityService.check(db, interview_id)
        if check:
            check.status, check.reason, check.live_consent_at, check.checked_at = "not_checked", "not_checked", None, None
            check.similarity, check.manual_by, check.manual_note = None, None, None
            check.version += 1

    @staticmethod
    def delete_application(db, application_id, interview_ids):
        db.execute(delete(IdentityCheck).where(IdentityCheck.interview_id.in_(interview_ids)))
        db.execute(delete(FaceReference).where(FaceReference.application_id == application_id))

    def tick(self):
        with self.factory() as db:
            for ref in db.scalars(select(FaceReference).where(FaceReference.consent.in_(["given", "pending"]))):
                ends = list(db.scalars(select(InterviewSchedule.end_utc).where(InterviewSchedule.application_id == ref.application_id,
                    InterviewSchedule.status == "completed")))
                expiry = min([utc(ref.expires_at), *[utc(end) + timedelta(days=self.settings.identity_post_interview_days) for end in ends]])
                ref.expires_at = expiry
                if expiry <= self.now() and ref.status != "expired":
                    ref.photo_cipher = ref.embedding_cipher = None
                    ref.status, ref.generation = "expired", uuid4().hex
            pending = db.scalar(select(FaceReference.id).where(FaceReference.status == "queued").order_by(FaceReference.id))
            db.commit()
        if pending:
            self.process_reference(pending)

    @staticmethod
    def recover(db):
        for ref in db.scalars(select(FaceReference).where(FaceReference.status == "processing")):
            ref.status, ref.generation = "queued", uuid4().hex
        db.commit()


def cosine(left, right):
    if len(left) != 128 or len(right) != 128 or not all(math.isfinite(v) for v in [*left, *right]):
        raise FaceError("model_unavailable")
    denominator = math.sqrt(sum(v*v for v in left) * sum(v*v for v in right))
    if denominator <= 0:
        raise FaceError("model_unavailable")
    return max(-1., min(1., sum(a*b for a,b in zip(left, right)) / denominator))


async def identity_worker(stop):
    import logging
    while not stop.is_set():
        try:
            await asyncio.to_thread(CandidateIdentityService().tick)
        except Exception:
            logging.getLogger(__name__).warning("Identity maintenance will retry; no biometric data is logged")
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
        except TimeoutError:
            pass
