import { useEffect, useRef, useState } from "react";
import { identityApi, type IdentityState } from "./identityApi";
import { exerciseButton, exerciseInput } from "./WorkSampleShared";
import { formatDateTime } from "../../utils/dateTime";

function VerificationMark({ kind }: { kind: "matched" | "manual" | "attention" | "pending" }) {
  return <svg aria-hidden="true" className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
    {kind === "manual" ? <><circle cx="9" cy="8" r="3" /><path d="M3 20v-2a6 6 0 0 1 10-4.5M15 18l2 2 4-5" /></>
      : kind === "attention" ? <><path d="m12 3 9 17H3L12 3Z" /><path d="M12 9v4m0 3h.01" /></>
      : <><path d="m12 3 8 3v6c0 4-4 7-8 9-4-2-8-5-8-9V6l8-3Z" />{kind === "matched" ? <path d="m8 12 3 3 5-6" /> : <path d="M9 12h6" />}</>}
  </svg>;
}

const captureButton = "inline-flex min-h-9 items-center justify-center gap-2 rounded-xl border border-blue-200 bg-blue-50 px-3.5 py-2 text-xs font-semibold text-blue-700 transition hover:border-blue-300 hover:bg-blue-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500 disabled:cursor-not-allowed disabled:opacity-50";

