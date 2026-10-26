import { useEffect, useRef, useState } from "react";
import { apiRequest } from "../../api/apiClient";
import { TranscriptCitation } from "./TranscriptCitation";
import type { Citation } from "./analysisApi";
import { MeetingTabs } from "./MeetingTabs";
import { IdentityOverview } from "./IdentityOverview";
import { CandidatePhoto } from "./CandidatePhoto";
import { displayPercent } from "../candidates/scoringDisplay";
import { AssistantBubble, AssistantComposer, AssistantIdentity, AssistantWorking, assistantChatStyles } from "../assistant/AssistantChatUI";

type Question = { question: string; requirement: string; source_ids: number[] };
type Message = { role: "user" | "assistant"; content: string; questions: Question[];
  task_options?: { id: string; title: string; summary: string; duration_minutes: number; response_type: string }[]; task_created?: boolean;
  sources: { chunk_id: number; document_title: string; excerpt: string }[]; analysis_citations?: Citation[]; analysis_run_id?: number };
export type CopilotContext = {
  open_practical_exercise?: boolean;
  candidate: { name: string; email: string | null; phone: string | null; location: string | null;
    skills: string[]; qualifications: string[]; experience_years: number | null; recent_roles: string[];
    cv_score?: string | null; probe_areas?: { name: string; reason: string; source: string; screening_run_id: number }[] };
  job_title: string; required_skills: string[]; preferred_skills: string[]; qualifications: string[];
  minimum_experience: number | null; selection_criteria: string[]; messages: Message[]; version: number;
};

