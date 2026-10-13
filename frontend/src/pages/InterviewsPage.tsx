import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiRequest } from "../api/apiClient";
import { ErrorMessage } from "../components/common/ErrorMessage";
import { InterviewSchedulingPanel } from "../components/interviews/InterviewSchedulingPanel";
import { useSupervisor } from "../components/assistant/SupervisorProvider";

type Schedule = { id: number; candidate_name: string; job_title: string; stage: string; local_start: string; timezone: string;
  duration_minutes: number; status: string; sequence: number; delivery_status: string; batch_id: number;
  delivery_id: number; delivery_attempts: number; delivery_in_flight: boolean; delivery_retryable: boolean; job_posting_id: number; history: { local_start: string; timezone: string; reason: string }[] };

export function InterviewsPage() {
  const { refreshVersion } = useSupervisor();
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  async function refresh() { const result = await apiRequest<Schedule[]>("/interviews/schedules"); setSchedules(result); setSelectedIds((ids) => ids.filter((id) => result.some((item) => item.id === id))); }
  useEffect(() => { void refresh().catch((failure) => setError(failure instanceof Error ? failure.message : "Could not load interviews.")).finally(() => setLoading(false)); }, [refreshVersion]);
  const sameJob = new Set(schedules.filter((item) => selectedIds.includes(item.id)).map((item) => item.job_posting_id)).size <= 1;
  async function retry(item: Schedule) {
    if (busy) return;
    setBusy(true); setError(undefined);
    try { await apiRequest(`/interviews/deliveries/${item.delivery_id}/retry`, { method: "POST", body: JSON.stringify({ confirmed: true, expected_attempts: item.delivery_attempts }) }); await refresh(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "Could not retry notification."); }
    finally { setBusy(false); }
  }
  useEffect(() => {
    if (!schedules.some((item) => item.delivery_status === "pending" || item.delivery_in_flight)) return;
    let active = true;
    let fetching = false;
    const timer = window.setInterval(() => { if (fetching) return; fetching = true; void refresh().catch((failure) => { if (active) setError(failure instanceof Error ? failure.message : "Could not refresh interviews."); }).finally(() => { fetching = false; }); }, 2500);
    return () => { active = false; window.clearInterval(timer); };
  }, [schedules]);
  return (
    <section className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6">
      <h1 className="text-3xl font-bold">Interviews</h1>
      <p className="mt-2 text-sm text-slate-600">Schedules, delivery and rescheduling. Select ranked candidates on Assessments to schedule new interviews.</p>
      <ErrorMessage message={error} />
      <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        {loading ? <p>Loading interviews…</p> : !schedules.length ? (
          <p className="text-sm text-slate-500">No interview schedules yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-200 text-slate-500">
                <tr>{["Select", "Candidate / job", "Schedule", "Delivery"].map((title) => <th key={title} className="p-2">{title}</th>)}</tr>
              </thead>
              <tbody>{schedules.map((item) => (
                <tr key={item.id} className="border-b border-slate-100">
                  <td className="p-2">
                    <input type="checkbox" aria-label={`Reschedule ${item.candidate_name}`}
                      disabled={!["scheduled", "rescheduled"].includes(item.status)} checked={selectedIds.includes(item.id)}
                      onChange={() => setSelectedIds((ids) => ids.includes(item.id) ? ids.filter((id) => id !== item.id) : [...ids, item.id])} />
                  </td>
                  <td className="p-2">
                    <p className="font-semibold">{item.candidate_name}</p>
                    <Link className="mt-2 inline-block font-medium text-blue-700" to={`/interviews/${item.id}/console`}>Open interview console</Link>
                    <p className="mt-1 text-xs text-slate-500">{item.job_title} · {item.stage} · Interview #{item.id}</p>
                    {item.history.length ? (
                      <details className="mt-2">
                        <summary className="cursor-pointer text-xs text-blue-700">Previous schedules ({item.history.length})</summary>
                        {item.history.map((old, index) => <p key={index} className="mt-2 text-xs">{old.local_start} ({old.timezone}) {old.reason ? "— " + old.reason : ""}</p>)}
                      </details>
                    ) : null}
                  </td>
                  <td className="p-2">
                    <p>{item.local_start} ({item.timezone})</p>
                    <p className="mt-1 text-xs text-slate-500">{item.duration_minutes} minutes · {item.status} · Calendar sequence {item.sequence}</p>
                  </td>
                  <td className="p-2">
                    <p className="capitalize">{item.delivery_in_flight ? "Sending…" : item.delivery_status}</p>
                    {item.delivery_retryable ? <button className="mt-2 text-xs font-semibold text-blue-700" disabled={busy} onClick={() => void retry(item)}>Retry failed notification</button> : null}
                    {item.delivery_status === "uncertain" && !item.delivery_in_flight ? <p className="mt-2 text-xs text-amber-800">Check SMTP provider; do not automatically resend.</p> : null}
                  </td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </section>
      {!sameJob ? <p className="mt-3 text-sm text-amber-800">Select interviews for one job at a time.</p> : selectedIds.length ? <InterviewSchedulingPanel scheduleIds={selectedIds} onUpdated={() => void refresh()} /> : null}
    </section>
  );
}
