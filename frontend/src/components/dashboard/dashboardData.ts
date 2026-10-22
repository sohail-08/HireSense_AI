import type { JobDescriptionResponse, ScreeningJobOption } from "../../types";
import { APP_TIME_ZONE } from "../../utils/dateTime";

export type DashboardInterview = {
  id: number; candidate_name: string; job_title: string; start_utc: string;
  end_utc: string; duration_minutes: number; status: string; room_status: string;
};
export type DashboardData = {
  jobs?: JobDescriptionResponse[];
  screening?: ScreeningJobOption[];
  interviews?: DashboardInterview[];
};

function timestamp(value: string) {
  if (!value) return NaN;
  return Date.parse(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : value + "Z");
}
export function interviewClosed(item: DashboardInterview) {
  return ["completed", "cancelled"].includes(item.status) || ["ended", "ending", "cancelled"].includes(item.room_status);
}
export function interviewLive(item: DashboardInterview) { return ["ready", "active", "waiting"].includes(item.room_status); }
export function dashboardDay(value: number) {
  return new Intl.DateTimeFormat("en-CA", { timeZone: APP_TIME_ZONE, year: "numeric", month: "2-digit", day: "2-digit" }).format(value);
}
export function dashboardSummary(data: DashboardData, now: number) {
  const open = data.interviews?.filter(item => !interviewClosed(item) && Number.isFinite(timestamp(item.start_utc)));
  const upcoming = open?.filter(item => interviewLive(item) || timestamp(item.end_utc) > now || timestamp(item.start_utc) >= now)
    .sort((a, b) => Number(interviewLive(b)) - Number(interviewLive(a)) || timestamp(a.start_utc) - timestamp(b.start_utc));
  return {
    published: data.screening?.filter(item => item.posting_status === "published").length,
    applications: data.screening?.reduce((sum, item) => sum + item.application_count, 0),
    pending: data.screening?.reduce((sum, item) => sum + item.pending_count, 0),
    drafts: data.jobs?.filter(item => item.status === "draft").length,
    approved: data.jobs?.filter(item => item.status === "approved").length,
    completed: data.interviews?.filter(item => item.status === "completed" || item.room_status === "ended").length,
    overdue: open?.filter(item => !interviewLive(item) && timestamp(item.start_utc) < now && timestamp(item.end_utc) <= now).length,
    today: upcoming?.filter(item => dashboardDay(timestamp(item.start_utc)) === dashboardDay(now)).length,
    upcoming,
    roles: data.screening?.filter(item => item.application_count > 0 || item.posting_status === "published")
      .sort((a, b) => b.pending_count - a.pending_count || b.application_count - a.application_count).slice(0, 4),
  };
}
