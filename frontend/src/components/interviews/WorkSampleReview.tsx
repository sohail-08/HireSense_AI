import { useState } from "react";
import { PreviewModal } from "../common/PreviewModal";
import { type PracticalScoreReview } from "./workSampleApi";
import { exerciseButton, exercisePrimary } from "./WorkSampleShared";

export function WorkSampleReview({ assessment, busy, onApprove, onScore }: {
  assessment?: PracticalScoreReview | null; busy: boolean; onApprove: () => void; onScore: () => void;
}) {
  const [confirm, setConfirm] = useState(false);
  const [reviewed, setReviewed] = useState(false);
  const result = assessment?.result;
  const approved = assessment?.status === "approved";
  const available = ["scored", "approved"].includes(assessment?.status ?? "") && result?.verified === true && typeof result.score === "number";
  const processing = ["queued", "processing"].includes(assessment?.status ?? "");
  return <section aria-label="Practical task score" className={`rounded-2xl border p-4 ${approved ? "border-emerald-100 bg-emerald-50/40" : "border-indigo-100 bg-indigo-50/30"}`}>
    <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-wide text-indigo-700">AI correctness review</p><h3 className="mt-1 font-semibold text-slate-900">{approved ? "Score approved" : available ? "Review the proposed score" : processing ? "Verifying the response…" : "Verification needed"}</h3></div>
      {available ? <span aria-label="Practical correctness score" className="rounded-xl bg-white px-3 py-2 text-xl font-bold tabular-nums text-indigo-800">{result.score}/100</span> : null}
    </div>
    {processing ? <p role="status" className="mt-2 text-sm leading-6 text-slate-600">The AI is checking the saved work against the task. You can leave this panel and return later.</p> : available ? <>
      <p className="mt-2 text-sm leading-6 text-slate-700">{result.summary}</p>
      <p className="mt-2 text-xs text-slate-500">{approved ? "Included" : "Once approved, contributes"} {(result.score! / 10).toFixed(1)} of the final score’s 10 practical points.</p>
      <details className="mt-3"><summary className="cursor-pointer text-xs font-semibold text-indigo-700">Review evidence & limitations</summary>
        {result.evidence?.map((item, index) => <blockquote key={index} className="mt-3 whitespace-pre-wrap rounded-xl border-l-2 border-indigo-300 bg-white p-3 text-sm">{item.quote}<p className="mt-2 text-xs text-slate-400">Saved response · lines {item.line_start}–{item.line_end}</p></blockquote>)}
        <p className="mt-3 text-xs leading-5 text-slate-500">{result.verification_reason}</p><p className="mt-2 text-xs leading-5 text-slate-500">{result.limitation}</p>
      </details>
      {approved ? <p className="mt-3 text-xs text-emerald-800">Approved by interviewer · {new Date(assessment!.approved_at!).toLocaleString()} · Final</p> : <button className={`${exercisePrimary} mt-4`} disabled={busy} onClick={() => { setReviewed(false); setConfirm(true); }}>Approve score</button>}
    </> : <><p className="mt-2 text-sm leading-6 text-slate-600">{assessment?.error || result?.summary || "The AI will verify correctness and propose a score. You only approve the result; you do not assign marks."}</p><p className="mt-2 text-xs text-slate-500">No practical marks count until a verified score is approved.</p><button className={`${exerciseButton} mt-3`} disabled={busy} onClick={onScore}>{assessment ? "Retry AI review" : "Verify & score task"}</button></>}
    {confirm && available && !approved ? <PreviewModal title="Approve this AI score?" busy={busy} onClose={() => setConfirm(false)}>
      <p className="text-sm leading-6 text-slate-600">Approve the saved {result.score}/100 score for this submission. It contributes {(result.score! / 10).toFixed(1)} final-score points. Approval is final; you cannot change the marks.</p>
      <label className="mt-4 flex items-start gap-2 text-sm text-slate-700"><input type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)} className="mt-1" />I have reviewed the AI score and saved response.</label>
      <div className="mt-5 flex justify-end gap-2"><button className={exerciseButton} disabled={busy} onClick={() => setConfirm(false)}>Cancel</button><button className={exercisePrimary} disabled={busy || !reviewed} onClick={onApprove}>Confirm approval</button></div>
    </PreviewModal> : null}
  </section>;
}
