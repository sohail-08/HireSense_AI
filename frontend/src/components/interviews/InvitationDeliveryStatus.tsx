type Delivery = { id: number; application_id: number; status: string; attempts: number; error_category: string | null; retryable: boolean; in_flight: boolean };
type Recipient = { application_id: number; name: string; email?: string | null; masked_email?: string | null };
export type InvitationDeliveryBatch = {
  status?: string; recipient_count: number; recipients: Recipient[]; deliveries?: Delivery[];
  sent?: number; failed?: number; uncertain?: number;
};

type State = "sending" | "pending" | "sent" | "failed" | "uncertain" | "unknown";
const labels: Record<State, string> = { sending: "Sending", pending: "Queued", sent: "Sent", failed: "Failed", uncertain: "Unconfirmed", unknown: "Checking status" };
const badgeStyles: Record<State, string> = {
  sending: "border-blue-100 bg-blue-50 text-blue-700", pending: "border-slate-200 bg-slate-50 text-slate-600",
  sent: "border-emerald-100 bg-emerald-50 text-emerald-700", failed: "border-rose-100 bg-rose-50 text-rose-700",
  uncertain: "border-amber-100 bg-amber-50 text-amber-800", unknown: "border-slate-200 bg-slate-50 text-slate-600",
};

function stateOf(item: Delivery): State {
  // The backend claims an SMTP attempt as uncertain while it is in flight.
  // It is still sending, not an unresolved outcome, until that attempt finishes.
  if (item.in_flight) return "sending";
  return ["pending", "sent", "failed", "uncertain"].includes(item.status) ? item.status as State : "unknown";
}

