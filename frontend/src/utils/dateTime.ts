// Display only: API timestamps, calendar instants and form values stay unchanged.
export const APP_TIME_ZONE = "Asia/Dhaka";
const unavailable = "Not provided";

function instant(value: string | null | undefined) {
  if (!value?.trim()) return undefined;
  // Legacy backend timestamps without an offset are UTC, never the device's zone.
  const raw = value.trim();
  const calendar = raw.match(/^(\d{4}-\d{2}-\d{2})(?:T|$)/)?.[1];
  if (calendar) {
    const day = new Date(calendar + "T00:00:00Z");
    if (Number.isNaN(day.getTime()) || day.toISOString().slice(0, 10) !== calendar) return undefined;
  }
  const normalized = /^\d{4}-\d{2}-\d{2}T/.test(raw) && !/(Z|[+-]\d{2}:?\d{2})$/i.test(raw) ? raw + "Z" : raw;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? undefined : date;
}

export function timeZoneLabel(timeZone = APP_TIME_ZONE) {
  return timeZone === APP_TIME_ZONE ? "Dhaka time" : ["UTC", "Etc/UTC"].includes(timeZone) ? "UTC" : timeZone.replaceAll("_", " ");
}

export function formatDate(value: string | null | undefined, timeZone = APP_TIME_ZONE) {
  const date = instant(value);
  if (!date) return unavailable;
  try {
    // A calendar-only date must not move to the previous day in another zone.
    return new Intl.DateTimeFormat("en-GB", { timeZone: /^\d{4}-\d{2}-\d{2}$/.test(value!) ? "UTC" : timeZone,
      day: "numeric", month: "short", year: "numeric" }).format(date);
  } catch { return unavailable; }
}

export function formatTime(value: string | null | undefined, timeZone = APP_TIME_ZONE) {
  const date = instant(value);
  if (!date) return unavailable;
  try {
    return new Intl.DateTimeFormat("en-US", { timeZone, hour: "numeric", minute: "2-digit", hour12: true }).format(date);
  } catch { return unavailable; }
}

export function formatDateTime(value: string | null | undefined, timeZone = APP_TIME_ZONE) {
  const date = formatDate(value, timeZone), time = formatTime(value, timeZone);
  return date === unavailable || time === unavailable ? unavailable : `${date} at ${time} (${timeZoneLabel(timeZone)})`;
}

export function formatTimeRange(start: string | null | undefined, end: string | null | undefined, timeZone = APP_TIME_ZONE) {
  const first = formatDate(start, timeZone), last = formatDate(end, timeZone);
  const begins = formatTime(start, timeZone), ends = formatTime(end, timeZone);
  if ([first, last, begins, ends].includes(unavailable)) return unavailable;
  return `${first === last ? `${first}, ${begins}` : `${first} at ${begins}`} – ${first === last ? ends : `${last} at ${ends}`} (${timeZoneLabel(timeZone)})`;
}
