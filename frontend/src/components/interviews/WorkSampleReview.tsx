import { useState } from "react";
import { PreviewModal } from "../common/PreviewModal";
import { type CorrectnessDecision } from "./workSampleApi";
import { exerciseButton, exerciseInput, exercisePrimary } from "./WorkSampleShared";
export function WorkSampleReview({ decision, busy, onDecide }: { decision?: CorrectnessDecision | null; busy: boolean; onDecide: (correct: boolean, note: string) => void }) {
  const [choice, setChoice] = useState<boolean>();
  const [note, setNote] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  if (decision) return <section aria-label="Practical correctness decision" className={`rounded-2xl border p-4 ${decision.correct ? "border-emerald-100 bg-emerald-50/50" : "border-rose-100 bg-rose-50/50"}`}>
    <div className="flex items-center justify-between gap-3"><h3 className="font-semibold">{decision.correct ? "Correctness approved" : "Correctness not approved"}</h3><span className="rounded-xl bg-white px-3 py-2 text-lg font-bold tabular-nums">{decision.score}/100</span></div>
    <p className="mt-2 text-sm text-slate-600">{decision.summary}</p><p className="mt-2 text-xs text-slate-500">Interviewer decision · {new Date(decision.approved_at).toLocaleString()} · Final</p>
  </section>;
  return <section aria-label="Review practical correctness" className="rounded-2xl border border-indigo-100 bg-indigo-50/30 p-4">
    <h3 className="font-semibold text-slate-900">Is the response correct?</h3><p className="mt-2 text-sm leading-6 text-slate-600">Discuss the candidate’s approach during the interview, then decide. Approval awards 100 marks; rejection awards 0. This task contributes 10% of the final score.</p>
    <div className="mt-4 flex flex-wrap gap-2"><button className={exercisePrimary} disabled={busy} onClick={() => { setConfirmed(false); setChoice(true); }}>Approve · 100 marks</button><button className={exerciseButton} disabled={busy} onClick={() => { setConfirmed(false); setChoice(false); }}>Reject · 0 marks</button></div>
    {choice !== undefined ? <PreviewModal title={choice ? "Approve correctness?" : "Reject correctness?"} busy={busy} onClose={() => setChoice(undefined)}>
      <p className="text-sm leading-6 text-slate-600">This final decision awards {choice ? "100" : "0"} practical marks ({choice ? "10" : "0"} points toward the final score). It cannot be changed afterward.</p>
      <label className="mt-3 block text-sm">Note (optional)<textarea className={exerciseInput} rows={2} maxLength={1000} value={note} onChange={e => setNote(e.target.value)} /></label>
      <label className="mt-4 flex items-start gap-2 text-sm text-slate-700"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} className="mt-1" />I have reviewed the saved response.</label>
      <div className="mt-5 flex justify-end gap-2"><button className={exerciseButton} disabled={busy} onClick={() => setChoice(undefined)}>Cancel</button><button className={exercisePrimary} disabled={busy || !confirmed} onClick={() => onDecide(choice, note)}>Confirm decision</button></div>
    </PreviewModal> : null}
  </section>;
}
