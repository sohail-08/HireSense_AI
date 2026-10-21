"""Timezone-safe slot allocation, deterministic email rendering and iCalendar."""
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formataddr, make_msgid
import smtplib
import ssl
from string import Formatter
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from icalendar import Calendar, Event, vCalAddress, vText
from app.services.date_time_display import format_date, format_time, format_date_time, time_zone_label

UTC = timezone.utc


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def allocate_slots(data, count, now=None):
    if data.mode != "sequential":
        raise ValueError("Only sequential individual interview slots are supported")
    try:
        zone = ZoneInfo(data.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Unsupported IANA time zone") from None
    if data.start_time.tzinfo:
        raise ValueError("Use a local start time and an IANA time zone")
    naive = datetime.combine(data.date, data.start_time)
    local = naive.replace(tzinfo=zone)
    if local.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != naive:
        raise ValueError("This local time does not exist due to a daylight-saving change")
    if local.utcoffset() != naive.replace(tzinfo=zone, fold=1).utcoffset():
        raise ValueError("This local time is ambiguous; choose a different time")
    start = local.astimezone(UTC)
    if start <= (now or datetime.now(UTC)):
        raise ValueError("Interview start must be in the future")
    slots = []
    for index in range(count):
        offset = index * (data.duration_minutes + data.buffer_minutes)
        begins = start + timedelta(minutes=offset)
        end = begins + timedelta(minutes=data.duration_minutes)
        slots.append({"start_utc": begins.isoformat(), "end_utc": end.isoformat(),
            "local_start": begins.astimezone(zone).isoformat(), "local_end": end.astimezone(zone).isoformat(),
            "timezone": data.timezone, "duration_minutes": data.duration_minutes,
            "buffer_minutes": data.buffer_minutes, "mode": data.mode})
    return slots


def render_email(settings, candidate, job_title, stage, slot, data, old=None):
    fields = {"candidate_name": candidate["name"], "job_title": job_title,
        "company_name": settings.interview_company_name, "local_date": format_date(slot["local_start"], slot["timezone"]),
        "local_start_time": format_time(slot["local_start"], slot["timezone"]), "timezone": time_zone_label(slot["timezone"]),
        "duration": str(slot["duration_minutes"]) + " minutes", "stage": stage,
        "contact_email": settings.interview_reply_to_email, "instructions": data.instructions,
        "old_schedule": "" if not old else format_date_time(old["local_start"], old["timezone"])}
    subject = data.subject_template or (("Interview rescheduled" if old else "Interview invitation") + " for {job_title} at {company_name}")
    body = data.body_template or ("Dear {candidate_name},\n\nThank you for your application for the {job_title} position.\n\n"
        "We would like to invite you to an interview:\nDate: {local_date}\nTime: {local_start_time} ({timezone})\n"
        "Duration: {duration}\nStage: {stage}\n\nPlease reply if you have questions or cannot attend.\nContact: {contact_email}\n\n"
        "{instructions}\n\nRegards,\n{company_name}")
    try:
        body_fields = set()
        for template in (subject, body):
            for _, key, format_spec, conversion in Formatter().parse(template):
                if key is not None and (key not in fields or format_spec or conversion):
                    raise ValueError("Unknown template field")
                if template == body and key:
                    body_fields.add(key)
        subject, body = subject.format_map(fields), body.format_map(fields)
    except (KeyError, ValueError, AttributeError, IndexError):
        raise ValueError("Unknown email template field or invalid template syntax") from None
    if data.body_template:
        # Editable prose cannot accidentally omit authoritative interview details.
        # These additions are included in the exact preview before confirmation.
        labels = {"candidate_name": "Candidate", "job_title": "Job", "company_name": "Company",
            "local_date": "Date", "local_start_time": "Start time", "timezone": "Time zone",
            "duration": "Duration", "stage": "Stage", "contact_email": "Contact", "instructions": "Instructions"}
        missing = [f"{label}: {fields[key]}" for key, label in labels.items() if key not in body_fields and fields[key]]
        if missing:
            body += "\n\nInterview details:\n" + "\n".join(missing)
    if old:
        body += "\n\nPrevious schedule: " + fields["old_schedule"] + "\nNew schedule: " + format_date_time(slot["local_start"], slot["timezone"])
        if getattr(data, "reason", ""):
            body += "\nReason: " + data.reason
    if "\r" in subject or "\n" in subject or len(subject) > 250:
        raise ValueError("Email subject must be a single line of at most 250 characters")
    return {"subject": subject, "body": body.strip(), "template_version": "interview-v2-readable-time"}


def calendar_invitation(settings, uid, sequence, slot, subject, body, recipient, sender=None):
    calendar = Calendar()
    calendar.add("prodid", "-//HireSense//Interview scheduling//EN")
    calendar.add("version", "2.0")
    calendar.add("method", "REQUEST")
    event = Event()
    event.add("uid", uid)
    event.add("sequence", sequence)
    event.add("dtstamp", datetime.now(UTC))
    event.add("dtstart", datetime.fromisoformat(slot["start_utc"]))
    event.add("dtend", datetime.fromisoformat(slot["end_utc"]))
    event.add("summary", subject)
    event.add("description", body)
    event.add("status", "CONFIRMED")
    organizer = vCalAddress("mailto:" + (sender or {}).get("from_email", settings.smtp_from_email))
    organizer.params["cn"] = vText((sender or {}).get("from_name", settings.smtp_from_name))
    event.add("organizer", organizer)
    attendee = vCalAddress("mailto:" + recipient)
    attendee.params["role"] = vText("REQ-PARTICIPANT")
    attendee.params["rsvp"] = vText("TRUE")
    event.add("attendee", attendee)
    calendar.add_component(event)
    return calendar.to_ical().decode("utf-8")


class SMTPInvitationSender:
    def __init__(self, settings):
        self.settings = settings

    def send(self, delivery):
        settings = self.settings
        if not settings.smtp_host:
            return {"status": "failed", "error_category": "smtp_not_configured"}
        identity = getattr(delivery, "sender_snapshot", {})
        header_values = [delivery.subject, delivery.recipient_email, identity.get("from_name", settings.smtp_from_name),
            identity.get("from_email", settings.smtp_from_email), identity.get("reply_to", settings.interview_reply_to_email)]
        if any("\r" in value or "\n" in value for value in header_values):
            return {"status": "failed", "error_category": "smtp_invalid_headers"}
        message = EmailMessage()
        message["From"] = formataddr((identity.get("from_name", settings.smtp_from_name), identity.get("from_email", settings.smtp_from_email)))
        message["To"] = delivery.recipient_email
        message["Reply-To"] = identity.get("reply_to", settings.interview_reply_to_email)
        message["Subject"] = delivery.subject
        message["Message-ID"] = make_msgid(domain="hiresense.local")
        message.set_content(delivery.body)
        message.add_attachment(delivery.calendar_text.encode("utf-8"), maintype="text", subtype="calendar",
            filename="interview.ics", params={"method": "REQUEST", "charset": "UTF-8"})
        smtp = None
        data_started = False
        try:
            smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds)
            smtp.ehlo()
            if settings.smtp_use_tls:
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
            from_email = identity.get("from_email", settings.smtp_from_email)
            code, _ = smtp.mail(from_email)
            if code != 250:
                return {"status": "failed", "error_category": "smtp_sender_rejected"}
            code, _ = smtp.rcpt(delivery.recipient_email)
            if code not in (250, 251):
                return {"status": "failed", "error_category": "smtp_recipient_rejected"}
            data_started = True
            code, _ = smtp.data(message.as_bytes(policy=SMTP))
            if code != 250:
                return {"status": "failed", "error_category": "smtp_data_rejected"}
            return {"status": "sent", "provider_message_id": str(message["Message-ID"]), "error_category": None}
        except smtplib.SMTPAuthenticationError:
            return {"status": "failed", "error_category": "smtp_authentication_failed"}
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError):
            return {"status": "failed", "error_category": "smtp_rejected"}
        except Exception:
            return {"status": "uncertain" if data_started else "failed", "error_category": "smtp_acceptance_unknown" if data_started else "smtp_connection_failed"}
        finally:
            if smtp:
                try:
                    smtp.close()
                except Exception:
                    pass
