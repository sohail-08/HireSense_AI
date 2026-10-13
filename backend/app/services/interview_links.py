"""Hash-only invitation links and transient email rendering.

A CSPRNG nonce and opaque invitation ID are persisted, not a bearer token. A dedicated
server HMAC key derives its unpredictable 256-bit bearer value. This permits exact
preview/send/retrieve parity without storing tokens in outbox or chat snapshots.
"""
import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from urllib.parse import urlsplit
from icalendar import Calendar, vText
from app.config import get_settings
from app.services.interview_content import utc

JOIN_PLACEHOLDER = "[[HIRESENSE_CANDIDATE_JOIN_LINK]]"
JOIN_PATTERN = re.compile(r"(?:https?://[^\s<>\"{}]+)?/interview/join/[A-Za-z0-9_-]{43}")
UTC = timezone.utc


def secret_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def redact_join_links(value):
    if isinstance(value, str):
        return JOIN_PATTERN.sub(JOIN_PLACEHOLDER, value)
    if isinstance(value, dict):
        return {key: redact_join_links(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_join_links(item) for item in value]
    return value


class InterviewLinks:
    def __init__(self, settings=None, now=None):
        self.settings = settings or get_settings()
        self.now = now or (lambda: datetime.now(UTC))

    def key(self):
        key = self.settings.interview_link_secret or self.settings.jwt_secret_key
        return key.get_secret_value().encode()

    def token(self, material):
        message = f"hiresense-candidate-v1|{material['join_id']}|{material['application_id']}|{material['nonce']}"
        return base64.urlsafe_b64encode(hmac.new(self.key(), message.encode(), hashlib.sha256).digest()).decode().rstrip("=")

    def window(self, start, end):
        start, end = utc(start), utc(end)
        opens = start - timedelta(minutes=self.settings.interview_room_early_minutes)
        closes = min(start + timedelta(minutes=self.settings.interview_room_late_minutes),
            end + timedelta(minutes=self.settings.interview_room_end_grace_minutes))
        return opens, closes

    def material(self, application_id, start, end, generation=1, room_name=None):
        opens, closes = self.window(start, end)
        expires = min(closes, self.now() + timedelta(days=self.settings.interview_link_max_days))
        if expires <= opens:
            raise ValueError("Interview is beyond the configured link lifetime. Choose an earlier date or increase INTERVIEW_LINK_MAX_DAYS.")
        value = {"room_name": room_name or "hs-" + uuid4().hex, "application_id": application_id,
            "join_id": uuid4().hex,
            "nonce": secrets.token_hex(32), "generation": generation,
            "base_url": self.settings.interview_join_base_url.rstrip("/"),
            "expires_at": expires.isoformat()}
        value["hash"] = secret_hash(self.token(value))
        return value

    def current(self, schedule):
        if not schedule.join_token_hash or not schedule.join_token_nonce or not schedule.room_name or not schedule.join_token_id:
            return None
        return {"room_name": schedule.room_name, "application_id": schedule.application_id,
            "join_id": schedule.join_token_id,
            "nonce": schedule.join_token_nonce, "generation": schedule.join_generation,
            "base_url": schedule.join_base_url or self.settings.interview_join_base_url.rstrip("/"),
            "hash": schedule.join_token_hash, "expires_at": utc(schedule.join_token_expires_at).isoformat()}

    @staticmethod
    def install(schedule, material):
        schedule.room_name, schedule.join_token_nonce = material["room_name"], material["nonce"]
        schedule.join_token_id = material["join_id"]
        schedule.join_token_hash, schedule.join_generation = material["hash"], material["generation"]
        schedule.join_token_expires_at = datetime.fromisoformat(material["expires_at"])
        schedule.join_base_url = material["base_url"]
        schedule.join_token_revoked_at = None

    def rescheduled_material(self, schedule, start, end):
        material = self.current(schedule)
        if not material or schedule.join_token_revoked_at or utc(schedule.join_token_expires_at) <= self.now():
            return self.material(schedule.application_id, start, end, schedule.join_generation + 1)
        # Invitation identity is independent of the media room. A reschedule can
        # retain its valid email token while retiring all previous media grants.
        material["room_name"] = "hs-" + uuid4().hex
        opens, closes = self.window(start, end)
        expires = min(closes, self.now() + timedelta(days=self.settings.interview_link_max_days))
        if expires <= opens:
            raise ValueError("Interview is beyond the configured link lifetime. Choose an earlier date or increase INTERVIEW_LINK_MAX_DAYS.")
        material["expires_at"] = expires.isoformat()
        return material

    def url(self, material):
        token = self.token(material)
        if not hmac.compare_digest(secret_hash(token), material["hash"]):
            raise ValueError("Join-link signing settings changed; rotate the candidate link")
        base = material.get("base_url", self.settings.interview_join_base_url).rstrip("/")
        parsed = urlsplit(base)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.query or parsed.fragment or parsed.username:
            raise ValueError("Configure a valid INTERVIEW_JOIN_BASE_URL")
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Candidate join links require HTTPS outside localhost")
        return base + "/interview/join/" + token

    def preview(self, recipient):
        result = {key: value for key, value in recipient.items() if key != "join_material"}
        if recipient.get("join_material"):
            link = self.url(recipient["join_material"])
            result["join_url"] = link
            result["body"] = result["body"].replace(JOIN_PLACEHOLDER, link)
            result["subject"] = result["subject"].replace(JOIN_PLACEHOLDER, link)
        return result

    def delivery(self, item):
        """A transient transport copy: raw tokens never assigned to ORM attributes."""
        from types import SimpleNamespace
        if not item.join_material:
            return SimpleNamespace(**{key: getattr(item, key) for key in ("id", "recipient_email", "subject", "body", "calendar_text")})
        link = self.url(item.join_material)
        calendar = Calendar.from_ical(item.calendar_text)
        for event in calendar.walk("VEVENT"):
            description = str(event.get("description", "")).replace(JOIN_PLACEHOLDER, link)
            event["description"] = vText(description)
            event["summary"] = vText(str(event.get("summary", "")).replace(JOIN_PLACEHOLDER, link))
        return SimpleNamespace(id=item.id, recipient_email=item.recipient_email,
            subject=item.subject.replace(JOIN_PLACEHOLDER, link), body=item.body.replace(JOIN_PLACEHOLDER, link),
            calendar_text=calendar.to_ical().decode())
