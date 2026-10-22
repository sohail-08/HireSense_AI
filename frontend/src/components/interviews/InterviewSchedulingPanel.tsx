import { useEffect, useRef, useState } from "react";
import { apiRequest } from "../../api/apiClient";
import { ErrorMessage } from "../common/ErrorMessage";
import { StyledSelect } from "../common/StyledSelect";
import { DateTimePicker } from "../common/DateTimePicker";
import { PreviewModal } from "../common/PreviewModal";
import { buildInterviewSchedule } from "./interviewSchedule";
import { formatDateTime, formatTimeRange } from "../../utils/dateTime";

type Recipient = { application_id: number; name: string; email?: string | null; masked_email?: string | null; rank?: number; score?: string;
  local_start?: string; local_end?: string; timezone?: string; duration_minutes?: number; subject?: string; body?: string;
  old_schedule?: { local_start: string; timezone: string }; calendar_uid?: string; sequence?: number };
type Selection = { selection_token: string; selected: Recipient[]; excluded: (Recipient & { reasons: string[] })[]; warnings: string[]; recipient_count: number };
type Invitation = { id?: number; status?: string; recipient_count: number; recipients: Recipient[]; confirmation_token?: string;
  sender: { from_email: string; reply_to: string }; sent?: number; failed?: number; uncertain?: number;
  deliveries?: { id: number; application_id: number; status: string; attempts: number; error_category: string | null; retryable: boolean; in_flight: boolean }[] };
const inputStyle = "mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm";
const buttonStyle = "rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:bg-slate-300";

