import { expect, it } from "vitest";
import { formatDate, formatTime, formatDateTime, formatTimeRange, timeZoneLabel } from "../../src/utils/dateTime";
import { formatRoomTime } from "../../src/components/interviews/roomState";
import { candidateDate } from "../../src/components/candidates/candidateDisplay";

it("shows a readable date and AM/PM time in Dhaka regardless of the device locale", () => {
  expect(formatDateTime("2026-10-22T02:00:59Z")).toBe("22 Oct 2026 at 8:00 AM (Dhaka time)");
  expect(formatRoomTime("2026-10-22T02:00:59Z", "Asia/Dhaka")).toBe("22 Oct 2026 at 8:00 AM (Dhaka time)");
  expect(candidateDate("2026-10-22T02:00:59Z", true)).toBe("22 Oct 2026 at 8:00 AM (Dhaka time)");
  expect(candidateDate("2026-10-22T02:00:59Z")).toBe("22 Oct 2026");
});

it("uses 12 AM for midnight and 12 PM for noon", () => {
  expect(formatTime("2026-10-22T00:00:00+06:00")).toBe("12:00 AM");
  expect(formatTime("2026-10-22T12:00:00+06:00")).toBe("12:00 PM");
  expect(formatTime("2026-10-22T17:05:00+06:00")).toBe("5:05 PM");
});

it("respects explicit interview zones, DST and day boundaries without using the host zone", () => {
  expect(formatDateTime("2026-10-21T20:15:00Z")).toBe("22 Oct 2026 at 2:15 AM (Dhaka time)");
  expect(formatTime("2026-07-01T12:00:00Z", "America/New_York")).toBe("8:00 AM");
  expect(formatTime("2026-01-01T12:00:00Z", "America/New_York")).toBe("7:00 AM");
  expect(formatDate("2026-10-22", "America/Los_Angeles")).toBe("22 Oct 2026");
  expect(formatDateTime("2026-10-22T02:00:00")).toBe("22 Oct 2026 at 8:00 AM (Dhaka time)");
  expect(timeZoneLabel("UTC")).toBe("UTC");
});

it("makes same-day and overnight schedule ranges unambiguous", () => {
  expect(formatTimeRange("2026-10-22T08:00:00+06:00", "2026-10-22T08:30:00+06:00")).toBe("22 Oct 2026, 8:00 AM – 8:30 AM (Dhaka time)");
  expect(formatTimeRange("2026-10-22T23:45:00+06:00", "2026-10-23T00:15:00+06:00")).toBe("22 Oct 2026 at 11:45 PM – 23 Oct 2026 at 12:15 AM (Dhaka time)");
});

it("handles missing, invalid dates and unknown zones without crashing pages", () => {
  for (const raw of [null, undefined, "", "invalid", "2026-02-30"]) expect(formatDateTime(raw)).toBe("Not provided");
  expect(formatDateTime("2026-10-22T02:00:00Z", "Mars/Olympus")).toBe("Not provided");
  expect(formatTimeRange(undefined, "2026-10-22T08:30:00+06:00")).toBe("Not provided");
});
