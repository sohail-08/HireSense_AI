import { useEffect, useRef, useState } from "react";
import { ApiError } from "../../api/apiClient";
import { PreviewModal } from "../common/PreviewModal";
import { workSampleApi, exerciseFinished, exerciseLabel, type ExerciseState } from "./workSampleApi";
import { ExerciseClock, ExerciseInstructions, exerciseButton, exerciseInput, exercisePrimary } from "./WorkSampleShared";

export function CandidateWorkSample({ closed = false }: { closed?: boolean }) {
  const [state, setState] = useState<ExerciseState>(), [content, setContent] = useState("");
  const [saveStatus, setSaveStatus] = useState("Saved"), [error, setError] = useState("");
  const [saving, setSaving] = useState(false), [blocked, setBlocked] = useState(false), [readyBusy, setReadyBusy] = useState(false);
  const [confirmSubmit, setConfirmSubmit] = useState(false), [confirmReload, setConfirmReload] = useState(false);
  const draft = useRef({ content: "", dirty: false, revision: 0, id: 0 });
  const saveLock = useRef(false), mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    const warn = (event: BeforeUnloadEvent) => { if (draft.current.dirty) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("beforeunload", warn);
    return () => { mounted.current = false; window.removeEventListener("beforeunload", warn); };
  }, []);
  const accept = (value: ExerciseState) => {
    const submission = value.exercise?.attempt;
    if (submission && submission.id === draft.current.id && submission.revision < draft.current.revision) return;
    if (submission && !draft.current.dirty && !saveLock.current) {
      draft.current = { id: submission.id, content: submission.content, dirty: false, revision: submission.revision };
      setContent(submission.content);
    }
    setState(value);
  };
  useEffect(() => {
    if (closed) return;
    let active = true, polling = false;
    const refresh = async () => {
      if (polling || saveLock.current) return;
      polling = true;
      try { const value = await workSampleApi.candidateRead(); if (active) accept(value); }
      catch (e) { if (active) setError(e instanceof Error ? e.message : "Exercise status is unavailable."); }
      finally { polling = false; }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, [closed]);
  const submission = state?.exercise?.attempt;
  const running = !closed && submission?.status === "running";
  async function save(submit = false) {
    if (saveLock.current || blocked || !running || (!submit && !draft.current.dirty)) return;
    const sent = { ...draft.current };
    saveLock.current = true; setSaving(true); setSaveStatus("Saving…"); setError("");
    try {
      const value = await workSampleApi.candidateSave(sent.id, sent.revision, sent.content, submit);
      if (!mounted.current) return;
      const saved = value.exercise?.attempt;
      if (saved?.id === draft.current.id) {
        draft.current.revision = saved.revision;
        draft.current.dirty = draft.current.content !== sent.content;
        setSaveStatus(submit ? "Submission received" : draft.current.dirty ? "Unsaved changes" : "Saved");
      }
      setState(value);
      if (submit) setConfirmSubmit(false);
    } catch (e) {
      if (!mounted.current) return;
      setSaveStatus("Not saved"); setError(e instanceof Error ? e.message : "Save failed. Keep this page open and retry.");
      if (e instanceof ApiError && [401, 403, 409, 410].includes(e.status)) {
        setBlocked(true);
        if (e.status === 409) try {
          const value = await workSampleApi.candidateRead();
          if (mounted.current) {
            accept(value);
            const current = value.exercise?.attempt;
            if (current?.id === sent.id && current.revision === sent.revision && ["running", "paused"].includes(current.status)) setBlocked(false);
          }
        } catch { /* Preserve local work until explicit recovery. */ }
      }
    } finally { saveLock.current = false; if (mounted.current) setSaving(false); }
  }
  useEffect(() => {
    if (!draft.current.dirty || !running || blocked || saving || confirmSubmit) return;
    const timer = window.setTimeout(() => void save(), 1200);
    return () => window.clearTimeout(timer);
  }, [content, running, blocked, saving, confirmSubmit]);
  async function reloadSaved() {
    try {
      const value = await workSampleApi.candidateRead();
      draft.current.dirty = false; setBlocked(false); setError(""); setSaveStatus("Saved"); accept(value);
    } catch (e) { setError(e instanceof Error ? e.message : "Saved work is unavailable."); }
  }
  if (!state?.exercise && !error) return null;
  const exercise = state?.exercise;
  return <section aria-label="Your practical exercise" className="min-w-0 overflow-hidden rounded-2xl border border-indigo-100 bg-white shadow-sm">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-indigo-100 bg-indigo-50/40 px-5 py-4"><div><p className="text-xs font-semibold uppercase tracking-wider text-indigo-700">Live practical task</p><h2 className="mt-1 text-lg font-bold text-slate-900">Your workspace</h2></div><div className="flex flex-wrap items-center gap-2">{exercise ? <span className="text-xs font-medium text-indigo-700">{closed ? "Interview access closed" : exerciseLabel(exercise.status)}</span> : null}{state && !closed ? <ExerciseClock state={state} /> : null}</div></header>
    <div className="space-y-5 p-5">
      {error ? <p role="alert" className="rounded-xl bg-amber-50 p-3 text-sm leading-6 text-amber-900">{error}</p> : null}
      {closed ? <p role="status" className="rounded-xl bg-amber-50 p-3 text-sm leading-6 text-amber-900">Interview access is closed. Your last server-saved work is preserved. Any unsaved text remains visible here so you can copy it.</p> : null}
      {exercise ? <><ExerciseInstructions task={exercise.task} /><p className="text-xs text-slate-500">One submission only. The interviewer will ask about your approach verbally.</p>
        {submission && ["shared", "ready"].includes(submission.status) ? <div className="rounded-xl bg-indigo-50 p-4"><p className="text-sm leading-6 text-indigo-900">Read the task and ask any clarification questions. Your working time has not begun.</p><button className={`${exercisePrimary} mt-3`} disabled={closed || readyBusy || submission.status === "ready"} onClick={() => { setReadyBusy(true); void workSampleApi.ready(submission.id).then(accept).catch(e => setError(e instanceof Error ? e.message : "Could not mark ready.")).finally(() => setReadyBusy(false)); }}>{submission.status === "ready" ? "Ready · waiting for interviewer" : "I’m ready"}</button></div> : null}
        {submission && !["shared", "ready"].includes(submission.status) ? <>
          <div className="flex justify-end"><span role="status" aria-live="polite" className={`text-xs font-medium ${saveStatus === "Saved" || saveStatus === "Submission received" ? "text-emerald-700" : "text-amber-800"}`}>{saveStatus}</span></div>
          <label className="block text-sm font-medium text-slate-700">{exercise.task.response_type === "code" ? "Your code" : "Your response"}<textarea className={`${exerciseInput} min-h-64 ${exercise.task.response_type === "code" ? "font-mono" : ""}`} rows={12} maxLength={50000} spellCheck={exercise.task.response_type !== "code"} readOnly={!running || blocked || confirmSubmit} value={content} onChange={e => { draft.current.content = e.target.value; draft.current.dirty = true; setContent(e.target.value); setSaveStatus("Unsaved changes"); }} /></label>
          {submission.status === "paused" ? <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900">The interviewer paused the exercise. Your work is preserved; editing resumes when they restart the timer.</p> : null}
          {exerciseFinished(submission.status) ? <div className="rounded-xl bg-teal-50 p-4"><h3 className="text-sm font-semibold text-teal-900">{submission.status === "submitted" ? "Submission received" : "Your saved work was preserved"}</h3><p className="mt-1 text-sm leading-6 text-teal-800">{submission.status === "submitted" ? "Your response is locked. Discuss your approach with the interviewer." : "The working period ended. The latest saved draft was preserved, not marked as a confirmed submission."}</p>{draft.current.dirty ? <p className="mt-2 text-sm font-medium text-amber-900">Some text here was not saved before the exercise stopped. Keep a copy and tell the interviewer.</p> : null}</div> : null}
          {running ? <div className="flex flex-wrap items-center justify-between gap-3"><p className="text-xs text-slate-500">Work saves automatically while connected.</p><div className="flex gap-2"><button className={exerciseButton} disabled={saving || blocked || !draft.current.dirty} onClick={() => void save()}>Save now</button><button className={exercisePrimary} disabled={saving || blocked} onClick={() => setConfirmSubmit(true)}>Submit exercise</button></div></div> : null}
          {blocked ? <div><p className="text-xs text-amber-800">Copy unsaved changes before loading the server version.</p><button className={`${exerciseButton} mt-2`} disabled={saving} onClick={() => setConfirmReload(true)}>Load saved version</button></div> : null}
        </> : null}
      </> : null}
    </div>
    {confirmSubmit ? <PreviewModal title="Submit your exercise?" busy={saving} onClose={() => setConfirmSubmit(false)}><p className="text-sm leading-6 text-slate-600">Your current response will be saved and locked. You have one submission and cannot try again.</p><div className="mt-5 flex justify-end gap-2"><button className={exerciseButton} disabled={saving} onClick={() => setConfirmSubmit(false)}>Keep working</button><button className={exercisePrimary} disabled={saving || !running || blocked} onClick={() => void save(true)}>{saving ? "Submitting…" : "Confirm submission"}</button></div></PreviewModal> : null}
    {confirmReload ? <PreviewModal title="Load the saved version?" onClose={() => setConfirmReload(false)}><p className="text-sm leading-6 text-slate-600">This replaces the text shown here. Copy your unsaved changes first.</p><div className="mt-5 flex justify-end gap-2"><button className={exerciseButton} onClick={() => setConfirmReload(false)}>Keep local text</button><button className={exercisePrimary} onClick={() => { setConfirmReload(false); void reloadSaved(); }}>Load saved version</button></div></PreviewModal> : null}
  </section>;
}
