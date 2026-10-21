"""Display-only formatting; no external services or persisted records."""
from datetime import datetime
import pytest
from app.services.date_time_display import format_date, format_time, format_date_time, format_time_range


def test_readable_dates_and_twelve_hour_times():
    assert format_date_time("2026-10-22T02:00:59Z") == "22 Oct 2026 at 8:00 AM (Dhaka time)"
    assert format_time("2026-10-22T00:00:00+06:00") == "12:00 AM"
    assert format_time("2026-10-22T12:00:00+06:00") == "12:00 PM"
    assert format_time("2026-10-22T17:05:00+06:00") == "5:05 PM"
    assert format_date_time(datetime(2026, 10, 22, 2)) == "22 Oct 2026 at 8:00 AM (Dhaka time)"


def test_zones_day_boundaries_and_dst():
    assert format_date_time("2026-10-21T20:15:00Z") == "22 Oct 2026 at 2:15 AM (Dhaka time)"
    assert format_time("2026-07-01T12:00:00Z", "America/New_York") == "8:00 AM"
    assert format_time("2026-01-01T12:00:00Z", "America/New_York") == "7:00 AM"
    assert format_date("2026-10-22", "America/Los_Angeles") == "22 Oct 2026"
    assert format_date_time("2026-10-22T02:00:00Z", "UTC") == "22 Oct 2026 at 2:00 AM (UTC)"


def test_same_day_and_overnight_ranges():
    assert format_time_range("2026-10-22T08:00:00+06:00", "2026-10-22T08:30:00+06:00") == "22 Oct 2026, 8:00 AM – 8:30 AM (Dhaka time)"
    assert format_time_range("2026-10-22T23:45:00+06:00", "2026-10-23T00:15:00+06:00") == "22 Oct 2026 at 11:45 PM – 23 Oct 2026 at 12:15 AM (Dhaka time)"


@pytest.mark.parametrize("value", [None, "", "invalid", "2026-02-30"])
def test_missing_or_invalid_values(value):
    assert format_date_time(value) == "Not provided"
    assert format_time_range(value, "2026-10-22T02:00:00Z") == "Not provided"


def test_unknown_time_zone_is_safe():
    assert format_date_time("2026-10-22T02:00:00Z", "Mars/Olympus") == "Not provided"
