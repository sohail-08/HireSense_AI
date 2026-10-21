import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiRequest } from "../api/apiClient";
import { ErrorMessage } from "../components/common/ErrorMessage";
import { InterviewSchedulingPanel } from "../components/interviews/InterviewSchedulingPanel";
import { useSupervisor } from "../components/assistant/SupervisorProvider";
import { formatDate, formatTime, timeZoneLabel } from "../utils/dateTime";

type Schedule = { id: number; application_id: number; candidate_name: string; job_title: string; stage: string; local_start: string; timezone: string;
  duration_minutes: number; status: string; room_status: string; sequence: number; delivery_status: string; batch_id: number;
  delivery_id: number; delivery_attempts: number; delivery_in_flight: boolean; delivery_retryable: boolean; job_posting_id: number; history: { local_start: string; timezone: string; reason: string }[] };

function isCompleted(item: Schedule) { return item.status === "completed" || item.room_status === "ended"; }
function isClosed(item: Schedule) {
  return isCompleted(item) || item.status === "cancelled" || ["ending", "cancelled"].includes(item.room_status);
}
function canReschedule(item: Schedule) {
  return !isCompleted(item) && ["scheduled", "rescheduled"].includes(item.status)
    && ["scheduled", "waiting"].includes(item.room_status);
}
function canRetry(item: Schedule) { return !isClosed(item) && item.delivery_retryable && !item.delivery_in_flight; }
function interviewStatus(item: Schedule) {
  if (isCompleted(item)) return { label: "Interview completed", style: "bg-emerald-100 text-emerald-800" };
  if (item.status === "cancelled" || item.room_status === "cancelled") return { label: "Cancelled", style: "bg-slate-100 text-slate-600" };
  if (item.room_status === "ending") return { label: "Finishing interview", style: "bg-amber-50 text-amber-800" };
  if (["ready", "active"].includes(item.room_status)) return { label: "In progress", style: "bg-amber-50 text-amber-800" };
  if (item.room_status === "waiting") return { label: "Candidate waiting", style: "bg-blue-50 text-blue-700" };
  return { label: item.status === "rescheduled" ? "Rescheduled" : "Scheduled", style: "bg-blue-50 text-blue-700" };
}
function scheduleTime(item: Schedule) {
  return { date: formatDate(item.local_start, item.timezone), time: formatTime(item.local_start, item.timezone) };
}
const actionStyle = "inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border px-3 py-2 text-xs font-semibold transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600";
const secondaryStyle = actionStyle + " border-slate-200 bg-white text-slate-700 hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700 disabled:border-slate-200 disabled:bg-slate-50 disabled:text-slate-400";