export function IdentityOverview({ interviewId }: { interviewId: number }) {
  const [state, setState] = useState<IdentityState>();
  const [error, setError] = useState(""), [note, setNote] = useState(""), [open, setOpen] = useState(false), [busy, setBusy] = useState(false);
  const lock = useRef(false), epoch = useRef(0);
  useEffect(() => {
    setState(undefined); setError(""); setOpen(false); setNote(""); setBusy(false); epoch.current += 1;
    let active = true, polling = false;
    const refresh = async () => {
      if (polling || lock.current) return;
      polling = true; const expected = epoch.current;
      try { const value = await identityApi.read(interviewId); if (active && expected === epoch.current) { setState(value); setError(""); } }
      catch { if (active) setError("Identity check unavailable. Do not assume a match."); }
      finally { polling = false; }
    };
    void refresh(); const timer = window.setInterval(() => void refresh(), 2500);
    return () => { active = false; epoch.current += 1; window.clearInterval(timer); };
  }, [interviewId]);
  async function manual() {
    if (lock.current || note.trim().length < 10) return;
    lock.current = true; epoch.current += 1; setBusy(true); setError("");
    try { setState(await identityApi.manual(interviewId, note)); setOpen(false); setNote(""); }
    catch (e) { setError(e instanceof Error ? e.message : "Manual confirmation could not be saved."); }
    finally { lock.current = false; setBusy(false); }
  }
  async function capture() {
    if (lock.current || !state?.capture_allowed || state.capture_pending) return;
    lock.current = true; const expected = ++epoch.current; setBusy(true); setError("");
    try { const next = await identityApi.capture(interviewId, state.version); if (epoch.current === expected) setState(next); }
    catch { if (epoch.current === expected) setError("Camera capture could not be requested. Refresh the status and try again."); }
    finally { lock.current = false; if (epoch.current === expected) setBusy(false); }
  }
  const matched = !error && state?.status === "matched";
  const manualCheck = !error && state?.status === "manual";
  const attention = Boolean(error) || ["low_similarity", "unverified", "no_face", "multiple_faces", "poor_quality"].includes(state?.status ?? "");
  const kind = matched ? "matched" : manualCheck ? "manual" : attention ? "attention" : "pending";
  const tone = matched ? "border-emerald-200/70 from-emerald-50/80" : attention ? "border-amber-200/70 from-amber-50/70" : "border-slate-200 from-blue-50/60";
  const iconTone = matched ? "bg-emerald-100 text-emerald-700 ring-emerald-200/60" : attention ? "bg-amber-100 text-amber-700 ring-amber-200/60" : "bg-blue-100 text-blue-600 ring-blue-200/60";
  return <section aria-label="Candidate identity status" data-state={error ? "unavailable" : state?.status ?? "loading"}
    className={`mt-4 min-w-0 overflow-hidden rounded-2xl border bg-gradient-to-br ${tone} via-white to-white shadow-sm`}>
    <header className="flex flex-wrap items-center justify-between gap-2 px-4 pt-4">
      <h3 className="text-xs font-semibold tracking-wide text-slate-600">Photo verification</h3>
      <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200/70 bg-white/90 px-2 py-1 text-[10px] font-medium text-slate-500">
        <svg aria-hidden="true" className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><rect x="5" y="10" width="14" height="11" rx="3" /><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 5v2" /></svg>
        Interviewer only
      </span>
    </header>
    <div className="p-4">
      <div className="flex items-start gap-3">
        <span className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl ring-1 ring-inset ${iconTone}`}><VerificationMark kind={kind} /></span>
        <div className="min-w-0 flex-1" aria-live="polite" aria-atomic="true">
          <p role={error ? "alert" : undefined} className="break-words text-sm font-semibold leading-6 text-slate-900">{error || state?.message || "Checking identification status…"}</p>
          {!error && state?.checked_at ? <>
            <p className="mt-0.5 text-xs leading-5 text-slate-500">{manualCheck ? "Human confirmation · not a photo match" : "Compared with application photo"}</p>
            <p className="mt-1.5 flex items-start gap-1.5 text-[11px] leading-5 text-slate-500">
              <svg aria-hidden="true" className="mt-1 h-3 w-3 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>
              <span>Checked {formatDateTime(state.checked_at)}</span>
            </p>
          </> : null}
        </div>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        {state?.enabled ? <button type="button" className={captureButton} disabled={busy || Boolean(error) || !state.capture_allowed || state.capture_pending} onClick={() => void capture()}>
          {state.capture_pending ? <svg aria-hidden="true" className="h-3.5 w-3.5 motion-safe:animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="9" opacity=".25" /><path d="M12 3a9 9 0 0 1 9 9" /></svg>
            : <svg aria-hidden="true" className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="m8 5 1.5-2h5L16 5h4a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h4Z" /><circle cx="12" cy="12" r="4" /></svg>}
          {state.capture_pending ? "Waiting for camera…" : state.checked_at || state.status === "capture_requested" ? "Capture face again" : "Capture face"}
        </button> : null}
        {!matched && state?.status !== "manual" ? <button type="button" aria-expanded={open} className={`${exerciseButton} !min-h-9 !px-3 !py-2 !text-xs focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500`} disabled={busy} onClick={() => setOpen(!open)}>Confirm identity manually</button> : null}
      </div>
      {state?.enabled && !state.capture_allowed ? <p className="mt-2 text-xs leading-5 text-slate-500">Available after the candidate consents and joins with a ready application photo.</p> : null}
      {open ? <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50/70 p-3"><label className="block text-xs font-medium leading-5 text-slate-600">How did you confirm the joining candidate?<textarea className={exerciseInput} value={note} maxLength={500} onChange={e => setNote(e.target.value)} /></label><p className="mt-2 text-xs leading-5 text-slate-500">This records human confirmation, not a biometric match. Do not enter identity-document numbers.</p><button type="button" className={`${captureButton} mt-3`} disabled={busy || note.trim().length < 10} onClick={() => void manual()}>Save manual confirmation</button></div> : null}
    </div>
    <footer className="border-t border-slate-100 bg-slate-50/70 px-4 py-3">
      <p className="flex items-center gap-1.5 text-[11px] font-medium text-slate-600"><svg aria-hidden="true" className="h-3.5 w-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="12" cy="12" r="9" /><path d="M12 11v6m0-10h.01" /></svg>No effect on assessment scores</p>
      <p className="mt-1 text-[11px] leading-5 text-slate-500">Not legal-ID verification or continuous monitoring.</p>
    </footer>
  </section>;
}
