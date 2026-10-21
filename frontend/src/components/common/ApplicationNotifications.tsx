import { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { apiRequest } from "../../api/apiClient";
import { APPLICATIONS_CHANGED_EVENT } from "./applicationNotificationEvents";
import { formatDateTime } from "../../utils/dateTime";

type NotificationSummary = {
  status: "ready" | "not_configured" | "unavailable";
  pending_count: number | null; unmatched_count: number | null;
  jobs: { job_posting_id: number; job_title: string; count: number }[];
  checked_at: string | null; message: string | null;
};

export function ApplicationNotifications() {
  const [summary, setSummary] = useState<NotificationSummary>();
  const [open, setOpen] = useState(false);
  const [checking, setChecking] = useState(false);
  const [retry, setRetry] = useState(0);
  const container = useRef<HTMLDivElement>(null);
  const panelId = useId();
  useEffect(() => {
    let active = true, busy = false, refreshAgain = false;
    const controller = new AbortController();
    async function check() {
      if (document.visibilityState === "hidden") return;
      if (busy) { refreshAgain = true; return; }
      busy = true; setChecking(true);
      try {
        const result = await apiRequest<NotificationSummary>("/candidates/notifications", { signal: controller.signal });
        if (active) setSummary(result);
      } catch {
        if (active) setSummary({ status: "unavailable", pending_count: null, unmatched_count: null,
          jobs: [], checked_at: null, message: "Could not check new applications. Check your connection and try again." });
      } finally {
        busy = false;
        if (active) {
          setChecking(false);
          if (refreshAgain) { refreshAgain = false; void check(); }
        }
      }
    }
    const refresh = () => { void check(); };
    refresh();
    const timer = window.setInterval(refresh, 60000);
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    window.addEventListener(APPLICATIONS_CHANGED_EVENT, refresh);
    return () => {
      active = false; controller.abort(); window.clearInterval(timer);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
      window.removeEventListener(APPLICATIONS_CHANGED_EVENT, refresh);
    };
  }, [retry]);
  useEffect(() => {
    if (!open) return;
    function outside(event: PointerEvent) {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    }
    function escape(event: KeyboardEvent) { if (event.key === "Escape") setOpen(false); }
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", outside); document.removeEventListener("keydown", escape); };
  }, [open]);
  const ready = summary?.status === "ready";
  const total = ready ? (summary.pending_count ?? 0) + (summary.unmatched_count ?? 0) : 0;
  const label = ready ? `Application notifications: ${total} responses waiting` : "Application notifications";
  return <div ref={container} className="relative shrink-0">
    <button type="button" aria-label={label} aria-expanded={open} aria-controls={panelId}
      onClick={() => setOpen((value) => !value)}
      className="relative flex h-10 w-10 items-center justify-center rounded-xl border border-slate-200 text-slate-600 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-blue-600">
      <svg aria-hidden="true" width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" strokeLinecap="round" strokeLinejoin="round" /></svg>
      {total > 0 ? <span aria-hidden="true" className="absolute -right-2 -top-2 min-w-5 rounded-full bg-red-600 px-1 text-center text-[10px] font-bold leading-5 text-white">{total > 99 ? "99+" : total}</span>
        : summary && !ready ? <span aria-hidden="true" className="absolute -right-1 -top-1 rounded-full bg-amber-500 px-1.5 text-xs font-bold text-white">!</span> : null}
    </button>
    {open ? <section id={panelId} aria-label="Application notifications" className="fixed left-3 right-3 top-20 z-40 max-h-[75vh] overflow-y-auto rounded-2xl border border-slate-200 bg-white p-5 text-left shadow-xl sm:absolute sm:left-auto sm:right-0 sm:top-12 sm:w-96">
      <div className="flex items-center justify-between gap-3"><h2 className="font-bold text-slate-900">New applications</h2><button type="button" aria-label="Close notifications" className="rounded px-2 py-1 text-slate-500 hover:bg-slate-100" onClick={() => setOpen(false)}>×</button></div>
      <p className="mt-2 text-xs leading-5 text-slate-500">Checks about every minute while HireSense is open. Nothing is imported automatically.</p>
      {!summary ? <p role="status" className="mt-4 text-sm text-slate-600">Checking Google Form responses…</p> : ready ? <div aria-live="polite">
        <p className="mt-4 text-sm font-semibold text-slate-800">{summary.pending_count === 0 ? (total ? "No applications are ready to sync yet." : "No new applications waiting to sync.") : `${summary.pending_count} new application${summary.pending_count === 1 ? " is" : "s are"} ready to sync.`}</p>
        {summary.jobs.length ? <ul className="mt-3 space-y-2">{summary.jobs.map((job) => <li key={job.job_posting_id} className="flex items-center justify-between gap-3 rounded-xl bg-blue-50 px-3 py-2 text-sm"><span className="min-w-0 break-words text-slate-800">{job.job_title}<span className="block text-xs text-slate-500">Posting #{job.job_posting_id}</span></span><span className="shrink-0 font-bold text-blue-700">{job.count}</span></li>)}</ul> : null}
        {(summary.unmatched_count ?? 0) > 0 ? <p className="mt-3 rounded-xl bg-amber-50 p-3 text-sm text-amber-900">{summary.unmatched_count} response{summary.unmatched_count === 1 ? " needs" : "s need"} a valid, unambiguous job selection before syncing. Correct the Job Posting answer in the response sheet.</p> : null}
        <p className="mt-3 text-xs text-slate-500">Synced and deliberately deleted applications are not counted. Opening this panel does not clear pending responses.</p>
      </div> : <p role="status" className="mt-4 rounded-xl bg-amber-50 p-3 text-sm text-amber-900">{summary.message}</p>}
      {summary?.checked_at ? <p className="mt-3 text-xs text-slate-400">Last checked: {formatDateTime(summary.checked_at)}</p> : null}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4">
        <button type="button" disabled={checking} className="text-sm font-medium text-blue-700 disabled:text-slate-400" onClick={() => setRetry((value) => value + 1)}>{checking ? "Checking…" : "Refresh count"}</button>
        <Link to="/interviewer/candidates" onClick={() => setOpen(false)} className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white">Review and sync</Link>
      </div>
    </section> : null}
  </div>;
}
