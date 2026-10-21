export const applicationStatuses: Record<string, { label: string; style: string }> = {
  received: { label: "New", style: "bg-blue-50 text-blue-700 ring-blue-100" },
  screening: { label: "Screening", style: "bg-amber-50 text-amber-800 ring-amber-100" },
  reviewed: { label: "Screened", style: "bg-teal-50 text-teal-800 ring-teal-100" },
  shortlisted: { label: "Shortlisted", style: "bg-emerald-50 text-emerald-800 ring-emerald-100" },
  rejected: { label: "Not selected", style: "bg-slate-100 text-slate-600 ring-slate-200" },
  withdrawn: { label: "Withdrawn", style: "bg-slate-100 text-slate-600 ring-slate-200" },
};

export function candidateDate(value: string, full = false): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Not provided" : full ? date.toLocaleString() : date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function cvSize(bytes: number): string {
  return bytes < 1024 * 1024 ? `${Math.ceil(bytes / 1024)} KB` : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function safeCandidateWebsite(value: string | null): string | undefined {
  if (!value) return undefined;
  try { const url = new URL(value); return ["https:", "http:"].includes(url.protocol) ? url.href : undefined; }
  catch { return undefined; }
}
