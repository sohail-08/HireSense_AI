"""Shared deterministic scheduling services. All identity/recipient resolution is server-side."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import jwt
from email_validator import validate_email, EmailNotValidError
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from app.config import get_settings
from app.database import SessionLocal
from app.models.user import User, UserRole
from app.models.job import JobDescription, JobPosting
from app.models.candidate import CandidateApplication, Candidate, CVDocument, CVProcessingStatus, ApplicationStatus
from app.models.scoring import ScoringRun, CandidateScore
from app.models.interview import InterviewBatch, InterviewSchedule, InterviewDelivery
from app.schemas.interview import SelectionRequest, PrepareInvites, RescheduleRequest
from app.services.scoring_service import ScoringService, fingerprint
from app.services.scoring_calculation import display_score
from app.services.interview_content import allocate_slots, render_email, calendar_invitation, SMTPInvitationSender, utc
from app.services.interview_links import InterviewLinks, JOIN_PLACEHOLDER, redact_join_links, ACCESS_POLICY

UTC = timezone.utc
ACTIVE = ("scheduled", "rescheduled")


class InterviewConflict(ValueError):
    pass


def normalized_email(value):
    try:
        return validate_email(value or "", check_deliverability=False, test_environment=True, allow_smtputf8=False).ascii_email
    except EmailNotValidError:
        return None


def masked_email(value):
    email = normalized_email(value)
    if not email:
        return None
    local, domain = email.split("@")
    return local[:1] + "***@" + domain


class InterviewService:
    def __init__(self, settings=None, sender=None, session_factory=None):
        self.settings = settings or get_settings()
        self.sender = sender or SMTPInvitationSender(self.settings)
        self.session_factory = session_factory or SessionLocal
        self.links = InterviewLinks(self.settings)

    def actor(self, db, user_id, *, lock=False):
        user = db.scalar(select(User).where(User.id == user_id).with_for_update()) if lock else db.get(User, user_id)
        if not user or not user.is_active or user.role != UserRole.INTERVIEWER:
            raise PermissionError("Interviewer access required")
        return user

    def job(self, db, user_id, job_id):
        self.actor(db, user_id)
        job = db.scalar(select(JobDescription).join(JobPosting).where(JobPosting.id == job_id, JobDescription.created_by_user_id == user_id))
        if not job:
            raise LookupError("Job posting not found")
        return job

    def token(self, kind, payload, user_id):
        return jwt.encode({"iss": "hiresense-interviews", "aud": kind, "sub": str(user_id),
            "exp": datetime.now(UTC) + timedelta(minutes=20), "data": payload},
            self.settings.jwt_secret_key.get_secret_value(), algorithm="HS256")

    def decode(self, kind, token, user_id, *, allow_expired=False):
        try:
            data = jwt.decode(token, self.settings.jwt_secret_key.get_secret_value(), algorithms=["HS256"],
                issuer="hiresense-interviews", audience=kind, options={"verify_exp": not allow_expired})
            if data["sub"] != str(user_id):
                raise ValueError()
            return data["data"]
        except (jwt.InvalidTokenError, KeyError, ValueError):
            raise InterviewConflict("Preview expired or belongs to another interviewer. Prepare a new preview.") from None

    def eligibility(self, db, application, stage):
        candidate = db.get(Candidate, application.candidate_id) if application.candidate_id else None
        reasons = []
        if not candidate or not normalized_email(candidate.email):
            reasons.append("Missing or invalid candidate email")
        if application.status in {ApplicationStatus.WITHDRAWN, ApplicationStatus.REJECTED}:
            reasons.append("Application is withdrawn or rejected")
        document = db.scalar(select(CVDocument).where(CVDocument.application_id == application.id).order_by(CVDocument.id.desc()))
        if not document or document.status != CVProcessingStatus.PROCESSED or document.extraction_warnings:
            reasons.append("CV processing is incomplete or has unresolved document problems")
        if db.scalar(select(InterviewSchedule.id).where(InterviewSchedule.application_id == application.id,
            InterviewSchedule.stage == stage, InterviewSchedule.status.in_(ACTIVE))):
            reasons.append("An active interview already exists for this stage")
        return candidate, reasons

    def preview_selection(self, db, user_id, data):
        job = self.job(db, user_id, data.job_posting_id)
        query = select(ScoringRun).where(ScoringRun.job_posting_id == data.job_posting_id)
        run = db.scalar(query.where(ScoringRun.id == data.ranking_run_id)) if data.ranking_run_id else db.scalar(query.order_by(ScoringRun.id.desc()))
        if not run or run.status not in {"completed", "completed_with_review"}:
            raise ValueError("A completed persisted ranking is required")
        latest_id = db.scalar(query.order_by(ScoringRun.id.desc()).with_only_columns(ScoringRun.id))
        proposal = ScoringService.proposal(db, user_id=user_id, job_id=data.job_posting_id)
        if run.id != latest_id or run.requirement_version != proposal["requirement_version"]:
            raise InterviewConflict("Ranking changed or is historical. Select the current ranking.")
        if proposal.get("approved_configuration") and run.configuration_id != proposal["approved_configuration"]["id"]:
            raise InterviewConflict("Scoring weights changed. Recalculate the ranking before selection.")
        saved_ids = run.snapshot["application_ids"]
        current_inputs = ScoringService._inputs(db, data.job_posting_id, run.requirement_version, saved_ids)
        if fingerprint(current_inputs) != fingerprint(run.snapshot["applications"]):
            raise InterviewConflict("Candidate evidence changed. Recalculate the ranking before selection.")
        if data.mode == "top_n" and data.top_n is None:
            raise ValueError("Provide the number of candidates")
        if data.mode == "threshold" and data.threshold is None:
            raise ValueError("Provide a score threshold and comparison operator")
        scores = list(db.scalars(select(CandidateScore).where(CandidateScore.scoring_run_id == run.id)
            .order_by(CandidateScore.rank.asc().nulls_last(), CandidateScore.application_id)))
        if data.mode == "manual":
            if not data.application_ids:
                raise ValueError("Select at least one candidate")
            if not set(data.application_ids).issubset({score.application_id for score in scores}):
                raise LookupError("Selected applications must belong to this job and ranking")
        # Top N refers to the original saved ranking positions, not the first N
        # candidates remaining after eligibility filtering. Never backfill an
        # excluded top-ranked candidate with someone outside that boundary.
        pool = scores[:data.top_n] if data.mode == "top_n" else scores
        tie = bool(data.mode == "top_n" and len(scores) > len(pool) and pool
            and pool[-1].rank is not None and pool[-1].rank == scores[len(pool)].rank)
        selected, excluded = [], []
        for score in pool:
            if data.mode == "manual" and score.application_id not in data.application_ids:
                continue
            if data.mode == "threshold" and not (score.final_score > data.threshold if data.operator == "gt" else score.final_score >= data.threshold):
                continue
            application = db.get(CandidateApplication, score.application_id)
            if not application or application.job_posting_id != data.job_posting_id:
                raise InterviewConflict("Application membership changed; create a new ranking")
            candidate, reasons = self.eligibility(db, application, data.stage)
            if score.rank is None or score.review_state != "ranked":
                reasons.append("This historical score was excluded from ranking; recalculate first")
            entry = {"application_id": application.id, "name": candidate.name if candidate else "Unnamed candidate",
                "rank": score.rank, "score": display_score(str(score.final_score)), "masked_email": masked_email(candidate.email) if candidate else None}
            if reasons:
                excluded.append({**entry, "reasons": reasons})
            else:
                selected.append(entry)
        seal = fingerprint({"rule": data.model_dump(mode="json"), "run": run.id, "input_hash": run.input_hash,
            "selected": selected, "emails": [db.get(Candidate, db.get(CandidateApplication, item["application_id"]).candidate_id).email for item in selected]})
        payload = {"rule": data.model_dump(mode="json"), "run_id": run.id, "fingerprint": seal}
        warnings = ["The top-N boundary crosses a tie; stable application order determines selection."] if tie else []
        if data.mode == "top_n" and len(selected) < data.top_n:
            warnings.append(f"Only {len(selected)} of the original top {data.top_n} candidates are eligible. "
                "Excluded candidates are not replaced by lower-ranked candidates.")
        return {"job_posting_id": data.job_posting_id, "job_title": job.title, "ranking_run_id": run.id,
            "selection_type": data.mode, "stage": data.stage, "selected": selected, "excluded": excluded,
            "recipient_count": len(selected), "tie_at_boundary": tie,
            "warnings": warnings,
            "fingerprint": seal, "selection_token": self.token("selection", payload, user_id)}

    def validate_selection(self, db, user_id, token):
        saved = self.decode("selection", token, user_id)
        current = self.preview_selection(db, user_id, SelectionRequest.model_validate(saved["rule"]))
        if current["fingerprint"] != saved["fingerprint"] or current["ranking_run_id"] != saved["run_id"]:
            raise InterviewConflict("Recipients or ranking changed. Create a new selection preview.")
        if not current["selected"]:
            raise ValueError("No eligible candidates are selected")
        current.pop("selection_token")
        return current

    def conflicts(self, db, user_id, slots, ignore_ids=()):
        for slot in slots:
            start, end = datetime.fromisoformat(slot["start_utc"]), datetime.fromisoformat(slot["end_utc"])
            query = select(InterviewSchedule.id).where(InterviewSchedule.created_by_user_id == user_id,
                InterviewSchedule.status.in_(ACTIVE), InterviewSchedule.start_utc < end, InterviewSchedule.end_utc > start)
            if ignore_ids:
                query = query.where(InterviewSchedule.id.not_in(ignore_ids))
            if db.scalar(query):
                raise InterviewConflict("The proposed time conflicts with an existing interview. Choose another time.")

    def prepare(self, db, user_id, data):
        selection = self.validate_selection(db, user_id, data.selection_token)
        slots = allocate_slots(data, len(selection["selected"]))
        self.conflicts(db, user_id, slots)
        previews = []
        for candidate, slot in zip(selection["selected"], slots):
            email = redact_join_links(render_email(self.settings, candidate, selection["job_title"], selection["stage"], slot, data))
            if JOIN_PLACEHOLDER not in email["body"]:
                email["body"] += "\n\nJoin your HireSense interview: " + JOIN_PLACEHOLDER
            material = self.links.material(candidate["application_id"], datetime.fromisoformat(slot["start_utc"]), datetime.fromisoformat(slot["end_utc"]))
            previews.append({**candidate, **slot, "calendar_uid": str(uuid4()) + "@hiresense", "sequence": 0,
                "join_material": material, **email})
        snapshot = {"selection": selection, "selection_token": data.selection_token,
            "schedule": redact_join_links(data.model_dump(mode="json", exclude={"selection_token"})), "recipients": previews,
            "sender": self.mail_identity()}
        batch = InterviewBatch(job_posting_id=selection["job_posting_id"], ranking_run_id=selection["ranking_run_id"],
            snapshot=snapshot, confirmation_hash=fingerprint(snapshot), created_by_user_id=user_id)
        db.add(batch)
        db.commit()
        result = self.batch(db, user_id, batch.id)
        result["confirmation_token"] = self.token("invitation", {"batch_id": batch.id, "hash": batch.confirmation_hash}, user_id)
        return result

    def mail_identity(self):
        for address in (self.settings.smtp_from_email, self.settings.interview_reply_to_email):
            if not normalized_email(address):
                raise ValueError("Configure a valid SMTP_FROM_EMAIL and INTERVIEW_REPLY_TO_EMAIL")
        if "\r" in self.settings.smtp_from_name or "\n" in self.settings.smtp_from_name:
            raise ValueError("SMTP_FROM_NAME must be a single line")
        return {"from_email": normalized_email(self.settings.smtp_from_email), "from_name": self.settings.smtp_from_name,
            "reply_to": normalized_email(self.settings.interview_reply_to_email)}

    def batch(self, db, user_id, batch_id):
        self.actor(db, user_id)
        batch = db.scalar(select(InterviewBatch).where(InterviewBatch.id == batch_id, InterviewBatch.created_by_user_id == user_id))
        if not batch:
            raise LookupError("Invitation batch not found")
        deliveries = list(db.scalars(select(InterviewDelivery).where(InterviewDelivery.batch_id == batch.id).order_by(InterviewDelivery.id)))
        return {"id": batch.id, "kind": batch.kind, "job_posting_id": batch.job_posting_id, "status": batch.status,
            "recipient_count": len(batch.snapshot["recipients"]), "recipients": [self.links.preview(item) for item in batch.snapshot["recipients"]],
            "sender": batch.snapshot["sender"], "selection": batch.snapshot.get("selection"),
            "deliveries": [{"id": item.id, "schedule_id": item.schedule_id, "application_id": item.application_id,
                "masked_email": masked_email(item.recipient_email), "status": item.status, "attempts": item.attempts,
                "in_flight": item.in_flight, "retryable": self.retryable(db, item),
                "error_category": item.error_category, "sent_at": item.sent_at.isoformat() if item.sent_at else None} for item in deliveries],
            "sent": sum(item.status == "sent" for item in deliveries), "failed": sum(item.status == "failed" for item in deliveries),
            "uncertain": sum(item.status == "uncertain" for item in deliveries), "pending": sum(item.status == "pending" for item in deliveries)}

    def confirm(self, db, user_id, batch_id, data):
        self.actor(db, user_id, lock=True)  # Serializes scheduling/conflicts across all this interviewer's jobs.
        batch = db.scalar(select(InterviewBatch).where(InterviewBatch.id == batch_id, InterviewBatch.created_by_user_id == user_id).with_for_update())
        if not batch:
            raise LookupError("Invitation batch not found")
        if batch.status not in {"draft", "sending", "completed"}:
            raise InterviewConflict("This draft was invalidated. Prepare a new invitation preview.")
        if batch.status != "draft":
            if {"batch_id": batch.id, "hash": batch.confirmation_hash} != self.decode("invitation", data.confirmation_token, user_id, allow_expired=True):
                raise InterviewConflict("Confirmation does not match this batch")
            return self.batch(db, user_id, batch.id)
        token = self.decode("invitation", data.confirmation_token, user_id)
        if token != {"batch_id": batch.id, "hash": batch.confirmation_hash} or fingerprint(batch.snapshot) != batch.confirmation_hash:
            raise InterviewConflict("Draft changed; prepare and confirm a new preview")
        if self.mail_identity() != batch.snapshot["sender"]:
            raise InterviewConflict("Email sender settings changed; prepare a new preview")
        if any(not item.get("join_material") or item["join_material"].get("access_policy") != ACCESS_POLICY for item in batch.snapshot["recipients"]):
            raise InterviewConflict("This draft uses older interview-access rules. Prepare a new invitation preview.")
        selection = self.validate_selection(db, user_id, batch.snapshot["selection_token"])
        schedule_data = PrepareInvites.model_validate({**batch.snapshot["schedule"], "selection_token": batch.snapshot["selection_token"]})
        slots = allocate_slots(schedule_data, len(selection["selected"]))
        self.conflicts(db, user_id, slots)
        existing = db.scalar(select(InterviewBatch).where(InterviewBatch.created_by_user_id == user_id, InterviewBatch.idempotency_key == data.idempotency_key))
        if existing:
            raise InterviewConflict("This idempotency key belongs to another batch")
        for preview in batch.snapshot["recipients"]:
            schedule = InterviewSchedule(batch_id=batch.id, job_posting_id=batch.job_posting_id, application_id=preview["application_id"],
                stage=selection["stage"], calendar_uid=preview["calendar_uid"], start_utc=datetime.fromisoformat(preview["start_utc"]),
                end_utc=datetime.fromisoformat(preview["end_utc"]), timezone=preview["timezone"], local_start=preview["local_start"],
                duration_minutes=preview["duration_minutes"], buffer_minutes=preview["buffer_minutes"], mode=preview["mode"], created_by_user_id=user_id)
            self.links.install(schedule, preview["join_material"])
            db.add(schedule)
            db.flush()
            self.create_delivery(db, batch, schedule, preview)
        batch.status, batch.confirmed_at, batch.idempotency_key = "sending", datetime.now(UTC), data.idempotency_key
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise InterviewConflict("A concurrent scheduling request changed these candidates. Create a new preview.") from None
        return self.batch(db, user_id, batch.id)

    def create_delivery(self, db, batch, schedule, preview):
        application = db.get(CandidateApplication, schedule.application_id)
        candidate = db.get(Candidate, application.candidate_id)
        email = normalized_email(candidate.email)
        if not email:
            raise InterviewConflict("Candidate email changed; prepare a new preview")
        calendar = calendar_invitation(self.settings, schedule.calendar_uid, schedule.sequence, preview, preview["subject"], preview["body"], email, batch.snapshot["sender"])
        db.add(InterviewDelivery(batch_id=batch.id, schedule_id=schedule.id, application_id=application.id,
            recipient_email=email, subject=preview["subject"], body=preview["body"], calendar_text=calendar,
            calendar_checksum=hashlib.sha256(calendar.encode()).hexdigest(), sequence=schedule.sequence,
            join_material=preview.get("join_material")))

    def deliver_batch(self, batch_id):
        from sqlalchemy.exc import SQLAlchemyError
        import logging
        try:
            with self.session_factory() as db:
                self.deliver_pending(db, batch_id)
        except SQLAlchemyError:
            # SQL exception parameters can contain private invitation snapshots.
            logging.getLogger(__name__).warning("Interview delivery database error; durable status requires recovery")

    def deliver_pending(self, db, batch_id):
        ids = list(db.scalars(select(InterviewDelivery.id).where(InterviewDelivery.batch_id == batch_id, InterviewDelivery.status == "pending").order_by(InterviewDelivery.id)))
        for delivery_id in ids:
            delivery = db.scalar(select(InterviewDelivery).where(InterviewDelivery.id == delivery_id).with_for_update())
            if not delivery or delivery.status != "pending":
                db.rollback()
                continue
            schedule = db.get(InterviewSchedule, delivery.schedule_id)
            if not schedule or schedule.sequence != delivery.sequence or schedule.status not in ACTIVE:
                delivery.status, delivery.error_category = "failed", "superseded_calendar_sequence"
                db.commit()
                continue
            if utc(schedule.start_utc) <= datetime.now(UTC):
                delivery.status, delivery.error_category = "failed", "interview_start_has_passed"
                db.commit()
                continue
            application = db.get(CandidateApplication, delivery.application_id)
            candidate = db.get(Candidate, application.candidate_id) if application and application.candidate_id else None
            if not application or application.status in {ApplicationStatus.WITHDRAWN, ApplicationStatus.REJECTED} or not candidate or normalized_email(candidate.email) != delivery.recipient_email:
                delivery.status, delivery.error_category = "failed", "recipient_became_ineligible"
                db.commit()
                continue
            if delivery.join_material and (schedule.join_token_revoked_at or schedule.join_token_hash != delivery.join_material["hash"]
                or not schedule.join_token_expires_at or utc(schedule.join_token_expires_at) <= datetime.now(UTC)
                or schedule.room_status in {"ending", "ended", "cancelled"}):
                delivery.status, delivery.error_category = "failed", "candidate_join_link_changed"
                db.commit()
                continue
            # Crash after this commit is conservatively uncertain: never auto-retry.
            delivery.status, delivery.in_flight = "uncertain", True
            delivery.attempts += 1
            db.commit()
            try:
                transport = self.links.delivery(delivery)
                transport.sender_snapshot = db.get(InterviewBatch, batch_id).snapshot["sender"]
                delivery.calendar_checksum = hashlib.sha256(transport.calendar_text.encode()).hexdigest()
                db.commit()
                result = self.sender.send(transport)
                if not isinstance(result, dict):
                    raise ValueError("Invalid transport result")
            except Exception:
                result = {"status": "uncertain", "error_category": "transport_acceptance_unknown"}
            delivery.status = result["status"] if result.get("status") in {"sent", "failed", "uncertain"} else "uncertain"
            delivery.error_category = result.get("error_category")
            delivery.provider_message_id = result.get("provider_message_id")
            delivery.in_flight = False
            delivery.sent_at = datetime.now(UTC) if delivery.status == "sent" else None
            db.commit()
        batch = db.get(InterviewBatch, batch_id)
        outstanding = db.scalar(select(func.count(InterviewDelivery.id)).where(InterviewDelivery.batch_id == batch_id,
            (InterviewDelivery.status == "pending") | (InterviewDelivery.in_flight == True)))
        if batch and not outstanding:
            batch.status = "completed"
            db.commit()

    @staticmethod
    def retryable(db, item):
        schedule = db.get(InterviewSchedule, item.schedule_id)
        application = db.get(CandidateApplication, item.application_id)
        candidate = db.get(Candidate, application.candidate_id) if application and application.candidate_id else None
        return bool(item.status == "failed" and not item.in_flight and item.attempts > 0
            and schedule and item.sequence == schedule.sequence and schedule.status in ACTIVE
            and utc(schedule.start_utc) > datetime.now(UTC) and application
            and application.status not in {ApplicationStatus.WITHDRAWN, ApplicationStatus.REJECTED}
            and candidate and normalized_email(candidate.email) == item.recipient_email)

    def retry(self, db, user_id, delivery_id, expected_attempts):
        self.actor(db, user_id, lock=True)
        item = db.scalar(select(InterviewDelivery).join(InterviewBatch).where(InterviewDelivery.id == delivery_id,
            InterviewBatch.created_by_user_id == user_id).with_for_update())
        if not item:
            raise LookupError("Delivery not found")
        if not self.retryable(db, item) or item.attempts != expected_attempts:
            raise InterviewConflict("Only the latest failed delivery can be retried. Sent, pending, uncertain or stale deliveries cannot be retried.")
        item.status = "pending"
        db.get(InterviewBatch, item.batch_id).status = "sending"
        db.commit()
        return self.batch(db, user_id, item.batch_id)

    def schedules(self, db, user_id):
        self.actor(db, user_id)
        items = []
        for schedule in db.scalars(select(InterviewSchedule).where(InterviewSchedule.created_by_user_id == user_id).order_by(InterviewSchedule.start_utc, InterviewSchedule.id)):
            application = db.get(CandidateApplication, schedule.application_id)
            candidate = db.get(Candidate, application.candidate_id) if application and application.candidate_id else None
            job = self.job(db, user_id, schedule.job_posting_id)
            last = db.scalar(select(InterviewDelivery).where(InterviewDelivery.schedule_id == schedule.id).order_by(InterviewDelivery.sequence.desc()))
            items.append({"id": schedule.id, "application_id": schedule.application_id, "candidate_name": candidate.name if candidate else "Unnamed candidate",
                "job_posting_id": schedule.job_posting_id, "job_title": job.title, "stage": schedule.stage,
                "start_utc": utc(schedule.start_utc).isoformat(), "end_utc": utc(schedule.end_utc).isoformat(),
                "local_start": schedule.local_start, "timezone": schedule.timezone, "duration_minutes": schedule.duration_minutes,
                "status": schedule.status, "sequence": schedule.sequence, "version": schedule.version, "meeting_url": schedule.meeting_url,
                "room_status": schedule.room_status, "has_join_link": bool(schedule.join_token_hash),
                "delivery_status": last.status if last else "pending", "delivery_id": last.id if last else None,
                "delivery_in_flight": last.in_flight if last else False,
                "delivery_retryable": self.retryable(db, last) if last else False,
                "delivery_attempts": last.attempts if last else 0, "history": schedule.history, "batch_id": last.batch_id if last else schedule.batch_id})
        return items

    def preview_reschedule(self, db, user_id, data, *, approved_join_materials=None):
        self.actor(db, user_id)
        ids = list(dict.fromkeys(data.schedule_ids))
        schedules = list(db.scalars(select(InterviewSchedule).where(InterviewSchedule.id.in_(ids), InterviewSchedule.created_by_user_id == user_id)
            .order_by(InterviewSchedule.start_utc, InterviewSchedule.id)))
        if len(schedules) != len(ids):
            raise LookupError("Interview schedule not found")
        if len({item.job_posting_id for item in schedules}) != 1 or any(item.status not in ACTIVE for item in schedules):
            raise ValueError("Reschedule active interviews for one job at a time")
        if any(item.room_status not in {"scheduled", "waiting"} for item in schedules):
            raise InterviewConflict("An admitted or active interview cannot be rescheduled. End it first.")
        slots = allocate_slots(data, len(schedules))
        self.conflicts(db, user_id, slots, ids)
        recipients = []
        for schedule, slot in zip(schedules, slots):
            app = db.get(CandidateApplication, schedule.application_id)
            candidate = db.get(Candidate, app.candidate_id) if app and app.candidate_id else None
            if not app or app.status in {ApplicationStatus.WITHDRAWN, ApplicationStatus.REJECTED}:
                raise ValueError("The application is no longer eligible for an interview")
            if not candidate or not normalized_email(candidate.email):
                raise ValueError("The candidate no longer has a valid email")
            old = {"local_start": schedule.local_start, "timezone": schedule.timezone,
                "start_utc": utc(schedule.start_utc).isoformat(), "end_utc": utc(schedule.end_utc).isoformat()}
            recipient = {"schedule_id": schedule.id, "expected_version": schedule.version, "application_id": app.id,
                "calendar_uid": schedule.calendar_uid, "sequence": schedule.sequence + 1,
                "name": candidate.name, "masked_email": masked_email(candidate.email), "email_hash": fingerprint(candidate.email),
                "stage": schedule.stage, "old_schedule": old, **slot,
                **render_email(self.settings, {"name": candidate.name}, self.job(db, user_id, schedule.job_posting_id).title, schedule.stage, slot, data, old)}
            recipient = redact_join_links(recipient)
            recipient["join_material"] = (approved_join_materials or {}).get(schedule.id) or self.links.rescheduled_material(
                schedule, datetime.fromisoformat(slot["start_utc"]), datetime.fromisoformat(slot["end_utc"]))
            if approved_join_materials and recipient["join_material"]["hash"] == schedule.join_token_hash and (
                schedule.join_token_revoked_at or utc(schedule.join_token_expires_at) <= datetime.now(UTC)):
                raise InterviewConflict("Candidate link expired or was revoked. Prepare a new rescheduling preview.")
            self.links.url(recipient["join_material"])  # Check signing/domain configuration before approval.
            if JOIN_PLACEHOLDER not in recipient["body"]:
                recipient["body"] += "\n\nJoin your HireSense interview: " + JOIN_PLACEHOLDER
            recipients.append(recipient)
        identity = self.mail_identity()
        original_identity = db.get(InterviewBatch, schedules[0].batch_id).snapshot["sender"]
        identity.update({"from_email": original_identity["from_email"], "from_name": original_identity["from_name"]})
        if any(db.get(InterviewBatch, item.batch_id).snapshot["sender"]["from_email"] != identity["from_email"] for item in schedules):
            raise InterviewConflict("Batch rescheduling requires the same original calendar organizer")
        payload = {"job_posting_id": schedules[0].job_posting_id, "schedule": redact_join_links(data.model_dump(mode="json")),
            "recipients": recipients, "sender": identity}
        return {"recipient_count": len(recipients), "recipients": [self.links.preview(item) for item in recipients], "sender": payload["sender"],
            "confirmation_token": self.token("reschedule", payload, user_id)}

    def confirm_reschedule(self, db, user_id, data):
        self.actor(db, user_id, lock=True)
        payload = self.decode("reschedule", data.confirmation_token, user_id, allow_expired=True)
        digest = fingerprint(payload)
        existing = db.scalar(select(InterviewBatch).where(InterviewBatch.created_by_user_id == user_id, InterviewBatch.confirmation_hash == digest))
        if existing:
            return self.batch(db, user_id, existing.id)
        self.decode("reschedule", data.confirmation_token, user_id)  # Expired tokens may acknowledge, never mutate.
        if db.scalar(select(InterviewBatch.id).where(InterviewBatch.created_by_user_id == user_id, InterviewBatch.idempotency_key == data.idempotency_key)):
            raise InterviewConflict("Idempotency key belongs to another invitation")
        materials = {item["schedule_id"]: item.get("join_material") for item in payload["recipients"]}
        if any(not item or item.get("access_policy") != ACCESS_POLICY for item in materials.values()):
            raise InterviewConflict("Prepare a new rescheduling preview with the current interview-access rules")
        # Serialize against admission, credential issuance, link changes and End,
        # not just another scheduling request that locks the interviewer account.
        locked = list(db.scalars(select(InterviewSchedule).where(InterviewSchedule.id.in_(materials),
            InterviewSchedule.created_by_user_id == user_id).order_by(InterviewSchedule.id)
            .with_for_update().execution_options(populate_existing=True)))
        if len(locked) != len(materials):
            raise LookupError("Interview schedule not found")
        fresh = self.preview_reschedule(db, user_id, RescheduleRequest.model_validate(payload["schedule"]), approved_join_materials=materials)
        fresh_payload = self.decode("reschedule", fresh["confirmation_token"], user_id)
        if fingerprint(fresh_payload) != digest:
            raise InterviewConflict("Schedule or recipient changed. Prepare a new rescheduling preview.")
        batch = InterviewBatch(job_posting_id=payload["job_posting_id"], kind="reschedule", status="sending", snapshot=payload,
            created_by_user_id=user_id, confirmed_at=datetime.now(UTC), confirmation_hash=digest, idempotency_key=data.idempotency_key)
        db.add(batch)
        db.flush()
        for preview in payload["recipients"]:
            schedule = db.get(InterviewSchedule, preview["schedule_id"])
            schedule.history = [*schedule.history, {**preview["old_schedule"], "sequence": schedule.sequence,
                "version": schedule.version, "changed_at": datetime.now(UTC).isoformat(), "reason": payload["schedule"]["reason"]}]
            schedule.start_utc, schedule.end_utc = datetime.fromisoformat(preview["start_utc"]), datetime.fromisoformat(preview["end_utc"])
            schedule.timezone, schedule.local_start = preview["timezone"], preview["local_start"]
            schedule.duration_minutes, schedule.buffer_minutes, schedule.mode = preview["duration_minutes"], preview["buffer_minutes"], preview["mode"]
            schedule.sequence += 1
            schedule.version += 1
            schedule.status = "rescheduled"
            if schedule.room_name and schedule.room_name != preview["join_material"]["room_name"]:
                schedule.media_cleanup_rooms = list(dict.fromkeys([*(schedule.media_cleanup_rooms or []), schedule.room_name]))
            self.links.install(schedule, preview["join_material"])
            from app.models.interview import CandidateInterviewSession
            db.execute(CandidateInterviewSession.__table__.update().where(CandidateInterviewSession.interview_id == schedule.id).values(revoked_at=datetime.now(UTC)))
            schedule.room_status, schedule.candidate_waiting_at, schedule.candidate_last_seen_at = "scheduled", None, None
            schedule.candidate_admitted_at = None
            schedule.room_version += 1
            self.create_delivery(db, batch, schedule, preview)
        db.commit()
        return self.batch(db, user_id, batch.id)

    @staticmethod
    def recover_interrupted(db):
        # Single-backend-worker recovery: an interrupted claimed attempt is uncertain.
        for delivery in db.scalars(select(InterviewDelivery).where(InterviewDelivery.in_flight == True)):
            delivery.in_flight = False
            delivery.status = "uncertain"
            delivery.error_category = "backend_restarted_acceptance_unknown"
        db.commit()
        pending_batches = list(db.scalars(select(InterviewDelivery.batch_id).join(InterviewBatch)
            .where(InterviewDelivery.status == "pending", InterviewBatch.confirmed_at.is_not(None)).distinct()))
        for batch in db.scalars(select(InterviewBatch).where(InterviewBatch.status == "sending")):
            if batch.id not in pending_batches:
                batch.status = "completed"
        db.commit()
        return pending_batches
