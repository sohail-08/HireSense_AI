import { useEffect, useRef, useState } from "react";
import { PreviewModal } from "../common/PreviewModal";
import { workSampleApi, exerciseFinished, exerciseLabel, type ExerciseState, type ExerciseTask } from "./workSampleApi";
import { WorkSampleTaskEditor, emptyExerciseTask } from "./WorkSampleTaskEditor";
import { ExerciseClock, ExerciseInstructions, exerciseButton, exerciseInput, exercisePrimary } from "./WorkSampleShared";
import { WorkSampleReview } from "./WorkSampleReview";

export function WorkSamplePanel({ interviewId, closed = false, refreshKey = 0, onAskAssistant }: {
  interviewId: number; closed?: boolean; refreshKey?: number; onAskAssistant?: () => void;
}) {
  const [state, setState] = useState<ExerciseState>();
  const [task, setTask] = useState<ExerciseTask>(structuredClone(emptyExerciseTask));
  const [templates, setTemplates] = useState<{ id: number; task: ExerciseTask }[]>([]);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [reason, setReason] = useState(""), [confirmShare, setConfirmShare] = useState(false);
  const dirty = useRef(false), editVersion = useRef(0), lock = useRef(false), epoch = useRef(0);
  const accept = (value: ExerciseState, reset = false) => {
    setState(value);
    if (reset || !dirty.current) { setTask(value.exercise?.task ?? structuredClone(emptyExerciseTask)); editVersion.current = value.exercise?.version ?? 0; dirty.current = false; }
  };
  useEffect(() => {
    let active = true, polling = false;
    dirty.current = false;
    const refresh = async () => {
      if (polling || lock.current) return;
      polling = true;
      const expectedEpoch = epoch.current;
      try { const value = await workSampleApi.read(interviewId); if (active && expectedEpoch === epoch.current) accept(value); }
      catch (e) { if (active) setError(e instanceof Error ? e.message : "Exercise could not be loaded."); }
      finally { polling = false; }
    };
    void refresh();
    void workSampleApi.templates().then(value => { if (active) setTemplates(value); }).catch(() => {});
    const timer = window.setInterval(() => void refresh(), 2500);
    return () => { active = false; window.clearInterval(timer); };
  }, [interviewId, refreshKey]);
  async function perform(work: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true; epoch.current += 1; setBusy(true); setError(""); setNotice("");
    try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "Exercise action failed. Please retry."); }
    finally { lock.current = false; setBusy(false); }
  }
  const exercise = state?.exercise, submission = exercise?.attempt;
  const editing = !exercise || exercise.status === "draft";
  const change = (value: ExerciseTask) => { dirty.current = true; setTask(value); };
  const action = (name: string) => exercise && perform(async () => { accept(await workSampleApi.action(interviewId, exercise.version, name, reason)); setReason(""); });
  return <section aria-label="Live work-sample studio" className="min-w-0 space-y-5 p-4 sm:p-5">
    <header className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-wider text-indigo-700">Live practical task</p><h2 className="mt-1 text-lg font-bold text-slate-900">Practical exercise</h2><p className="mt-1 text-sm text-slate-500">One submission · up to 15 minutes · AI scores, interviewer approves</p></div><div className="flex flex-wrap gap-2">{exercise ? <span className="rounded-full bg-indigo-50 px-3 py-1.5 text-xs font-medium text-indigo-800">{exerciseLabel(exercise.status)}</span> : null}{state ? <ExerciseClock state={state} /> : null}</div></header>
    {error ? <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-800">{error}</p> : null}
    {notice ? <p role="status" className="rounded-xl bg-teal-50 p-3 text-sm text-teal-800">{notice}</p> : null}
    {!state ? <p role="status">Loading practical exercise…</p> : editing && !closed ? <>
      <div className="rounded-2xl border border-indigo-100 bg-indigo-50/40 p-4"><h3 className="text-sm font-semibold text-indigo-900">Let the interview assistant suggest a task</h3><p className="mt-2 text-sm leading-6 text-slate-600">Ask for a practical task, choose a suggestion, and its draft will appear here. You can also prepare it manually.</p>{onAskAssistant ? <button className={`${exerciseButton} mt-3`} onClick={onAskAssistant}>Ask interview assistant</button> : null}</div>
      {templates.length ? <label className="block text-sm">Saved tasks<select className={exerciseInput} defaultValue="" disabled={busy} onChange={e => { const value = templates.find(t => t.id === Number(e.target.value)); if (value) change(structuredClone(value.task)); }}><option value="">Choose a saved task</option>{templates.map(t => <option key={t.id} value={t.id}>{t.task.title}</option>)}</select></label> : null}
      <WorkSampleTaskEditor task={task} onChange={change} disabled={busy} />
      <div className="flex flex-wrap gap-2"><button className={exerciseButton} disabled={busy} onClick={() => void perform(async () => { accept(await workSampleApi.save(interviewId, task, editVersion.current), true); setNotice("Private task saved."); })}>Save private draft</button><button className={exerciseButton} disabled={busy} onClick={() => void perform(async () => { const value = await workSampleApi.template(task); setTemplates(prev => [value, ...prev]); setNotice("Task saved for reuse."); })}>Save as template</button><button className={exercisePrimary} disabled={busy} onClick={() => setConfirmShare(true)}>Approve & share task</button></div>
    </> : exercise ? <>
      <ExerciseInstructions task={exercise.task} />
      {submission ? <>
        <div className="rounded-xl border border-slate-200 bg-slate-50/50 p-4"><div className="flex flex-wrap items-center justify-between gap-3"><h3 className="text-sm font-semibold">{exerciseLabel(submission.status)}</h3>{!closed && submission.status === "ready" ? <button className={exercisePrimary} disabled={busy} onClick={() => void action("start")}>Start exercise</button> : null}{!closed && submission.status === "paused" ? <button className={exercisePrimary} disabled={busy} onClick={() => void action("resume")}>Resume exercise</button> : null}</div>
          {submission.status === "shared" ? <p className="mt-2 text-sm text-slate-500">Waiting for the candidate to read the task and select Ready. The timer has not started.</p> : null}
          {!closed && submission.status === "running" ? <div className="mt-3 flex flex-wrap items-end gap-2"><label className="min-w-0 flex-1 text-xs text-slate-600">Reason for pausing<input className={exerciseInput} maxLength={1000} value={reason} onChange={e => setReason(e.target.value)} placeholder="For example: connection interrupted." /></label><button className={exerciseButton} disabled={busy || reason.trim().length < 5} onClick={() => void action("pause")}>Pause exercise</button></div> : null}
        </div>
        <section aria-label="Candidate live work"><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold text-slate-800">{exerciseFinished(submission.status) ? "Saved response" : "Candidate workspace · read only"}</h3><span className="text-xs text-slate-400">{submission.saved_at ? `Saved ${new Date(submission.saved_at).toLocaleTimeString()}` : "No work saved yet"}</span></div><pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-xl border border-slate-200 bg-slate-50 p-4 font-mono text-sm leading-6">{submission.content || "The candidate’s saved work will appear here."}</pre>
          {["time_ended", "interview_ended"].includes(submission.status) ? <p className="mt-2 text-xs text-amber-800">Latest server-saved draft preserved. This was not a candidate-confirmed submission.</p> : null}
        </section>
        {exerciseFinished(submission.status) && submission.submission_hash ? <WorkSampleReview assessment={exercise.assessment} busy={busy}
          onScore={() => void perform(async () => accept(await workSampleApi.score(interviewId, submission.submission_hash!)))}
          onApprove={() => { const score = exercise.assessment; if (score?.result_hash) void perform(async () => accept(await workSampleApi.approve(interviewId, score.id, submission.submission_hash!, score.result_hash!))); }} /> : null}
      </> : null}
    </> : <p className="rounded-xl bg-slate-50 p-4 text-sm text-slate-500">No practical task was saved, or its retention period has ended.</p>}
    {confirmShare ? <PreviewModal title="Approve and share this task?" onClose={() => setConfirmShare(false)} busy={busy}><p className="text-sm leading-6 text-slate-600">The candidate gets one submission and at most 15 minutes of working time. Sharing locks the instructions. The timer starts only after readiness and your Start action.</p><div className="mt-5 flex justify-end gap-2"><button className={exerciseButton} disabled={busy} onClick={() => setConfirmShare(false)}>Cancel</button><button className={exercisePrimary} disabled={busy} onClick={() => void perform(async () => { const saved = await workSampleApi.save(interviewId, task, editVersion.current); accept(saved, true); accept(await workSampleApi.action(interviewId, saved.exercise!.version, "share"), true); setConfirmShare(false); })}>Approve & share</button></div></PreviewModal> : null}
  </section>;
}
