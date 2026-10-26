// Match the default stage used by the invitation selection API. Status belongs
// to an application (not a name/email) and never comes from the CV ranking.
export type CandidateSchedule = {
  id: number; application_id: number; job_posting_id: number; stage: string;
  status: string; room_status: string; start_utc: string; timezone: string;
  delivery_status: string; delivery_in_flight: boolean;
};
export type SchedulingFilter = "all" | "not_scheduled" | "scheduled" | "completed";

export function blocksInvitation(schedule: CandidateSchedule) {
  return ["scheduled", "rescheduled"].includes(schedule.status);
}

export function candidateSchedules(items: CandidateSchedule[], jobId: number) {
  const byApplication = new Map<number, CandidateSchedule>();
  const ordered = items.filter(item => item.job_posting_id === jobId && item.stage === "technical")
    .sort((a, b) => Number(blocksInvitation(b)) - Number(blocksInvitation(a))
      || b.start_utc.localeCompare(a.start_utc) || b.id - a.id);
  for (const item of ordered) if (!byApplication.has(item.application_id)) byApplication.set(item.application_id, item);
  return byApplication;
}

export function schedulingStatus(schedule?: CandidateSchedule) {
  if (!schedule) return { label: "Not scheduled", group: "not_scheduled", style: "bg-amber-50 text-amber-800" } as const;
  if (schedule.status === "completed" || schedule.room_status === "ended") return { label: "Completed", group: "completed", style: "bg-emerald-50 text-emerald-800" } as const;
  if (schedule.status === "cancelled" || schedule.room_status === "cancelled") return { label: "Cancelled · can schedule again", group: "not_scheduled", style: "bg-slate-100 text-slate-600" } as const;
  const label = schedule.room_status === "ending" ? "Finishing interview"
    : ["ready", "active"].includes(schedule.room_status) ? "In progress"
    : schedule.room_status === "waiting" ? "Candidate waiting"
    : schedule.status === "rescheduled" ? "Rescheduled" : "Scheduled";
  return { label, group: "scheduled", style: "bg-blue-50 text-blue-700" } as const;
}
