import { useEffect, useRef, useState } from "react";
import { identityApi, type IdentityState } from "./identityApi";
import { exerciseButton, exerciseInput } from "./WorkSampleShared";

export function IdentityOverview({ interviewId }: { interviewId: number }) {
  const [state, setState] = useState<IdentityState>();
  const [error, setError] = useState(""), [note, setNote] = useState(""), [open, setOpen] = useState(false), [busy, setBusy] = useState(false);
  const lock = useRef(false), epoch = useRef(0);
  useEffect(() => {
    setState(undefined); setError(""); setOpen(false); setNote(""); epoch.current += 1;
    let active = true, polling = false;
    const refresh = async () => {
      if (polling || lock.current) return;
      polling = true; const expected = epoch.current;
      try { const value = await identityApi.read(interviewId); if (active && expected === epoch.current) { setState(value); setError(""); } }
      catch { if (active) setError("Identity check unavailable. Do not assume a match."); }
      finally { polling = false; }
    };
    void refresh(); const timer = window.setInterval(() => void refresh(), 2500);
    return () => { active = false; window.clearInterval(timer); };
  }, [interviewId]);
  async function manual() {
    if (lock.current || note.trim().length < 10) return;
    lock.current = true; epoch.current += 1; setBusy(true); setError("");
    try { setState(await identityApi.manual(interviewId, note)); setOpen(false); setNote(""); }
    catch (e) { setError(e instanceof Error ? e.message : "Manual confirmation could not be saved."); }
    finally { lock.current = false; setBusy(false); }
  }
  const matched = !error && state?.status === "matched";
  return <section aria-label="Candidate identity status" className={`mt-4 rounded-2xl border p-4 ${matched ? "border-emerald-100 bg-emerald-50/50" : "border-indigo-100 bg-indigo-50/30"}`}>
    <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{matched ? "Joining photo match" : "Scheduled candidate"}</p>
    <p className="mt-1 text-sm font-semibold text-slate-800">{error || state?.message || "Checking identification status…"}</p>
    {state?.checked_at && !error ? <p className="mt-1 text-xs text-slate-500">Checked {new Date(state.checked_at).toLocaleString()} · {state.status === "manual" ? "Human confirmation" : "Compared with application photo"}</p> : null}
    <p className="mt-2 text-xs leading-5 text-slate-500">Not legal-ID verification or continuous monitoring. No effect on assessment scores.</p>
    {!matched && state?.status !== "manual" ? <button className={`${exerciseButton} mt-3 !min-h-8 !px-3 !py-1.5 !text-xs`} disabled={busy} onClick={() => setOpen(!open)}>Confirm identity manually</button> : null}
    {open ? <div className="mt-3"><label className="block text-xs text-slate-600">How did you confirm the joining candidate?<textarea className={exerciseInput} value={note} maxLength={500} onChange={e => setNote(e.target.value)} /></label><p className="mt-2 text-xs text-slate-500">This records human confirmation, not a biometric match. Do not enter identity-document numbers.</p><button className={`${exerciseButton} mt-2`} disabled={busy || note.trim().length < 10} onClick={() => void manual()}>Save manual confirmation</button></div> : null}
  </section>;
}
