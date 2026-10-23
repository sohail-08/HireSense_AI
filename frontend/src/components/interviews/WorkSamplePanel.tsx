import { useEffect, useRef, useState } from "react";
import { PreviewModal } from "../common/PreviewModal";
import { workSampleApi, exerciseFinished, exerciseLabel, type ExerciseState, type ExerciseTask } from "./workSampleApi";
import { WorkSampleTaskEditor, emptyExerciseTask } from "./WorkSampleTaskEditor";
import { ExerciseClock, ExerciseInstructions, exerciseButton, exerciseInput, exercisePrimary } from "./WorkSampleShared";
import { WorkSampleReview } from "./WorkSampleReview";
import { transcriptionApi, transcriptTime, type TranscriptLine } from "./transcriptionApi";

export function WorkSamplePanel({ interviewId, closed = false }: { interviewId: number; closed?: boolean }) {
  const [state, setState] = useState<ExerciseState>();
  const [task, setTask] = useState<ExerciseTask>(structuredClone(emptyExerciseTask));
  const [templates, setTemplates] = useState<{ id: number; task: ExerciseTask }[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [brief, setBrief] = useState("");
  const [reason, setReason] = useState("");
  const [minutes, setMinutes] = useState(5);
  const [confirmShare, setConfirmShare] = useState(false);
  const [confirmRetry, setConfirmRetry] = useState(false);
  const [discussion, setDiscussion] = useState<TranscriptLine[]>([]);
  const [selectedDiscussion, setSelectedDiscussion] = useState<string[]>([]);
  const [discussionCursor, setDiscussionCursor] = useState<string | null | undefined>();
  const dirty = useRef(false), editVersion = useRef(0), lock = useRef(false);
  const mounted = useRef(true);
  const mutationEpoch = useRef(0);
  const accept = (value: ExerciseState, reset = false) => {
    setState(value);
    if (reset || !dirty.current) { setTask(value.exercise?.task ?? structuredClone(emptyExerciseTask)); editVersion.current = value.exercise?.version ?? 0; dirty.current = false; }
  };
  useEffect(() => {
    mounted.current = true;
    let active = true, polling = false;
    const refresh = async () => {
      if (polling || lock.current) return;
      polling = true;
      const epoch = mutationEpoch.current;
      try { const value = await workSampleApi.read(interviewId); if (active && epoch === mutationEpoch.current) accept(value); }
      catch (e) { if (active) setError(e instanceof Error ? e.message : "Exercise could not be loaded."); }
      finally { polling = false; }
    };
    void refresh();
    void workSampleApi.templates().then(value => { if (active) setTemplates(value); }).catch(() => {});
    const timer = window.setInterval(() => void refresh(), 2500);
    return () => { active = false; mounted.current = false; window.clearInterval(timer); };
  }, [interviewId]);
  async function perform(work: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true; mutationEpoch.current += 1; setBusy(true); setError(""); setNotice("");
    try { await work(); }
    catch (e) { if (mounted.current) setError(e instanceof Error ? e.message : "Exercise action failed. Please try again."); }
    finally { lock.current = false; if (mounted.current) setBusy(false); }
  }
  const exercise = state?.exercise, attempt = exercise?.attempt;
  const editing = !exercise || exercise.status === "draft";
  const changeTask = (value: ExerciseTask) => { dirty.current = true; setTask(value); };
  async function action(actionName: string) {
    if (!exercise) return;
    await perform(async () => { accept(await workSampleApi.action(interviewId, exercise.version, actionName, reason, minutes)); setReason(""); });
  }
  const assessment = exercise?.assessments?.find(a => a.attempt_id === attempt?.id);
  return <section aria-label="Live work-sample studio" className="min-w-0 space-y-5 p-4 sm:p-5">
    <header className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-wider text-indigo-700">Live work-sample studio</p><h2 className="mt-1 text-lg font-bold text-slate-900">Practical exercise</h2><p className="mt-1 text-sm text-slate-500">See the work. Discuss the reasoning.</p></div><div className="flex flex-wrap gap-2">{exercise ? <span className="rounded-full bg-indigo-50 px-3 py-1.5 text-xs font-medium text-indigo-800">{exerciseLabel(exercise.status)}</span> : null}{state ? <ExerciseClock state={state} /> : null}</div></header>
    {error ? <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-800">{error}</p> : null}
    {notice ? <p role="status" className="rounded-xl bg-teal-50 p-3 text-sm text-teal-800">{notice}</p> : null}
    {!state ? <p role="status" className="text-sm text-slate-500">Loading practical exercise…</p> : editing && !closed ? <>
      <div className="rounded-2xl border border-indigo-100 bg-indigo-50/40 p-4"><p className="text-sm font-semibold text-indigo-900">Prepare a short, realistic task</p><p className="mt-1 text-xs leading-5 text-slate-500">Use the same approved task and criteria for comparable candidates. Nothing is shared until you approve it.</p>
        {templates.length ? <label className="mt-3 block text-xs font-medium text-slate-600">Saved templates<select className={exerciseInput} defaultValue="" disabled={busy} onChange={e => { const template = templates.find(t => t.id === Number(e.target.value)); if (template) changeTask(structuredClone(template.task)); }}><option value="">Choose a template</option>{templates.map(t => <option key={t.id} value={t.id}>{t.task.title}</option>)}</select></label> : null}
        <details className="mt-3"><summary className="cursor-pointer text-sm font-medium text-indigo-700">Draft with AI</summary><label className="mt-2 block text-xs text-slate-600">Describe the skill to assess<textarea className={exerciseInput} rows={2} maxLength={2000} value={brief} onChange={e => setBrief(e.target.value)} placeholder="For example: a short API validation exercise using Python." /></label><button className={`${exerciseButton} mt-2`} disabled={busy || brief.trim().length < 5} onClick={() => void perform(async () => { const value = await workSampleApi.draft(interviewId, brief); changeTask(value.task); setNotice(value.notice); })}>{busy ? "Working…" : "Generate task draft"}</button><p className="mt-2 text-xs text-slate-500">Uses the job description and available knowledge sources. Review all generated materials.</p></details>
      </div>
      <WorkSampleTaskEditor task={task} onChange={changeTask} disabled={busy} />
      <div className="flex flex-wrap gap-2"><button className={exerciseButton} disabled={busy} onClick={() => void perform(async () => { accept(await workSampleApi.save(interviewId, task, editVersion.current), true); setNotice("Private task saved."); })}>Save private draft</button><button className={exerciseButton} disabled={busy} onClick={() => void perform(async () => { const value = await workSampleApi.template(task); setTemplates(prev => [value, ...prev]); setNotice("Template saved for future interviews."); })}>Save as template</button><button className={exercisePrimary} disabled={busy} onClick={() => setConfirmShare(true)}>Approve & share task</button></div>
    </> : exercise ? <>
      <ExerciseInstructions task={exercise.task} />
      {attempt ? <>
        <div className="rounded-xl border border-slate-200 bg-slate-50/50 p-4"><div className="flex flex-wrap items-center justify-between gap-3"><h3 className="text-sm font-semibold">Attempt {attempt.number} · {exerciseLabel(attempt.status)}</h3>{!closed && attempt.status === "ready" ? <button className={exercisePrimary} disabled={busy} onClick={() => void action("start")}>Start exercise</button> : null}{!closed && attempt.status === "paused" ? <button className={exercisePrimary} disabled={busy} onClick={() => void action("resume")}>Resume exercise</button> : null}</div>
          {attempt.status === "shared" ? <p className="mt-2 text-sm text-slate-500">Waiting for the candidate to read the instructions and select Ready. The timer has not started.</p> : null}
          {!closed && ["running", "paused"].includes(attempt.status) ? <div className="mt-4"><label className="block text-xs text-slate-600">Reason for timing adjustment<input className={exerciseInput} maxLength={1000} value={reason} onChange={e => setReason(e.target.value)} placeholder="For example: connection interrupted." /></label><div className="mt-2 flex flex-wrap items-end gap-2">{attempt.status === "running" ? <button className={exerciseButton} disabled={busy || reason.trim().length < 5} onClick={() => void action("pause")}>Pause exercise</button> : null}<label className="text-xs text-slate-600">Extra minutes<input type="number" min={1} max={60} className={`${exerciseInput} !w-20`} value={minutes} onChange={e => setMinutes(Number(e.target.value))} /></label><button className={exerciseButton} disabled={busy || reason.trim().length < 5} onClick={() => void action("extend")}>Extend time</button></div></div> : null}
        </div>
        <section aria-label="Candidate live work"><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold text-slate-800">{exerciseFinished(attempt.status) ? "Saved submission" : "Candidate workspace · read only"}</h3><span className="text-xs text-slate-400">{attempt.saved_at ? `Saved ${new Date(attempt.saved_at).toLocaleTimeString()}` : "No work saved yet"}</span></div><pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-xl border border-slate-200 bg-slate-50 p-4 font-mono text-sm leading-6">{attempt.content || "The candidate’s saved work will appear here."}</pre>{attempt.explanation ? <div className="mt-3 rounded-xl bg-indigo-50/40 p-4"><h4 className="text-xs font-semibold text-indigo-800">Candidate explanation</h4><p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-600">{attempt.explanation}</p></div> : null}
          {attempt.status === "time_ended" || attempt.status === "interview_ended" ? <p className="mt-2 text-xs text-amber-800">Latest server-saved draft preserved. This was not a candidate-confirmed submission.</p> : null}
        </section>
        {exerciseFinished(attempt.status) && !assessment ? <details className="rounded-xl border border-slate-200 p-4"><summary className="cursor-pointer text-sm font-medium text-indigo-700">Link discussion evidence (optional)</summary><p className="mt-2 text-xs leading-5 text-slate-500">Select up to 12 saved passages from this interview. Candidate speech can support findings; interviewer speech provides context only. Unclear transcription remains unverified. Selected sources are fixed when assessment starts.</p><button className={`${exerciseButton} mt-3`} disabled={busy || discussionCursor === null} onClick={() => void perform(async () => { const value = await transcriptionApi.history(interviewId, discussionCursor || undefined); setDiscussion(prev => [...prev, ...value.segments]); setDiscussionCursor(value.next_cursor); })}>{discussion.length ? "Load more passages" : "Load saved passages"}</button><div className="mt-3 max-h-64 space-y-2 overflow-auto">{discussion.map(line => <label key={line.id} className="flex items-start gap-2 rounded-lg bg-slate-50 p-3 text-xs leading-5"><input type="checkbox" className="mt-1" checked={selectedDiscussion.includes(line.id!)} disabled={!selectedDiscussion.includes(line.id!) && selectedDiscussion.length >= 12} onChange={e => setSelectedDiscussion(prev => e.target.checked ? [...prev, line.id!] : prev.filter(id => id !== line.id))} /><span><strong className="font-medium text-slate-700">{line.speaker === "CANDIDATE" ? "Candidate" : "Interviewer"} · {transcriptTime(line.start_offset_ms)}</strong><br />{line.text}</span></label>)}</div>{discussionCursor === null && !discussion.length ? <p className="mt-2 text-xs text-slate-500">No saved discussion passages are available.</p> : null}</details> : null}
        {exerciseFinished(attempt.status) ? <div className="flex flex-wrap gap-2">{!assessment || assessment.status === "failed" ? <button className={exercisePrimary} disabled={busy} onClick={() => void perform(async () => accept(await workSampleApi.assess(interviewId, selectedDiscussion)))}>{assessment ? "Retry assessment" : "Assess exercise"}</button> : null}{!closed && attempt.number < 5 ? <button className={exerciseButton} disabled={busy} onClick={() => setConfirmRetry(true)}>Allow another attempt</button> : null}</div> : null}
        {assessment ? <WorkSampleReview key={`${assessment.id}-${assessment.status}`} assessment={assessment} task={exercise.task} busy={busy} onApprove={(result, reviewReason) => void perform(async () => accept(await workSampleApi.review(interviewId, assessment.id, result, reviewReason)))} /> : null}
        {(exercise.attempts?.length ?? 0) > 1 ? <details className="rounded-xl border border-slate-200 p-4"><summary className="cursor-pointer text-sm font-medium text-indigo-700">Previous attempts</summary>{exercise.attempts?.filter(a => a.id !== attempt.id).map(a => <section key={a.id} className="mt-4"><h4 className="text-sm font-semibold">Attempt {a.number} · {exerciseLabel(a.status)}</h4><pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-50 p-3 text-xs leading-6">{a.content}</pre><p className="mt-2 whitespace-pre-wrap text-xs text-slate-600">{a.explanation}</p>{exercise.assessments?.filter(s => s.attempt_id === a.id).map(s => <WorkSampleReview key={`${s.id}-${s.status}`} assessment={s} task={exercise.task} busy={busy} onApprove={(result, reviewReason) => void perform(async () => accept(await workSampleApi.review(interviewId, s.id, result, reviewReason)))} />)}</section>)}</details> : null}
      </> : null}
      <details className="border-t border-slate-100 pt-4"><summary className="cursor-pointer text-xs text-slate-500">Exercise activity</summary><ul className="mt-3 space-y-2">{exercise.events?.map((event, i) => <li key={i} className="text-xs leading-5 text-slate-500"><span className="font-medium text-slate-700">{exerciseLabel(event.kind)}</span> · {new Date(event.at).toLocaleString()} · {event.actor}{event.reason ? <p>{event.reason}</p> : null}</li>)}</ul></details>
    </> : <p className="rounded-xl bg-slate-50 p-4 text-sm text-slate-500">No practical exercise was saved for this interview, or its retention period has ended.</p>}
    {confirmShare ? <PreviewModal title="Approve and share this task?" onClose={() => setConfirmShare(false)} busy={busy}><p className="text-sm leading-6 text-slate-600">The candidate will see these instructions, materials and criteria. They cannot be edited after sharing. The timer starts only after the candidate is ready and you click Start.</p><div className="mt-5 flex justify-end gap-2"><button className={exerciseButton} disabled={busy} onClick={() => setConfirmShare(false)}>Cancel</button><button className={exercisePrimary} disabled={busy} onClick={() => void perform(async () => { const saved = await workSampleApi.save(interviewId, task, editVersion.current); accept(saved, true); const shared = await workSampleApi.action(interviewId, saved.exercise!.version, "share"); accept(shared, true); setConfirmShare(false); })}>Approve & share</button></div></PreviewModal> : null}
    {confirmRetry ? <PreviewModal title="Allow another attempt?" onClose={() => setConfirmRetry(false)} busy={busy}><p className="text-sm leading-6 text-slate-600">The previous submission and assessment remain unchanged. A new attempt starts with a copy of the saved work and waits for candidate readiness.</p><label className="mt-3 block text-sm">Reason<input className={exerciseInput} value={reason} maxLength={1000} onChange={e => setReason(e.target.value)} /></label><div className="mt-5 flex justify-end gap-2"><button className={exerciseButton} onClick={() => setConfirmRetry(false)}>Cancel</button><button className={exercisePrimary} disabled={busy || reason.trim().length < 5} onClick={() => { setConfirmRetry(false); void action("retry"); }}>Create new attempt</button></div></PreviewModal> : null}
  </section>;
}
