import { useState } from "react";
import { type ExerciseAssessment, type ExerciseEvaluation, type ExerciseTask, exerciseLabel } from "./workSampleApi";
import { ExerciseFindings, exerciseButton, exerciseInput, exercisePrimary } from "./WorkSampleShared";

export function WorkSampleReview({ assessment, task, busy, onApprove }: { assessment: ExerciseAssessment; task: ExerciseTask;
  busy: boolean; onApprove: (result: ExerciseEvaluation, reason: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [result, setResult] = useState<ExerciseEvaluation>(assessment.approved_result || assessment.result);
  const [reason, setReason] = useState("");
  const shown = assessment.approved_result || assessment.result;
  if (["queued", "processing"].includes(assessment.status)) return <p role="status" className="mt-4 rounded-xl bg-indigo-50 p-4 text-sm text-indigo-800">Preparing an evidence-linked assessment…</p>;
  if (assessment.status === "failed") return <p role="alert" className="mt-4 rounded-xl bg-amber-50 p-4 text-sm text-amber-800">{assessment.error}</p>;
  return <section aria-label="Exercise review" className="mt-5 border-t border-slate-100 pt-5">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h3 className="font-semibold text-slate-900">{assessment.status === "approved" ? "Approved assessment" : "AI assessment draft"}</h3><p className="mt-1 text-xs text-slate-500">Separate from the CV/interview final score.</p></div><span className="rounded-xl bg-indigo-50 px-3 py-2 text-sm font-bold text-indigo-800">{shown.score === null || shown.score === undefined ? "Needs verification" : `${shown.score}%`}</span></div>
    <ExerciseFindings task={task} result={shown} />
    {assessment.status === "approved" ? <p className="mt-4 text-xs text-slate-500">Approved by interviewer · {assessment.approved_at ? new Date(assessment.approved_at).toLocaleString() : ""}<br />{assessment.review_reason}</p> : <>
      <button className={`${exerciseButton} mt-4`} disabled={busy} onClick={() => setEditing(!editing)}>{editing ? "Close adjustments" : "Adjust findings"}</button>
      {editing ? <div className="mt-4 space-y-3"><label className="block text-sm">Summary<textarea className={exerciseInput} rows={3} maxLength={400} value={result.summary} onChange={e => setResult({ ...result, summary: e.target.value })} /></label>
        {result.findings.map((finding, i) => <fieldset key={finding.criterion_id} disabled={busy} className="rounded-xl border border-slate-200 p-3"><legend className="px-1 text-sm font-semibold">{task.criteria.find(c => c.id === finding.criterion_id)?.title}</legend>
          <label className="block text-xs text-slate-500">Outcome<select className={exerciseInput} value={finding.label} onChange={e => setResult({ ...result, findings: result.findings.map((f, n) => n === i ? { ...f, label: e.target.value as typeof finding.label } : f) })}>{["met", "partially_met", "unmet", "needs_verification"].map(label => <option value={label} key={label}>{exerciseLabel(label)}</option>)}</select></label>
          <label className="mt-2 block text-xs text-slate-500">Reason<textarea className={exerciseInput} rows={2} maxLength={600} value={finding.reason} onChange={e => setResult({ ...result, findings: result.findings.map((f, n) => n === i ? { ...f, reason: e.target.value } : f) })} /></label>
          <details className="mt-3"><summary className="cursor-pointer text-xs text-indigo-700">Edit exact evidence</summary><p className="mt-2 text-xs text-slate-500">Every scored finding needs a matching quote from the final submission. Line numbers start at 1.</p>{finding.evidence.map((evidence, j) => {
            const change = (patch: Partial<typeof evidence>) => setResult({ ...result, findings: result.findings.map((f, n) => n === i ? { ...f, evidence: f.evidence.map((e, m) => m === j ? { ...e, ...patch } : e) } : f) });
            return <div key={j} className="mt-2 rounded-lg bg-slate-50 p-2">
              <div className="grid grid-cols-3 gap-2">
                <label className="text-xs">Source<select className={exerciseInput} value={evidence.field} onChange={e => change({ field: e.target.value as typeof evidence.field, segment_id: null })}>
                  <option value="content">Submission</option><option value="explanation">Explanation</option>
                  {assessment.result.discussion_sources?.some(s => s.speaker === "CANDIDATE") ? <option value="discussion">Discussion</option> : null}
                </select></label>
                <label className="text-xs">First line<input type="number" min={1} className={exerciseInput} value={evidence.line_start} onChange={e => change({ line_start: Number(e.target.value) })} /></label>
                <label className="text-xs">Last line<input type="number" min={1} className={exerciseInput} value={evidence.line_end} onChange={e => change({ line_end: Number(e.target.value) })} /></label>
              </div>
              {evidence.field === "discussion" ? <label className="mt-2 block text-xs">Linked candidate passage<select className={exerciseInput} value={evidence.segment_id ?? ""} onChange={e => change({ segment_id: e.target.value })}><option value="">Select a passage</option>{assessment.result.discussion_sources?.filter(s => s.speaker === "CANDIDATE").map(s => <option value={s.id} key={s.id}>{s.text.slice(0, 100)}</option>)}</select></label> : null}
              <label className="text-xs">Exact quote<textarea className={exerciseInput} rows={2} maxLength={4000} value={evidence.quote} onChange={e => change({ quote: e.target.value })} /></label>
              <button className="mt-1 text-xs text-red-700" onClick={() => setResult({ ...result, findings: result.findings.map((f, n) => n === i ? { ...f, evidence: f.evidence.filter((_, m) => m !== j) } : f) })}>Remove quote</button>
            </div>;
          })}{finding.evidence.length < 6 ? <button className={`${exerciseButton} mt-2`} onClick={() => setResult({ ...result, findings: result.findings.map((f, n) => n === i ? { ...f, evidence: [...f.evidence, { field: "content", line_start: 1, line_end: 1, quote: "" }] } : f) })}>Add quote</button> : null}</details>
        </fieldset>)}
      </div> : null}
      <label className="mt-4 block text-sm font-medium text-slate-700">Review note<textarea className={exerciseInput} rows={2} value={reason} maxLength={1000} placeholder="Confirm your review and explain any changes." onChange={e => setReason(e.target.value)} /></label>
      <button className={`${exercisePrimary} mt-3`} disabled={busy || reason.trim().length < 5} onClick={() => onApprove(result, reason)}>Approve assessment</button>
      <p className="mt-2 text-xs text-slate-500">Approval locks this review. The original AI draft is retained.</p>
    </>}
  </section>;
}