export function InterviewSchedulingPanel({ jobId, rankingRunId, selectedIds = [], scheduleIds, onUpdated, onBusyChange }:
  { jobId?: number; rankingRunId?: number; selectedIds?: number[]; scheduleIds?: number[]; onUpdated?: () => void; onBusyChange?: (busy: boolean) => void }) {
  const rescheduling = Boolean(scheduleIds?.length);
  const [selectionMode, setSelectionMode] = useState("manual");
  const [topN, setTopN] = useState("5");
  const [threshold, setThreshold] = useState("70");
  const [operator, setOperator] = useState("gt");
  const [selection, setSelection] = useState<Selection>();
  const [preview, setPreview] = useState<Invitation>();
  const [modal, setModal] = useState<"selection" | "invitation">();
  const [batch, setBatch] = useState<Invitation>();
  const [fields, setFields] = useState<Record<string, string>>({ date: "", start_time: "", duration_minutes: "30",
    buffer_minutes: "0", instructions: "", subject_template: "", body_template: "", reason: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const confirmationKey = useRef("");
  const actionBusy = useRef(false);
  const selectedKey = selectedIds.join(",");
  const scheduleKey = scheduleIds?.join(",");
  useEffect(() => {
    onBusyChange?.(busy || batch?.status === "sending");
    return () => onBusyChange?.(false);
  }, [busy, batch?.status, onBusyChange]);
  useEffect(() => { setSelection(undefined); setPreview(undefined); setBatch(undefined); setError(undefined); setModal(undefined); }, [jobId, rankingRunId, selectedKey, scheduleKey]);
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
  function change(name: string, value: string) { setFields((current) => ({ ...current, [name]: value })); setPreview(undefined); setModal(undefined); }
  function selectionChanged() { setSelection(undefined); setPreview(undefined); setBatch(undefined); setModal(undefined); }
  async function previewSelection() {
    await action(async () => {
      setSelection(await apiRequest<Selection>("/interviews/selection/preview", { method: "POST", body: JSON.stringify({
        job_posting_id: jobId, ranking_run_id: rankingRunId, mode: selectionMode,
        top_n: selectionMode === "top_n" ? Number(topN) : null, threshold: selectionMode === "threshold" ? threshold : null,
        operator, application_ids: selectionMode === "manual" ? selectedIds : [],
      }) })); setPreview(undefined); setBatch(undefined); setModal("selection");
    });
  }
  async function prepare() {
    await action(async () => {
      const data: Record<string, unknown> = buildInterviewSchedule(fields);
      if (rescheduling) data.schedule_ids = scheduleIds;
      else { delete data.reason; data.selection_token = selection?.selection_token; }
      setPreview(await apiRequest<Invitation>(rescheduling ? "/interviews/reschedule/preview" : "/interviews/invitations/prepare", { method: "POST", body: JSON.stringify(data) }));
      confirmationKey.current = crypto.randomUUID(); setBatch(undefined); setModal("invitation");
    });
  }
  async function confirm() {
    if (!preview?.confirmation_token) return;
    await action(async () => {
      setBatch(await apiRequest<Invitation>(rescheduling ? "/interviews/reschedule/confirm" : `/interviews/batches/${preview.id}/confirm`, {
        method: "POST", body: JSON.stringify({ confirmed: true, confirmation_token: preview.confirmation_token, idempotency_key: confirmationKey.current }),
      })); setPreview(undefined); setModal(undefined); onUpdated?.();
    });
  }
  async function retry(id: number, attempts: number) { await action(async () => setBatch(await apiRequest<Invitation>(`/interviews/deliveries/${id}/retry`, {
    method: "POST", body: JSON.stringify({ confirmed: true, expected_attempts: attempts }),
  }))); }
  return <section className="mt-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
    <h2 className="text-lg font-semibold">{rescheduling ? (scheduleIds?.length === 1 ? "Reschedule interview" : "Reschedule selected interviews") : "Schedule interviews"}</h2>
    <p className="mt-1 text-sm text-slate-500">Preview recipients, times and email before confirming.</p><ErrorMessage message={error} />
    <fieldset disabled={busy || batch?.status === "sending"} className="min-w-0">
      {!rescheduling ? <>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <label className="text-sm">Which candidates?<StyledSelect label="Which candidates?" className="mt-1" value={selectionMode} disabled={busy || batch?.status === "sending"}
            options={[{ value: "manual", label: `Candidates I checked (${selectedIds.length})` }, { value: "top_n", label: "Highest-ranked candidates" }, { value: "threshold", label: "Candidates above a score" }]}
            onChange={value => { setSelectionMode(value); selectionChanged(); }} /></label>
          {selectionMode === "top_n" ? <label className="text-sm">Number of candidates<input type="number" min="1" max="100" className={inputStyle} value={topN} onChange={(event) => { setTopN(event.target.value); selectionChanged(); }} /></label> : null}
          {selectionMode === "threshold" ? <div className="text-sm"><label htmlFor="interview-score-threshold">Candidate score (%)</label><div className="flex gap-2"><StyledSelect label="Score comparison" className="mt-1" value={operator} disabled={busy || batch?.status === "sending"}
            options={[{ value: "gt", label: "Above" }, { value: "gte", label: "At least" }]} onChange={value => { setOperator(value); selectionChanged(); }} />
            <input id="interview-score-threshold" type="number" min="0" max="100" step="any" value={threshold} className={inputStyle} onChange={(event) => { setThreshold(event.target.value); selectionChanged(); }} /></div></div> : null}
        </div>
        <button type="button" className={buttonStyle + " mt-3"} disabled={!rankingRunId || (selectionMode === "manual" && !selectedIds.length)} onClick={() => void previewSelection()}>Preview candidate selection</button>
        {selection ? <p className="mt-3 text-sm text-slate-500">{selection.recipient_count} candidate(s) selected. <button type="button" className="font-semibold text-blue-700 hover:underline" onClick={() => setModal("selection")}>Review selection</button></p> : null}
      </> : <p className="mt-3 text-sm">{scheduleIds?.length} interview(s) selected.</p>}
      {rescheduling || selection?.recipient_count ? <>
        <p className="mt-5 text-sm text-slate-500">One candidate per time slot · All times are in Dhaka time.</p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <DateTimePicker label="Date" kind="date" value={fields.date} disabled={busy || batch?.status === "sending"} onChange={value => change("date", value)} />
          <DateTimePicker label="Start time" kind="time" value={fields.start_time} disabled={busy || batch?.status === "sending"} onChange={value => change("start_time", value)} />
          {[["duration_minutes", "Duration (minutes)"], ["buffer_minutes", "Buffer (minutes)"]].map(([key, label]) => <label key={key} className="text-sm">{label}<input type="number" className={inputStyle} value={fields[key]} onChange={(event) => change(key, event.target.value)} /></label>)}
        </div>
        <label className="mt-4 block text-sm">Additional instructions<textarea className={inputStyle} value={fields.instructions} onChange={(event) => change("instructions", event.target.value)} /></label>
        {rescheduling ? <label className="mt-3 block text-sm">Reason for rescheduling<input className={inputStyle} value={fields.reason} onChange={(event) => change("reason", event.target.value)} /></label> : null}
        <button type="button" className={buttonStyle + " mt-4"} onClick={() => void prepare()} disabled={!fields.date || !fields.start_time}>Preview schedule & email</button>
      </> : null}
      {preview ? <button type="button" className="ml-3 mt-4 text-sm font-semibold text-blue-700 hover:underline" onClick={() => setModal("invitation")}>Review schedule & email</button> : null}
    </fieldset>
    {modal === "selection" && selection ? <PreviewModal title="Candidate selection" onClose={() => setModal(undefined)}>
      <p className="text-sm font-semibold">{selection.recipient_count} eligible recipient(s)</p>
      <ul className="mt-4 space-y-3">{selection.selected.map(item => <li key={item.application_id} className="rounded-xl border border-slate-200 p-4">
        <p className="font-semibold">{item.name}</p><p className="mt-1 break-all text-sm text-slate-600">{item.email || item.masked_email || "No email address"}</p>
        <p className="mt-2 text-sm text-slate-500">Rank {item.rank} · Score {item.score}%</p>
      </li>)}</ul>
      {selection.warnings.map(warning => <p key={warning} className="mt-3 rounded-xl bg-amber-50 p-3 text-sm text-amber-800">{warning}</p>)}
      {selection.excluded.length ? <details className="mt-4 text-sm"><summary className="font-medium">Excluded candidates ({selection.excluded.length})</summary><ul className="mt-2 space-y-2">{selection.excluded.map(item => <li key={item.application_id}>{item.name}: {item.reasons.join("; ")}</li>)}</ul></details> : null}
      <div className="mt-5 flex justify-end"><button type="button" className={buttonStyle} onClick={() => setModal(undefined)}>{selection.recipient_count ? "Continue to schedule" : "Back to selection"}</button></div>
    </PreviewModal> : null}
    {modal === "invitation" && preview ? <PreviewModal title="Schedule & email preview" onClose={() => setModal(undefined)} busy={busy}>
      <ErrorMessage message={error} />
      <p className="text-sm font-semibold">{preview.recipient_count} invitation(s) · Nothing has been sent yet</p>
      <p className="mt-2 break-words text-xs text-slate-500">From: {preview.sender.from_email} · Reply-to: {preview.sender.reply_to}</p>
      <div className="mt-4 space-y-3">{preview.recipients.map(item => <details key={item.application_id} className="rounded-xl border border-slate-200 bg-slate-50 p-4" open={preview.recipients.length === 1}>
        <summary className="text-sm font-semibold"><span>{item.name}</span><span className="mt-1 block break-all font-normal text-slate-600">{item.email || item.masked_email || "No email address"}</span></summary>
        {item.old_schedule ? <p className="mt-3 text-sm text-slate-500">Previous: {formatDateTime(item.old_schedule.local_start, item.old_schedule.timezone)}</p> : null}
        <p className="mt-3 text-sm">{formatTimeRange(item.local_start, item.local_end, item.timezone)} · {item.duration_minutes} minutes</p>
        <p className="mt-3 text-sm font-semibold">Subject: {item.subject}</p><p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6">{item.body}</p>
        <p className="mt-3 text-xs text-slate-500">Calendar attachment: interview.ics</p>
      </details>)}</div>
      <div className="mt-5 flex flex-wrap justify-end gap-3"><button type="button" disabled={busy} className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold hover:bg-slate-50 disabled:opacity-40" onClick={() => setModal(undefined)}>Back to schedule</button>
        <button type="button" disabled={busy} className={buttonStyle} onClick={() => void confirm()}>{busy ? "Confirming…" : `Confirm & send ${preview.recipient_count} invitation(s)`}</button></div>
    </PreviewModal> : null}
    {batch ? <div className="mt-4 rounded-xl bg-slate-50 p-4 text-sm" role="status"><p className="font-semibold">{batch.status === "sending" ? "Sending invitations…" : "Invitation results"}</p><p className="mt-1">{batch.sent ?? 0} sent · {batch.failed ?? 0} failed · {batch.uncertain ?? 0} uncertain</p><ul className="mt-3 space-y-2">{batch.deliveries?.map((item) => <li key={item.id}>{batch.recipients.find((recipient) => recipient.application_id === item.application_id)?.name ?? `Application #${item.application_id}`}: {item.in_flight ? "sending" : item.status}{item.error_category ? " · " + item.error_category.replaceAll("_", " ") : ""}{item.retryable ? <button type="button" disabled={busy} onClick={() => void retry(item.id, item.attempts)} className="ml-3 font-semibold text-blue-700">Retry failed delivery</button> : null}</li>)}</ul>{batch.status === "completed" && batch.uncertain ? <p className="mt-3 text-amber-800">Uncertain delivery is not automatically retried. Check your SMTP provider before another action.</p> : null}</div> : null}
  </section>;
}
