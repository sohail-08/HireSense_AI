import { useEffect, useRef, useState } from "react";
import { apiRequest } from "../../api/apiClient";
import { ErrorMessage } from "../common/ErrorMessage";
import { buildInterviewSchedule } from "./interviewSchedule";

type Recipient = { application_id: number; name: string; masked_email: string; rank?: number; score?: string;
  local_start?: string; local_end?: string; timezone?: string; duration_minutes?: number; subject?: string; body?: string;
  old_schedule?: { local_start: string; timezone: string }; calendar_uid?: string; sequence?: number };
type Selection = { selection_token: string; selected: Recipient[]; excluded: (Recipient & { reasons: string[] })[]; warnings: string[]; recipient_count: number };
type Invitation = { id?: number; status?: string; recipient_count: number; recipients: Recipient[]; confirmation_token?: string;
  sender: { from_email: string; reply_to: string }; sent?: number; failed?: number; uncertain?: number;
  deliveries?: { id: number; application_id: number; status: string; attempts: number; error_category: string | null; retryable: boolean; in_flight: boolean }[] };
const inputStyle = "mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm";
const buttonStyle = "rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:bg-slate-300";

export function InterviewSchedulingPanel({ jobId, rankingRunId, selectedIds = [], scheduleIds, onUpdated }:
  { jobId?: number; rankingRunId?: number; selectedIds?: number[]; scheduleIds?: number[]; onUpdated?: () => void }) {
  const rescheduling = Boolean(scheduleIds?.length);
  const [selectionMode, setSelectionMode] = useState("manual");
  const [topN, setTopN] = useState("5");
  const [threshold, setThreshold] = useState("70");
  const [operator, setOperator] = useState("gt");
  const [selection, setSelection] = useState<Selection>();
  const [preview, setPreview] = useState<Invitation>();
  const [batch, setBatch] = useState<Invitation>();
  const [fields, setFields] = useState<Record<string, string>>({ date: "", start_time: "", duration_minutes: "30",
    buffer_minutes: "0", instructions: "", subject_template: "", body_template: "", reason: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const confirmationKey = useRef("");
  const actionBusy = useRef(false);
  const selectedKey = selectedIds.join(",");
  const scheduleKey = scheduleIds?.join(",");
  useEffect(() => { setSelection(undefined); setPreview(undefined); setBatch(undefined); setError(undefined); }, [jobId, rankingRunId, selectedKey, scheduleKey]);
  useEffect(() => {
    if (!batch?.id || batch.status !== "sending") return;
    let active = true;
    let fetching = false;
    const timer = window.setInterval(() => {
      if (fetching) return;
      fetching = true;
      void apiRequest<Invitation>(`/interviews/batches/${batch.id}`).then((result) => {
        if (!active) return;
        setBatch(result);
        if (result.status === "completed") { window.clearInterval(timer); onUpdated?.(); }
      }).catch((failure) => { if (active) setError(failure instanceof Error ? failure.message : "Could not load deliveries."); }).finally(() => { fetching = false; });
    }, 1500);
    return () => { active = false; window.clearInterval(timer); };
  }, [batch?.id, batch?.status]);
  async function action(work: () => Promise<void>) {
    if (actionBusy.current) return;
    actionBusy.current = true; setBusy(true); setError(undefined);
    try { await work(); } catch (failure) { setError(failure instanceof Error ? failure.message : "Scheduling failed."); }
    finally { actionBusy.current = false; setBusy(false); }
  }
  function change(name: string, value: string) { setFields((current) => ({ ...current, [name]: value })); setPreview(undefined); }
  function selectionChanged() { setSelection(undefined); setPreview(undefined); setBatch(undefined); }
  async function previewSelection() {
    await action(async () => {
      setSelection(await apiRequest<Selection>("/interviews/selection/preview", { method: "POST", body: JSON.stringify({
        job_posting_id: jobId, ranking_run_id: rankingRunId, mode: selectionMode,
        top_n: selectionMode === "top_n" ? Number(topN) : null, threshold: selectionMode === "threshold" ? threshold : null,
        operator, application_ids: selectionMode === "manual" ? selectedIds : [],
      }) })); setPreview(undefined); setBatch(undefined);
    });
  }
  async function prepare() {
    await action(async () => {
      const data: Record<string, unknown> = buildInterviewSchedule(fields);
      if (rescheduling) data.schedule_ids = scheduleIds;
      else { delete data.reason; data.selection_token = selection?.selection_token; }
      setPreview(await apiRequest<Invitation>(rescheduling ? "/interviews/reschedule/preview" : "/interviews/invitations/prepare", { method: "POST", body: JSON.stringify(data) }));
      confirmationKey.current = crypto.randomUUID(); setBatch(undefined);
    });
  }
  async function confirm() {
    if (!preview?.confirmation_token) return;
    await action(async () => {
      setBatch(await apiRequest<Invitation>(rescheduling ? "/interviews/reschedule/confirm" : `/interviews/batches/${preview.id}/confirm`, {
        method: "POST", body: JSON.stringify({ confirmed: true, confirmation_token: preview.confirmation_token, idempotency_key: confirmationKey.current }),
      })); setPreview(undefined); onUpdated?.();
    });
  }
  async function retry(id: number, attempts: number) { await action(async () => setBatch(await apiRequest<Invitation>(`/interviews/deliveries/${id}/retry`, {
    method: "POST", body: JSON.stringify({ confirmed: true, expected_attempts: attempts }),
  }))); }
  return <section className="mt-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
    <h2 className="text-lg font-semibold">{rescheduling ? "Reschedule selected interviews" : "Schedule interviews"}</h2>
    <p className="mt-1 text-sm text-slate-500">Preview recipients, times and email before confirming. No meeting platform is connected.</p><ErrorMessage message={error} />
    <fieldset disabled={busy || batch?.status === "sending"} className="min-w-0">
      {!rescheduling ? <>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <label className="text-sm">Selection method<select className={inputStyle} value={selectionMode} onChange={(event) => { setSelectionMode(event.target.value); selectionChanged(); }}><option value="manual">Checked candidates ({selectedIds.length})</option><option value="top_n">Top N ranked candidates</option><option value="threshold">Score threshold / filter</option></select></label>
          {selectionMode === "top_n" ? <label className="text-sm">Number of candidates<input type="number" min="1" max="100" className={inputStyle} value={topN} onChange={(event) => { setTopN(event.target.value); selectionChanged(); }} /></label> : null}
          {selectionMode === "threshold" ? <label className="text-sm">Score threshold (%)<div className="flex gap-2"><select className={inputStyle} value={operator} onChange={(event) => { setOperator(event.target.value); selectionChanged(); }}><option value="gt">Greater than</option><option value="gte">At least</option></select><input type="number" min="0" max="100" step="any" value={threshold} className={inputStyle} onChange={(event) => { setThreshold(event.target.value); selectionChanged(); }} /></div></label> : null}
        </div>
        <button type="button" className={buttonStyle + " mt-3"} disabled={!rankingRunId || (selectionMode === "manual" && !selectedIds.length)} onClick={() => void previewSelection()}>Preview candidate selection</button>
        {selection ? <div className="mt-4 rounded-xl bg-slate-50 p-4 text-sm"><p className="font-semibold">{selection.recipient_count} eligible recipient(s)</p><ul className="mt-2 space-y-1">{selection.selected.map((item) => <li key={item.application_id}>{item.name} · rank {item.rank} · {item.score}% · {item.masked_email}</li>)}</ul>{selection.warnings.map((warning) => <p key={warning} className="mt-2 text-amber-800">{warning}</p>)}{selection.excluded.length ? <details className="mt-3"><summary className="cursor-pointer font-medium">Excluded candidates ({selection.excluded.length})</summary><ul className="mt-2 space-y-1">{selection.excluded.map((item) => <li key={item.application_id}>{item.name}: {item.reasons.join("; ")}</li>)}</ul></details> : null}</div> : null}
      </> : <p className="mt-3 text-sm">{scheduleIds?.length} interview(s) selected.</p>}
      {rescheduling || selection?.recipient_count ? <>
        <p className="mt-5 text-sm text-slate-500">Sequential individual slots · Times are in Asia/Dhaka.</p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">{[["date", "Date", "date"], ["start_time", "Start time", "time"], ["duration_minutes", "Duration (minutes)", "number"], ["buffer_minutes", "Buffer (minutes)", "number"]].map(([key, label, type]) => <label key={key} className="text-sm">{label}<input type={type} className={inputStyle} value={fields[key]} onChange={(event) => change(key, event.target.value)} /></label>)}
        </div>
        <label className="mt-4 block text-sm">Additional instructions<textarea className={inputStyle} value={fields.instructions} onChange={(event) => change("instructions", event.target.value)} /></label>
        {rescheduling ? <label className="mt-3 block text-sm">Reason for rescheduling<input className={inputStyle} value={fields.reason} onChange={(event) => change("reason", event.target.value)} /></label> : null}
        <details className="mt-3 rounded-xl border border-slate-200 p-3"><summary className="cursor-pointer text-sm font-medium">Edit invitation email</summary><p className="mt-2 text-xs text-slate-500">Blank means defaults. Fields: {"{candidate_name}, {job_title}, {company_name}, {local_date}, {local_start_time}, {timezone}, {duration}, {stage}, {contact_email}, {instructions}"}.</p><label className="mt-3 block text-sm">Subject template<input className={inputStyle} value={fields.subject_template} onChange={(event) => change("subject_template", event.target.value)} /></label><label className="mt-3 block text-sm">Body template<textarea rows={7} className={inputStyle} value={fields.body_template} onChange={(event) => change("body_template", event.target.value)} /></label></details>
        <button type="button" className={buttonStyle + " mt-4"} onClick={() => void prepare()} disabled={!fields.date || !fields.start_time}>Preview schedule & email</button>
      </> : null}
      {preview ? <div className="mt-5 rounded-xl border border-blue-200 p-4"><h3 className="font-semibold">Exact preview — {preview.recipient_count} recipients</h3><p className="mt-1 text-xs text-slate-500">From: {preview.sender.from_email} · Reply-to: {preview.sender.reply_to}</p><div className="mt-3 space-y-3">{preview.recipients.map((item) => <details key={item.application_id} className="rounded-lg bg-slate-50 p-3" open={preview.recipients.length === 1}><summary className="cursor-pointer text-sm font-semibold">{item.name} · {item.masked_email} · {item.local_start} ({item.timezone})</summary>{item.old_schedule ? <p className="mt-2 text-sm">Previous: {item.old_schedule.local_start} ({item.old_schedule.timezone})</p> : null}<p className="mt-2 text-sm">New slot: {item.local_start} → {item.local_end} · {item.duration_minutes} minutes</p><p className="mt-2 text-sm font-medium">Subject: {item.subject}</p><p className="mt-2 whitespace-pre-wrap text-sm leading-6">{item.body}</p><p className="mt-3 break-all text-xs text-slate-500">Attachment: interview.ics · METHOD:REQUEST · UTC times · UID: {item.calendar_uid} · SEQUENCE:{item.sequence}</p></details>)}</div><button type="button" className={buttonStyle + " mt-4"} onClick={() => void confirm()}>Confirm & send {preview.recipient_count} invitation(s)</button></div> : null}
    </fieldset>
    {batch ? <div className="mt-4 rounded-xl bg-slate-50 p-4 text-sm" role="status"><p className="font-semibold">{batch.status === "sending" ? "Sending invitations…" : "Invitation results"}</p><p className="mt-1">{batch.sent ?? 0} sent · {batch.failed ?? 0} failed · {batch.uncertain ?? 0} uncertain</p><ul className="mt-3 space-y-2">{batch.deliveries?.map((item) => <li key={item.id}>{batch.recipients.find((recipient) => recipient.application_id === item.application_id)?.name ?? `Application #${item.application_id}`}: {item.in_flight ? "sending" : item.status}{item.error_category ? " · " + item.error_category.replaceAll("_", " ") : ""}{item.retryable ? <button type="button" disabled={busy} onClick={() => void retry(item.id, item.attempts)} className="ml-3 font-semibold text-blue-700">Retry failed delivery</button> : null}</li>)}</ul>{batch.status === "completed" && batch.uncertain ? <p className="mt-3 text-amber-800">Uncertain delivery is not automatically retried. Check your SMTP provider before another action.</p> : null}</div> : null}
  </section>;
}
