import { useEffect, useState } from "react";
import { type ExerciseState, type ExerciseTask, type ExerciseEvaluation, exerciseLabel } from "./workSampleApi";
import { transcriptTime } from "./transcriptionApi";

export const exerciseButton = "inline-flex min-h-10 items-center justify-center rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40";
export const exercisePrimary = `${exerciseButton} !border-transparent !bg-indigo-700 !text-white hover:!bg-indigo-800`;
export const exerciseInput = "mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-800 outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100";

export function ExerciseClock({ state }: { state: ExerciseState }) {
  const [clock, setClock] = useState(Date.now());
  const [offset, setOffset] = useState(0);
  useEffect(() => { setOffset(Date.parse(state.server_now) - Date.now()); setClock(Date.now()); }, [state.server_now]);
  useEffect(() => { const timer = window.setInterval(() => setClock(Date.now()), 1000); return () => window.clearInterval(timer); }, []);
  const attempt = state.exercise?.attempt;
  if (!attempt || !["running", "paused"].includes(attempt.status)) return null;
  const seconds = attempt.deadline_at ? Math.max(0, Math.ceil((Date.parse(attempt.deadline_at) - clock - offset) / 1000)) : attempt.remaining_seconds;
  return <span aria-label="Exercise time remaining" className={`rounded-lg px-3 py-1.5 font-mono text-sm font-semibold tabular-nums ${seconds < 60 ? "bg-amber-50 text-amber-800" : "bg-indigo-50 text-indigo-800"}`}>{String(Math.floor(seconds / 60)).padStart(2, "0")}:{String(seconds % 60).padStart(2, "0")}{attempt.status === "paused" ? " · Paused" : ""}</span>;
}

export function ExerciseInstructions({ task }: { task: ExerciseTask }) {
  return <div className="space-y-4 text-sm leading-6 text-slate-600">
    <div><h3 className="text-lg font-bold text-slate-900">{task.title}</h3><p className="mt-2 whitespace-pre-wrap">{task.instructions}</p></div>
    {task.materials ? <details className="rounded-xl border border-slate-200 bg-slate-50/60 p-3" open><summary className="cursor-pointer font-semibold text-slate-700">Task materials</summary><pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-white p-3 text-xs leading-6">{task.materials}</pre></details> : null}
    <div className="grid gap-3 sm:grid-cols-2"><section className="rounded-xl bg-indigo-50/60 p-3"><h4 className="font-semibold text-indigo-900">What to submit</h4><p className="mt-1 whitespace-pre-wrap">{task.deliverables}</p></section><section className="rounded-xl bg-teal-50/60 p-3"><h4 className="font-semibold text-teal-900">Tools & time</h4><p className="mt-1 whitespace-pre-wrap">{task.tools_policy}</p><p className="mt-1 text-xs">Working time: {task.duration_minutes} minutes</p></section></div>
  </div>;
}

export function ExerciseFindings({ task, result }: { task: ExerciseTask; result: ExerciseEvaluation }) {
  return <section aria-label="Practical assessment findings" className="mt-4 space-y-3">
    <p className="text-sm leading-6 text-slate-600">{result.summary}</p>
    <div className="grid gap-3 sm:grid-cols-2">{result.findings.map(f => <div key={f.criterion_id} className="rounded-xl border border-slate-100 bg-slate-50/60 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><h4 className="text-sm font-semibold text-slate-800">{task.criteria?.find(c => c.id === f.criterion_id)?.title ?? f.criterion_id}</h4><span className={`rounded-full px-2 py-1 text-xs font-medium ${f.label === "met" ? "bg-emerald-50 text-emerald-800" : f.label === "needs_verification" ? "bg-slate-200 text-slate-700" : "bg-amber-50 text-amber-800"}`}>{exerciseLabel(f.label)}</span></div><p className="mt-2 text-sm leading-6 text-slate-600">{f.reason}</p>{f.evidence.length ? <details className="mt-3"><summary className="cursor-pointer text-xs font-medium text-indigo-700">View evidence</summary>{f.evidence.map((e, i) => <figure key={i} className="mt-2 rounded-lg bg-white p-3"><blockquote className="whitespace-pre-wrap break-words border-l-2 border-indigo-300 pl-3 text-xs leading-6">{e.quote}</blockquote><figcaption className="mt-2 text-xs text-slate-400">{e.field === "discussion" ? `Candidate discussion · ${transcriptTime(result.discussion_sources?.find(s => s.id === e.segment_id)?.start_offset_ms ?? 0)}` : e.field === "content" ? "Submission" : "Explanation"} · lines {e.line_start}–{e.line_end}</figcaption></figure>)}</details> : null}</div>)}</div>
    <p className="text-xs leading-5 text-slate-500">{result.limitation || "Code was not executed. Runtime correctness and test results are not verified."}</p>
  </section>;
}