export function InterviewsPage() {
  const { refreshVersion } = useSupervisor();
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [rescheduleId, setRescheduleId] = useState<number>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  async function refresh() { const result = await apiRequest<Schedule[]>("/interviews/schedules"); setSchedules(result); setRescheduleId((id) => result.some((item) => item.id === id && canReschedule(item)) ? id : undefined); }
  useEffect(() => { void refresh().catch((failure) => setError(failure instanceof Error ? failure.message : "Could not load interviews.")).finally(() => setLoading(false)); }, [refreshVersion]);
  const needsRefresh = schedules.some((item) => item.delivery_status === "pending" || item.delivery_in_flight
    || (!isCompleted(item) && (["scheduled", "rescheduled"].includes(item.status) || item.room_status === "ending")));
  async function retry(item: Schedule) {
    if (busy || !canRetry(item)) return;
    setBusy(true); setError(undefined);
    try { await apiRequest(`/interviews/deliveries/${item.delivery_id}/retry`, { method: "POST", body: JSON.stringify({ confirmed: true, expected_attempts: item.delivery_attempts }) }); await refresh(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "Could not retry notification."); }
    finally { setBusy(false); }
  }
  useEffect(() => {
    if (!needsRefresh) return;
    let active = true;
    let fetching = false;
    const timer = window.setInterval(() => { if (fetching) return; fetching = true; void refresh().catch((failure) => { if (active) setError(failure instanceof Error ? failure.message : "Could not refresh interviews."); }).finally(() => { fetching = false; }); }, 2500);
    return () => { active = false; window.clearInterval(timer); };
  }, [needsRefresh]);
  return (
    <section className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div><h1 className="text-3xl font-bold tracking-tight">Interviews</h1>
          <p className="mt-2 text-sm text-slate-600">Open an interview, review past sessions, or change a schedule.</p></div>
        <div className="flex flex-wrap gap-2">
          <Link to="/interviewer/reports" className={secondaryStyle}>View assessments</Link>
          <Link to="/interviewer/schedule-interviews" className={actionStyle + " border-blue-600 bg-blue-600 text-white hover:bg-blue-700"}>Schedule interviews</Link>
        </div>
      </header>
      <ErrorMessage message={error} />
      <section aria-label="Scheduled interviews" className="mt-6 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        {loading ? <p className="p-6" role="status">Loading interviews…</p> : !schedules.length ? (
          <p className="p-6 text-sm text-slate-500">No interview schedules yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table aria-label="Interviews" className="w-full text-left text-sm">
              <thead className="border-b border-slate-200 bg-slate-50/80 text-xs text-slate-500">
                <tr>{["Candidate / job", "Schedule", "Actions"].map((title) => <th key={title} scope="col" className="px-5 py-4 font-semibold">{title}</th>)}</tr>
              </thead>
              <tbody>{schedules.map((item) => {
                const status = interviewStatus(item);
                const time = scheduleTime(item);
                return (
                <tr key={item.id} className={`border-b border-slate-100 align-top last:border-0 ${isCompleted(item) ? "bg-emerald-50/30" : "hover:bg-slate-50/50"}`}>
                  <td className="min-w-44 px-5 py-5">
                    <p className="font-semibold text-slate-900">{item.candidate_name}</p>
                    <p className="mt-1 text-xs text-slate-600">{item.job_title}</p>
                    <p className="mt-1 text-xs text-slate-400">Interview #{item.id}</p>
                    <span className={`mt-3 inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${status.style}`}>
                      {isCompleted(item) ? <span aria-hidden="true" className="mr-1">✓</span> : null}{status.label}
                    </span>
                    {item.history.length ? (
                      <details className="mt-2">
                        <summary className="cursor-pointer text-xs text-blue-700">Previous schedules ({item.history.length})</summary>
                        {item.history.map((old, index) => { const time = scheduleTime({ ...item, ...old }); return <p key={index} className="mt-2 text-xs text-slate-600">{time.date} at {time.time} ({timeZoneLabel(old.timezone)}) {old.reason ? "— " + old.reason : ""}</p>; })}
                      </details>
                    ) : null}
                  </td>
                  <td className="min-w-44 px-5 py-5">
                    <p className="font-semibold text-slate-800">{time.date}</p>
                    <p className="mt-1 text-sm text-slate-600">{time.time}</p>
                    <p className="mt-2 text-xs text-slate-500">{timeZoneLabel(item.timezone)} · {item.duration_minutes} minutes</p>
                  </td>
                  <td className="w-72 px-5 py-5">
                    <div className="flex min-w-60 flex-wrap gap-2">
                      <Link className={actionStyle + " w-full " + (isClosed(item) ? "border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100" : "border-blue-600 bg-blue-600 text-white shadow-sm hover:bg-blue-700")}
                        to={`/interviews/${item.id}/console`}>
                        <svg aria-hidden="true" className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">{isClosed(item) ? <><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9Z"/><path d="M14 3v6h6M8 13h8M8 17h5"/></> : <><rect x="3" y="5" width="13" height="14" rx="3"/><path d="m16 10 5-3v10l-5-3"/></>}</svg>
                        {isClosed(item) ? "View interview details" : "Open interview console"}
                      </Link>
                      <Link className={secondaryStyle + " flex-1"} to={`/interviewer/reports?application=${item.application_id}`}>Assessment report</Link>
                      <button type="button" className={secondaryStyle} disabled={busy || !canReschedule(item)} aria-label={`Reschedule ${item.candidate_name}`}
                        title={canReschedule(item) ? "Change the interview time" : isClosed(item) ? "Closed interviews cannot be rescheduled" : "An interview that has started cannot be rescheduled"}
                        onClick={() => { if (canReschedule(item)) setRescheduleId(item.id); }}>Reschedule</button>
                      {item.delivery_status === "failed" ? <button type="button" className={secondaryStyle + " w-full"} disabled={busy || !canRetry(item)} onClick={() => void retry(item)}>Retry failed notification</button> : null}
                      {item.delivery_status === "uncertain" && !item.delivery_in_flight && !isClosed(item) ? <p className="text-xs text-amber-800">Email delivery is unconfirmed. Check with your email provider before resending.</p> : null}
                    </div>
                  </td>
                </tr>
              ); })}</tbody>
            </table>
          </div>
        )}
      </section>
      {rescheduleId !== undefined ? <div className="mt-4">
        <button type="button" className="text-sm font-medium text-slate-600" onClick={() => setRescheduleId(undefined)}>Close rescheduling</button>
        <InterviewSchedulingPanel key={rescheduleId} scheduleIds={[rescheduleId]} onUpdated={() => void refresh()} />
      </div> : null}
    </section>
  );
}