function StatusIcon({ state, className = "h-3.5 w-3.5" }: { state: State; className?: string }) {
  return <svg aria-hidden="true" className={`${className} shrink-0 ${state === "sending" ? "animate-spin motion-reduce:animate-none" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    {state === "sending" ? <><circle className="opacity-20" cx="12" cy="12" r="8" /><path d="M12 4a8 8 0 0 1 8 8" /></> : state === "sent" ? <path d="m5 12 4 4L19 6" /> : state === "pending" || state === "unknown" ? <><circle cx="12" cy="12" r="8" /><path d="M12 8v4l3 2" /></> : <><path d="m12 3 10 18H2Z" /><path d="M12 9v4m0 4h.01" /></>}
  </svg>;
}

function failureMessage(category: string | null) {
  const messages: Record<string, string> = {
    smtp_not_configured: "Email settings need to be configured.", smtp_authentication: "Check the email account’s sign-in settings.",
    recipient_became_ineligible: "This candidate is no longer eligible for the invitation.",
    interview_start_has_passed: "The scheduled start time has passed.", superseded_calendar_sequence: "A newer schedule has replaced this invitation.",
    candidate_join_link_changed: "The candidate link has changed. Review the latest interview details.",
  };
  return messages[category ?? ""] ?? "The invitation could not be sent. Check your email settings or delivery details.";
}

export function InvitationDeliveryStatus({ batch, busy, onRetry }: {
  batch: InvitationDeliveryBatch; busy: boolean; onRetry: (id: number, attempts: number) => void;
}) {
  const deliveries = batch.deliveries ?? [];
  const counts = { sent: 0, failed: 0, uncertain: 0, sending: 0 };
  if (deliveries.length) {
    for (const item of deliveries) {
      const state = stateOf(item);
      if (state in counts) counts[state as keyof typeof counts]++;
    }
  } else {
    counts.sent = batch.sent ?? 0; counts.failed = batch.failed ?? 0; counts.uncertain = batch.uncertain ?? 0;
  }
  const total = Math.max(batch.recipient_count, deliveries.length, counts.sent + counts.failed + counts.uncertain + counts.sending);
  const processed = counts.sent + counts.failed + counts.uncertain;
  const remaining = Math.max(0, total - processed);
  const running = batch.status === "sending" || deliveries.some(item => item.in_flight || item.status === "pending");
  const needsAttention = counts.failed + counts.uncertain > 0;
  const successful = !running && total > 0 && counts.sent === total;
  const overall: State = running ? "sending" : needsAttention ? "uncertain" : successful ? "sent" : "unknown";
  const metrics = [
    { label: "Sent", value: counts.sent, color: "border-emerald-100 bg-emerald-50/60 text-emerald-700" },
    { label: "Pending", value: remaining, color: "border-blue-100 bg-blue-50/60 text-blue-700" },
    { label: "Failed", value: counts.failed, color: "border-rose-100 bg-rose-50/60 text-rose-700" },
    { label: "Unconfirmed", value: counts.uncertain, color: "border-amber-100 bg-amber-50/60 text-amber-800" },
  ];
  return <section id="invitation-delivery" aria-label="Invitation delivery progress" className="workflow-section mt-5 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
    <header className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 bg-gradient-to-br from-blue-50/80 via-white to-white p-4 sm:p-5">
      <div className="flex min-w-0 items-center gap-3"><span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-blue-100 bg-white text-blue-600 shadow-sm"><svg aria-hidden="true" className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="5" width="18" height="14" rx="3" /><path d="m4 7 8 6 8-6" /></svg></span>
        <div className="min-w-0"><h3 className="text-base font-semibold tracking-tight text-slate-900">{running ? "Sending invitations…" : "Invitation results"}</h3><p className="mt-1 text-xs leading-5 text-slate-500">{running ? "Interview emails are on their way. Progress updates automatically." : needsAttention ? "Some invitations need your attention below." : successful ? "Your interview invitations have been sent." : "Checking the saved delivery results."}</p></div>
      </div>
      <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${badgeStyles[overall]}`}><StatusIcon state={overall} />{running ? "In progress" : needsAttention ? "Review needed" : successful ? "Completed" : "Checking status"}</span>
    </header>
    <div className="p-4 sm:p-5">
      <p role="status" aria-live="polite" aria-atomic="true" className="sr-only">{counts.sent} sent, {remaining} pending, {counts.failed} failed, {counts.uncertain} unconfirmed.</p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">{metrics.map(metric => <div aria-label={`${metric.label} invitations`} key={metric.label} className={`rounded-xl border px-3 py-2.5 ${metric.value ? metric.color : "border-slate-100 bg-slate-50/60 text-slate-400"}`}><p className="text-xl font-semibold tabular-nums leading-7">{metric.value}</p><p className={`mt-0.5 text-xs font-medium ${metric.value ? "" : "text-slate-500"}`}>{metric.label}</p></div>)}</div>
      {total > 0 ? <div className="mt-4"><div className="mb-2 flex items-center justify-between gap-3 text-xs"><span className="font-medium text-slate-600">Delivery progress</span><span className="tabular-nums text-slate-500">{processed} of {total} processed</span></div>
        <div role="progressbar" aria-label="Invitation sending progress" aria-valuemin={0} aria-valuemax={total} aria-valuenow={processed} aria-valuetext={`${processed} of ${total} processed`} className="flex h-1.5 overflow-hidden rounded-full bg-slate-100">
          {[{ value: counts.sent, color: "bg-emerald-500" }, { value: counts.failed, color: "bg-rose-400" }, { value: counts.uncertain, color: "bg-amber-400" }].map(segment => <span key={segment.color} className={`${segment.color} transition-[width] duration-500 motion-reduce:transition-none`} style={{ width: `${segment.value / total * 100}%` }} />)}
        </div>
      </div> : null}
      {deliveries.length ? <ul aria-label="Candidate invitation deliveries" className="mt-4 divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-100">{deliveries.map(item => {
        const recipient = batch.recipients.find(candidate => candidate.application_id === item.application_id);
        const name = recipient?.name || "Candidate invitation";
        const email = recipient?.email || recipient?.masked_email;
        const state = stateOf(item);
        const initials = name.trim().split(/\s+/).slice(0, 2).map(part => part[0]).join("").toUpperCase();
        return <li key={item.id} className="flex flex-wrap items-center justify-between gap-3 px-3 py-3 sm:px-4">
          <div className="flex min-w-0 flex-1 basis-44 items-center gap-3"><span aria-hidden="true" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-blue-50 text-xs font-semibold text-blue-700">{initials}</span><div className="min-w-0"><p className="break-words text-sm font-semibold text-slate-800">{name}</p>{email ? <p className="mt-0.5 break-all text-xs text-slate-500">{email}</p> : null}{state === "failed" ? <p className="mt-1 text-xs leading-5 text-rose-700">{failureMessage(item.error_category)}</p> : state === "uncertain" ? <p className="mt-1 text-xs leading-5 text-amber-800">Delivery could not be confirmed.</p> : null}</div></div>
          <div className="flex shrink-0 flex-wrap items-center gap-2"><span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${badgeStyles[state]}`}><StatusIcon state={state} />{labels[state]}</span>
            {state === "failed" && item.retryable ? <button type="button" disabled={busy} onClick={() => onRetry(item.id, item.attempts)} className="inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-blue-700 transition hover:border-blue-200 hover:bg-blue-50 focus-visible:outline-2 focus-visible:outline-blue-500 disabled:opacity-50"><svg aria-hidden="true" className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M20 7v5h-5M4 17v-5h5M6.5 6.5A8 8 0 0 1 20 12M4 12a8 8 0 0 0 13.5 5.5" /></svg><span>Retry<span className="sr-only"> failed delivery for {name}</span></span></button> : null}
          </div>
        </li>;
      })}</ul> : null}
      {counts.uncertain > 0 ? <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-900">Unconfirmed invitations are not retried automatically. Check your email provider before sending again.</p> : null}
    </div>
  </section>;
}
