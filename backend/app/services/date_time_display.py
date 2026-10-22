"""Readable dates for user-facing prose only; storage and API values stay ISO/UTC."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

APP_TIME_ZONE = "Asia/Dhaka"
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sept", "Oct", "Nov", "Dec")


def time_zone_label(zone=APP_TIME_ZONE):
    return "Dhaka time" if zone == APP_TIME_ZONE else "UTC" if zone in {"UTC", "Etc/UTC"} else zone.replace("_", " ")


def _local(value, zone):
    if not value:
        raise ValueError("Date is missing")
    instant = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    return instant.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(zone)) if instant.tzinfo is None else instant.astimezone(ZoneInfo(zone))


def format_date(value, zone=APP_TIME_ZONE):
    try:
        local = _local(value, "UTC" if isinstance(value, str) and len(value) == 10 else zone)
        return f"{local.day} {MONTHS[local.month - 1]} {local.year}"
    except (ValueError, TypeError, KeyError):
        return "Not provided"


def format_time(value, zone=APP_TIME_ZONE):
    try:
        local = _local(value, zone)
        return f"{local.hour % 12 or 12}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"
    except (ValueError, TypeError, KeyError):
        return "Not provided"


def format_date_time(value, zone=APP_TIME_ZONE):
    day, time = format_date(value, zone), format_time(value, zone)
    return "Not provided" if "Not provided" in (day, time) else f"{day} at {time} ({time_zone_label(zone)})"


def format_time_range(start, end, zone=APP_TIME_ZONE):
    first, last, begins, ends = format_date(start, zone), format_date(end, zone), format_time(start, zone), format_time(end, zone)
    if "Not provided" in (first, last, begins, ends):
        return "Not provided"
    return f"{first}, {begins} – {ends} ({time_zone_label(zone)})" if first == last else f"{first} at {begins} – {last} at {ends} ({time_zone_label(zone)})"