export function InterviewCopilotPanel({ interviewId, fill = false, pageScroll = false, activeTab, onTabChange, onOpenPractical, onOpenAnalysis }: { interviewId: number; fill?: boolean; pageScroll?: boolean; activeTab?: string; onTabChange?: (id: string) => void; onOpenPractical?: () => void; onOpenAnalysis?: () => void }) {
  const [context, setContext] = useState<CopilotContext>();
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const lock = useRef(false);
  const history = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let active = true;
    setContext(undefined); setError(undefined);
    apiRequest<CopilotContext>(`/interview-rooms/${interviewId}/copilot`)
      .then((value) => { if (active) setContext(value); })
      .catch((failure) => { if (active) setError(failure instanceof Error ? failure.message : "Could not load candidate information."); });
    return () => { active = false; };
  }, [interviewId, attempt]);
  useEffect(() => { history.current?.scrollTo?.({ top: history.current.scrollHeight, behavior: "smooth" }); }, [context?.messages.length, busy]);

  async function send(text: string, selectedTaskId?: string) {
    if (!context || !text.trim() || lock.current) return;
    lock.current = true; setBusy(true); setError(undefined);
    try {
      const result = await apiRequest<CopilotContext>(`/interview-rooms/${interviewId}/copilot`, {
        method: "POST", body: JSON.stringify({ message: text.trim(), version: context.version, ...(selectedTaskId ? { selected_task_id: selectedTaskId } : {}) }),
      });
      setContext(result); setMessage("");
      if (result.open_practical_exercise) onOpenPractical?.();
      else if (result.messages.at(-1)?.analysis_run_id) onOpenAnalysis?.();
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Could not suggest questions. Please retry."); }
    finally { lock.current = false; setBusy(false); }
  }
  if (!context) return <aside aria-label="Private interview assistance" data-loading="true" className={`rounded-2xl bg-white p-5 shadow-sm ${fill ? "hiresense-private-panel" : ""}`}>
    {error ? <><p role="alert" className="text-red-700">{error}</p><button className="mt-3 text-blue-700" onClick={() => setAttempt((value) => value + 1)}>Reload candidate information</button></> : <p role="status">Loading candidate information…</p>}
  </aside>;
  const candidate = context.candidate;
  const candidateInfo = <section className="min-w-0 break-words p-5">
      <h2 className="text-sm font-semibold text-slate-500">Candidate information</h2>
      <div role="group" aria-label="Candidate profile" className="mt-5 flex flex-col items-center gap-4 pb-5 text-center"><CandidatePhoto interviewId={interviewId} name={candidate.name} /><div className="min-w-0 max-w-full"><h3 className="break-words text-xl font-bold text-slate-900">{candidate.name}</h3>
      <p className="mt-1 text-sm text-slate-600">{context.job_title}</p>
      </div></div>
      <IdentityOverview interviewId={interviewId} />
      {candidate.cv_score != null ? <p className="mt-4 rounded-xl bg-teal-50 p-3 text-sm text-teal-900">Saved CV score <strong className="float-right">{displayPercent(candidate.cv_score)}</strong></p> : null}
      {candidate.probe_areas?.length ? <section aria-label="Areas to explore" className="mt-4"><h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Areas to explore</h3><ul className="mt-2 space-y-2">{candidate.probe_areas.map((item, index) => <li key={index} className="rounded-xl border border-amber-100 bg-amber-50/50 p-3 text-sm"><p className="font-medium text-slate-700">{item.name}</p><details className="mt-1 text-xs text-slate-500"><summary className="cursor-pointer">Why explore this?</summary><p className="mt-1 leading-5">{item.reason}</p><p className="mt-1">{item.source}</p></details></li>)}</ul></section> : null}
      <dl className="mt-5 space-y-3 break-words text-sm">
        <div><dt className="text-xs text-slate-400">Email</dt><dd className="mt-1 font-medium">{candidate.email || "Not provided"}</dd></div>
        <div><dt className="text-xs text-slate-400">Phone</dt><dd className="mt-1 font-medium">{candidate.phone || "Not provided"}</dd></div>
        {candidate.location ? <div><dt className="text-slate-500">Location</dt><dd>{candidate.location}</dd></div> : null}
      </dl>
      <details className="mt-5 border-t border-slate-100 pt-4" open>
        <summary className="cursor-pointer font-semibold">CV highlights</summary>
        <p className="mt-2 text-xs text-slate-400">From the candidate’s saved CV.</p>
        <p className="mt-3 rounded-xl bg-slate-50 p-3 text-sm font-medium">Experience: {candidate.experience_years == null ? "Not available" : `${candidate.experience_years} years`}</p>
        <div className="mt-3 flex flex-wrap gap-2">{candidate.skills.length ? candidate.skills.map((skill, index) => <span key={index} className="max-w-full rounded-lg bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700">{skill}</span>) : <p className="text-sm text-slate-500">Skills are not available yet.</p>}</div>
        {candidate.qualifications.map((value, index) => <p className="mt-2 text-sm" key={index}>{value}</p>)}
        {candidate.recent_roles.map((value, index) => <p className="mt-2 text-sm text-slate-600" key={index}>{value}</p>)}
      </details>
      <details className="mt-5 overflow-hidden rounded-2xl border border-blue-100 bg-gradient-to-br from-blue-50/70 to-white">
        <summary className="flex cursor-pointer items-center gap-3 p-4 font-semibold text-slate-800"><span className="rounded-xl border border-blue-100 bg-white p-2 text-blue-600"><svg aria-hidden="true" className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="3" y="7" width="18" height="14" rx="3"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12a22 22 0 0 0 18 0M12 11v4"/></svg></span><span className="flex-1">Job requirements<span className="mt-0.5 block text-xs font-normal text-slate-500">What to look for during this interview</span></span><span aria-hidden="true" className="text-blue-500">⌄</span></summary>
        <div className="space-y-4 border-t border-blue-100/70 p-4">
          <div className="flex items-center justify-between gap-3 rounded-xl border border-blue-100 bg-white p-3"><p className="text-xs font-semibold text-slate-500">Minimum experience</p><p className="shrink-0 rounded-lg bg-blue-50 px-2.5 py-1 text-sm font-bold text-blue-700">{context.minimum_experience == null ? "Not specified" : `${context.minimum_experience}+ years`}</p></div>
          <section aria-label="Required skills"><h4 className="text-xs font-bold uppercase tracking-wide text-slate-500">Required skills</h4><div className="mt-2 flex flex-wrap gap-1.5">{context.required_skills.length ? context.required_skills.map((skill, index) => <span key={index} className="max-w-full rounded-lg border border-blue-100 bg-white px-2.5 py-1.5 text-xs font-medium text-blue-700">{skill}</span>) : <p className="text-sm text-slate-500">No required skills listed.</p>}</div></section>
          {context.preferred_skills.length ? <section aria-label="Preferred skills"><h4 className="text-xs font-bold uppercase tracking-wide text-slate-500">Nice to have</h4><div className="mt-2 flex flex-wrap gap-1.5">{context.preferred_skills.map((skill, index) => <span key={index} className="max-w-full rounded-lg border border-violet-100 bg-violet-50 px-2.5 py-1.5 text-xs font-medium text-violet-700">{skill}</span>)}</div></section> : null}
          <section aria-label="Qualifications"><h4 className="text-xs font-bold uppercase tracking-wide text-slate-500">Education & qualifications</h4>{context.qualifications.length ? <ul className="mt-2 space-y-2">{context.qualifications.map((qualification, index) => <li key={index} className="flex items-start gap-2 rounded-xl bg-white p-3 text-sm text-slate-700"><span aria-hidden="true" className="mt-0.5 text-blue-500">✓</span>{qualification}</li>)}</ul> : <p className="mt-2 text-sm text-slate-500">No qualifications listed.</p>}</section>
          {context.selection_criteria.length ? <section aria-label="Selection criteria"><h4 className="text-xs font-bold uppercase tracking-wide text-slate-500">Selection criteria</h4><ul className="mt-2 space-y-2">{context.selection_criteria.map((criterion, index) => <li key={index} className="flex items-start gap-2 text-sm leading-6 text-slate-600"><span aria-hidden="true" className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-400"/>{criterion}</li>)}</ul></section> : null}
        </div>
      </details>
    </section>;
  const assistant = <section aria-label="Interview assistant" className="hiresense-interview-assistant flex min-w-0 flex-col">
      <header className={assistantChatStyles.header}><div className="flex items-center gap-2.5"><AssistantIdentity subtitle="Private interview support" /></div></header>
      <div ref={history} role="log" aria-label="Interview assistant conversation" aria-live="polite" className={`h-[25rem] max-h-[60svh] min-h-48 ${assistantChatStyles.conversation}`}>
        {!context.messages.length ? <AssistantBubble role="assistant"><p>Ask for interview questions, short practical tasks, or insights from this interview.</p><button type="button" disabled={busy} className="mt-3 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-semibold text-blue-700 transition hover:bg-blue-100 focus-visible:outline-2 focus-visible:outline-blue-600 disabled:opacity-50" onClick={() => void send("Suggest 3 interview questions relevant to this job description.")}>Suggest questions</button></AssistantBubble> : null}
        {context.messages.map((item, index) => <AssistantBubble key={index} role={item.role} label={item.role === "user" ? "Your message" : "Assistant reply"}>
          <p className="whitespace-pre-wrap break-words leading-6">{item.content}</p>
          {item.task_options?.length ? <div className="mt-3 space-y-2">{item.task_options.map(option => <section className="rounded-xl border border-indigo-100 bg-indigo-50/40 p-3" key={option.id}><div className="flex justify-between gap-2"><h3 className="text-sm font-semibold text-slate-800">{option.title}</h3><span className="shrink-0 text-xs font-medium text-indigo-700">{option.duration_minutes} min</span></div><p className="mt-2 text-sm leading-6 text-slate-600">{option.summary}</p><button className="mt-3 rounded-lg bg-indigo-700 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40" disabled={busy || context.messages.slice(index + 1).some(m => m.task_created)} onClick={() => void send(`Create task: ${option.title}`, option.id)}>Use this task</button></section>)}</div> : null}
          {item.task_created ? <button className="mt-3 text-sm font-semibold text-indigo-700" onClick={onOpenPractical}>Open practical exercise →</button> : null}
          {item.analysis_run_id ? item.analysis_citations?.map((citation, i) => <TranscriptCitation key={i} citation={citation} runId={item.analysis_run_id!} interviewId={interviewId} />) : null}
          {item.questions.length ? <ol className="mt-3 list-decimal space-y-3 pl-5">{item.questions.map((question, i) => <li key={i}><p className="leading-6">{question.question}</p><p className="mt-1 text-xs text-slate-500">Job requirement: {question.requirement} · Sources: {question.source_ids.map((value) => `#${value}`).join(", ")}</p></li>)}</ol> : null}
          {item.sources.length ? <details className="mt-3"><summary className="cursor-pointer text-xs font-semibold text-blue-700">Knowledge sources ({item.sources.length})</summary>{item.sources.map((source) => <blockquote key={source.chunk_id} className="mt-2 border-l-2 border-blue-200 pl-3"><p className="text-xs font-semibold">#{source.chunk_id} · {source.document_title}</p><p className="mt-1 whitespace-pre-wrap text-xs leading-5 text-slate-600">{source.excerpt}</p></blockquote>)}</details> : null}
        </AssistantBubble>)}
        {busy ? <AssistantWorking /> : null}
      </div>
      <AssistantComposer id="interview-assistant-message" label="Ask the interview assistant" value={message} onChange={setMessage} onSend={() => void send(message)} busy={busy} maxLength={2000} placeholder="Ask about this interview…" className="hiresense-assistant-composer">
        {error ? <div role="alert" className="mb-3 text-sm text-red-700">{error}<button type="button" className="ml-2 underline" disabled={busy} onClick={() => setAttempt((value) => value + 1)}>Reload conversation</button></div> : null}
      </AssistantComposer>
    </section>;
  return <aside aria-label="Private interview assistance" className={`min-w-0 ${fill ? "hiresense-private-panel" : ""}`}>
    <MeetingTabs fill={fill} pageScroll={pageScroll} activeId={activeTab} onActiveChange={onTabChange} label="Private interviewer tools" tabs={[{ id: "candidate", label: "Candidate info", content: candidateInfo }, { id: "assistant", label: "Assistant", content: assistant }]} />
  </aside>;
}
