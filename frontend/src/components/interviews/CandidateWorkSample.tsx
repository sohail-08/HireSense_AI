import { useEffect, useRef, useState } from "react";
import { ApiError } from "../../api/apiClient";
import { PreviewModal } from "../common/PreviewModal";
import { workSampleApi, exerciseFinished, exerciseLabel, type ExerciseState } from "./workSampleApi";
import { ExerciseClock, ExerciseInstructions, exerciseButton, exerciseInput, exercisePrimary } from "./WorkSampleShared";

export function CandidateWorkSample({ closed = false }: { closed?: boolean }) {
  const [state, setState] = useState<ExerciseState>();
  const [content, setContent] = useState("");
  const [explanation, setExplanation] = useState("");
  const [saveStatus, setSaveStatus] = useState("Saved");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [confirmSubmit, setConfirmSubmit] = useState(false);
  const [readyBusy, setReadyBusy] = useState(false);
  const [recoveredDraft, setRecoveredDraft] = useState<{ content: string; explanation: string }>();
  const draft = useRef({ content: "", explanation: "", dirty: false, revision: 0, attemptId: 0 });
  const saveLock = useRef(false), mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    const beforeUnload = (event: BeforeUnloadEvent) => { if (draft.current.dirty) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("beforeunload", beforeUnload);
    return () => { mounted.current = false; window.removeEventListener("beforeunload", beforeUnload); };
  }, []);
  const accept = (value: ExerciseState) => {
    const attempt = value.exercise?.attempt;
    if (attempt && attempt.id === draft.current.attemptId && attempt.revision < draft.current.revision) return;
    if (attempt && attempt.id !== draft.current.attemptId) {
      if (draft.current.dirty) setRecoveredDraft({ content: draft.current.content, explanation: draft.current.explanation });
      // A new attempt is explicitly authorized by the interviewer, never an overwrite of the old submission.
      draft.current = { content: attempt.content, explanation: attempt.explanation, dirty: false, revision: attempt.revision, attemptId: attempt.id };
      setContent(attempt.content); setExplanation(attempt.explanation); setSaveStatus("Saved"); setBlocked(false); setError("");
    } else if (attempt && !draft.current.dirty && !saveLock.current) {
      draft.current = { ...draft.current, content: attempt.content, explanation: attempt.explanation, revision: attempt.revision };
      setContent(attempt.content); setExplanation(attempt.explanation);
    }
    setState(value);
  };
  useEffect(() => {
    if (closed) return;
    let alive = true, polling = false;
    async function refresh() {
      if (polling || saveLock.current) return;
      polling = true;
      try { const value = await workSampleApi.candidateRead(); if (alive) accept(value); }
      catch (e) { if (alive) setError(e instanceof Error ? e.message : "Exercise status is unavailable. Your unsaved work remains here."); }
      finally { polling = false; }
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [closed]);
  const attempt = state?.exercise?.attempt;
  async function save(submit = false) {
    if (saveLock.current || blocked || closed || !attempt || attempt.status !== "running") return;
    if (!submit && !draft.current.dirty) return;
    const sent = { ...draft.current };
    saveLock.current = true; setSaving(true); setSaveStatus("Saving…"); setError("");
    try {
      const value = await workSampleApi.candidateSave(sent.attemptId, sent.revision, sent.content, sent.explanation, submit);
      if (!mounted.current) return;
      const saved = value.exercise?.attempt;
      if (saved && saved.id === draft.current.attemptId) {
        draft.current.revision = saved.revision;
        draft.current.dirty = draft.current.content !== sent.content || draft.current.explanation !== sent.explanation;
        setSaveStatus(submit ? "Submission received" : draft.current.dirty ? "Unsaved changes" : "Saved");
      }
      setState(value);
      if (submit) setConfirmSubmit(false);
    } catch (e) {
      if (mounted.current) {
        setSaveStatus("Not saved"); setError(e instanceof Error ? e.message : "Save failed. Keep this page open and retry.");
        if (e instanceof ApiError && [401, 403, 409, 410].includes(e.status)) {
          setBlocked(true);
          if (e.status === 409) {
            try {
              const value = await workSampleApi.candidateRead();
              if (mounted.current) {
                accept(value);
                const current = value.exercise?.attempt;
                // A pause is not a competing writer. Keep local text for resumption.
                if (current?.id === sent.attemptId && current.revision === sent.revision && ["running", "paused"].includes(current.status)) setBlocked(false);
              }
            } catch { /* Keep local text and require explicit recovery if status is unavailable. */ }
          }
        }
      }
    } finally { saveLock.current = false; if (mounted.current) setSaving(false); }
  }
  useEffect(() => {
    if (!draft.current.dirty || attempt?.status !== "running" || blocked || closed || saving || confirmSubmit) return;
    const timer = window.setTimeout(() => void save(), 1200);
    return () => window.clearTimeout(timer);
  }, [content, explanation, attempt?.status, blocked, closed, saving, confirmSubmit]);
  async function reloadSaved() {
    try {
      const value = await workSampleApi.candidateRead();
      draft.current.dirty = false; setBlocked(false); setError(""); setSaveStatus("Saved"); accept(value);
    } catch (e) { setError(e instanceof Error ? e.message : "Saved work is unavailable."); }
  }
  const [confirmReload, setConfirmReload] = useState(false);
  if (!state?.exercise && !error) return null;
  const exercise = state?.exercise;
  const running = !closed && attempt?.status === "running";
  const unsaved = draft.current.dirty;
  return <section aria-label="Your practical exercise" className="min-w-0 overflow-hidden rounded-2xl border border-indigo-100 bg-white shadow-sm">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-indigo-100 bg-indigo-50/40 px-5 py-4"><div><p className="text-xs font-semibold uppercase tracking-wider text-indigo-700">Live practical exercise</p><h2 className="mt-1 text-lg font-bold text-slate-900">Your workspace</h2></div><div className="flex flex-wrap items-center gap-2">{exercise ? <span className="text-xs font-medium text-indigo-700">{closed ? "Interview access closed" : exerciseLabel(exercise.status)}</span> : null}{state && !closed ? <ExerciseClock state={state} /> : null}</div></header>
    <div className="space-y-5 p-5">
      {error ? <p role="alert" className="rounded-xl bg-amber-50 p-3 text-sm leading-6 text-amber-900">{error}</p> : null}
      {closed ? <p role="status" className="rounded-xl bg-amber-50 p-3 text-sm leading-6 text-amber-900">Interview access is closed. Your last server-saved work is preserved. Any unsaved text remains visible here so you can copy it.</p> : null}
      {recoveredDraft ? <details className="rounded-xl border border-amber-200 bg-amber-50 p-3"><summary className="cursor-pointer text-sm font-semibold text-amber-900">Unsaved text from your previous attempt</summary><p className="mt-2 text-xs text-amber-800">This local copy was not submitted. Copy it before leaving or reloading.</p><pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-xs">{recoveredDraft.content}{"\n\n"}{recoveredDraft.explanation}</pre></details> : null}
      {exercise ? <>
        <ExerciseInstructions task={exercise.task} />
        {attempt?.status === "shared" || attempt?.status === "ready" ? <div className="rounded-xl bg-indigo-50 p-4"><p className="text-sm leading-6 text-indigo-900">Read the task and ask any clarification questions before you start. Your working time has not begun.</p><button className={`${exercisePrimary} mt-3`} disabled={closed || readyBusy || attempt.status === "ready"} onClick={() => { setReadyBusy(true); void workSampleApi.ready(attempt.id).then(accept).catch(e => setError(e instanceof Error ? e.message : "Could not mark ready.")).finally(() => setReadyBusy(false)); }}>{attempt.status === "ready" ? "Ready · waiting for interviewer" : "I’m ready"}</button></div> : null}
        {attempt && !["shared", "ready"].includes(attempt.status) ? <>
          <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold text-slate-800">Attempt {attempt.number}</h3><span role="status" aria-live="polite" className={`text-xs font-medium ${saveStatus === "Saved" || saveStatus === "Submission received" ? "text-emerald-700" : "text-amber-800"}`}>{saveStatus}</span></div>
          <label className="block text-sm font-medium text-slate-700">{exercise.task.response_type === "code" ? "Your code" : "Your response"}<textarea className={`${exerciseInput} min-h-64 ${exercise.task.response_type === "code" ? "font-mono" : ""}`} rows={12} maxLength={50000} spellCheck={exercise.task.response_type !== "code"} readOnly={!running || blocked || confirmSubmit} value={content} onChange={e => { const value = e.target.value; draft.current.content = value; draft.current.dirty = true; setContent(value); setSaveStatus("Unsaved changes"); }} /></label>
          <label className="block text-sm font-medium text-slate-700">Explain your approach<textarea className={exerciseInput} rows={4} maxLength={10000} readOnly={!running || blocked || confirmSubmit} value={explanation} onChange={e => { const value = e.target.value; draft.current.explanation = value; draft.current.dirty = true; setExplanation(value); setSaveStatus("Unsaved changes"); }} /></label>
          {attempt.status === "paused" ? <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900">The interviewer paused the exercise. Your work is preserved; editing resumes when they restart the timer.</p> : null}
          {exerciseFinished(attempt.status) ? <div className="rounded-xl bg-teal-50 p-4"><h3 className="text-sm font-semibold text-teal-900">{attempt.status === "submitted" ? "Submission received" : "Your saved work was preserved"}</h3><p className="mt-1 text-sm leading-6 text-teal-800">{attempt.status === "submitted" ? "Your submitted version is locked. Discuss your approach with the interviewer." : "The working period ended. The latest server-saved draft was preserved; it was not marked as a confirmed submission."}</p>{unsaved ? <p className="mt-2 text-sm font-medium text-amber-900">Some text here was not saved before the exercise stopped. Keep a copy and tell the interviewer.</p> : null}</div> : null}
          {running ? <div className="flex flex-wrap items-center justify-between gap-3"><p className="text-xs text-slate-500">Work saves automatically while this page is connected.</p><div className="flex gap-2"><button className={exerciseButton} disabled={saving || blocked || !unsaved} onClick={() => void save()}>Save now</button><button className={exercisePrimary} disabled={saving || blocked} onClick={() => setConfirmSubmit(true)}>Submit exercise</button></div></div> : null}
          {blocked ? <div><p className="text-xs leading-5 text-amber-800">Your local text is still visible. Copy any unsaved changes before loading the server version.</p><button className={`${exerciseButton} mt-2`} disabled={saving} onClick={() => setConfirmReload(true)}>Load saved version</button></div> : null}
        </> : null}
      </> : null}
    </div>
    {confirmSubmit ? <PreviewModal title="Submit your exercise?" busy={saving} onClose={() => setConfirmSubmit(false)}><p className="text-sm leading-6 text-slate-600">Your current response and explanation will be saved together and locked. You can discuss your work with the interviewer afterward.</p><div className="mt-5 flex justify-end gap-2"><button className={exerciseButton} disabled={saving} onClick={() => setConfirmSubmit(false)}>Keep working</button><button className={exercisePrimary} disabled={saving || !running || blocked} onClick={() => void save(true)}>{saving ? "Submitting…" : "Confirm submission"}</button></div></PreviewModal> : null}
    {confirmReload ? <PreviewModal title="Load the saved version?" onClose={() => setConfirmReload(false)}><p className="text-sm leading-6 text-slate-600">This replaces the text shown here with the server-saved version. Copy your unsaved changes first.</p><div className="mt-5 flex justify-end gap-2"><button className={exerciseButton} onClick={() => setConfirmReload(false)}>Keep local text</button><button className={exercisePrimary} onClick={() => { setConfirmReload(false); void reloadSaved(); }}>Load saved version</button></div></PreviewModal> : null}
  </section>;
}
