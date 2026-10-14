import { useEffect, useRef, useState } from "react";
import { apiRequest } from "../../api/apiClient";

type Question = { question: string; requirement: string; source_ids: number[] };
type Message = { role: "user" | "assistant"; content: string; questions: Question[];
  sources: { chunk_id: number; document_title: string; excerpt: string }[] };
export type CopilotContext = {
  candidate: { name: string; email: string | null; phone: string | null; location: string | null;
    skills: string[]; qualifications: string[]; experience_years: number | null; recent_roles: string[] };
  job_title: string; required_skills: string[]; preferred_skills: string[]; qualifications: string[];
  minimum_experience: number | null; selection_criteria: string[]; messages: Message[]; version: number;
};

export function InterviewCopilotPanel({ interviewId }: { interviewId: number }) {
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

  async function send(text: string) {
    if (!context || !text.trim() || lock.current) return;
    lock.current = true; setBusy(true); setError(undefined);
    try {
      const result = await apiRequest<CopilotContext>(`/interview-rooms/${interviewId}/copilot`, {
        method: "POST", body: JSON.stringify({ message: text.trim(), version: context.version }),
      });
      setContext(result); setMessage("");
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Could not suggest questions. Please retry."); }
    finally { lock.current = false; setBusy(false); }
  }
  if (!context) return <aside aria-label="Private interview assistance" className="rounded-2xl bg-white p-5 shadow-sm">
    {error ? <><p role="alert" className="text-red-700">{error}</p><button className="mt-3 text-blue-700" onClick={() => setAttempt((value) => value + 1)}>Reload candidate information</button></> : <p role="status">Loading candidate information…</p>}
  </aside>;
  const candidate = context.candidate;
  return <aside aria-label="Private interview assistance" className="min-w-0 space-y-4">
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-lg font-bold">Candidate information</h2>
      <h3 className="mt-3 font-semibold">{candidate.name}</h3>
      <p className="text-sm text-slate-600">{context.job_title}</p>
      <dl className="mt-3 space-y-2 break-words text-sm">
        <div><dt className="text-slate-500">Email</dt><dd>{candidate.email || "Not provided"}</dd></div>
        <div><dt className="text-slate-500">Phone</dt><dd>{candidate.phone || "Not provided"}</dd></div>
        {candidate.location ? <div><dt className="text-slate-500">Location</dt><dd>{candidate.location}</dd></div> : null}
      </dl>
      <details className="mt-4 border-t pt-3" open>
        <summary className="cursor-pointer font-semibold">CV highlights</summary>
        <p className="mt-2 text-xs text-slate-500">From saved CV screening; not independently verified.</p>
        <p className="mt-2 text-sm">Experience: {candidate.experience_years == null ? "Not available" : `${candidate.experience_years} years`}</p>
        <p className="mt-2 text-sm">Skills: {candidate.skills.join(", ") || "Not available — process the CV first"}</p>
        {candidate.qualifications.map((value, index) => <p className="mt-2 text-sm" key={index}>{value}</p>)}
        {candidate.recent_roles.map((value, index) => <p className="mt-2 text-sm text-slate-600" key={index}>{value}</p>)}
      </details>
      <details className="mt-4 border-t pt-3">
        <summary className="cursor-pointer font-semibold">Job requirements</summary>
        <p className="mt-2 text-sm">Required: {context.required_skills.join(", ") || "Not specified"}</p>
        <p className="mt-2 text-sm">Preferred: {context.preferred_skills.join(", ") || "Not specified"}</p>
        <p className="mt-2 text-sm">Qualifications: {context.qualifications.join(", ") || "Not specified"}</p>
        <p className="mt-2 text-sm">Minimum experience: {context.minimum_experience == null ? "Not specified" : `${context.minimum_experience} years`}</p>
        {context.selection_criteria.length ? <p className="mt-2 text-sm">Selection criteria: {context.selection_criteria.join(", ")}</p> : null}
      </details>
    </section>
    <section aria-label="Interview assistant" className="flex flex-col rounded-2xl border border-slate-200 bg-white shadow-sm">
      <header className="border-b px-5 py-4"><h2 className="text-lg font-bold">HireSense assistant</h2><p className="mt-1 text-xs text-slate-500">Private to you · Questions grounded in the knowledge base</p></header>
      <div ref={history} role="log" aria-label="Interview assistant conversation" aria-live="polite" className="max-h-[28rem] min-h-48 space-y-4 overflow-y-auto overscroll-contain p-4">
        {!context.messages.length ? <div><p className="text-sm leading-6 text-slate-600">Ask me for questions relevant to this job, or request a more practical or challenging follow-up.</p><button disabled={busy} className="mt-3 rounded-lg border border-blue-200 px-3 py-2 text-sm font-semibold text-blue-700 disabled:opacity-50" onClick={() => void send("Suggest 3 interview questions relevant to this job description.")}>Suggest questions</button></div> : null}
        {context.messages.map((item, index) => <article key={index} className={`min-w-0 rounded-xl p-3 text-sm ${item.role === "user" ? "ml-6 bg-blue-600 text-white" : "mr-2 bg-slate-50 text-slate-800"}`}>
          <p className="mb-1 text-xs font-semibold">{item.role === "user" ? "You" : "HireSense assistant"}</p>
          <p className="whitespace-pre-wrap break-words leading-6">{item.content}</p>
          {item.questions.length ? <ol className="mt-3 list-decimal space-y-3 pl-5">{item.questions.map((question, i) => <li key={i}><p className="leading-6">{question.question}</p><p className="mt-1 text-xs text-slate-500">Job requirement: {question.requirement} · Sources: {question.source_ids.map((value) => `#${value}`).join(", ")}</p></li>)}</ol> : null}
          {item.sources.length ? <details className="mt-3"><summary className="cursor-pointer text-xs font-semibold text-blue-700">Knowledge sources ({item.sources.length})</summary>{item.sources.map((source) => <blockquote key={source.chunk_id} className="mt-2 border-l-2 border-blue-200 pl-3"><p className="text-xs font-semibold">#{source.chunk_id} · {source.document_title}</p><p className="mt-1 whitespace-pre-wrap text-xs leading-5 text-slate-600">{source.excerpt}</p></blockquote>)}</details> : null}
        </article>)}
        {busy ? <p role="status" className="text-sm text-slate-500">Searching the question bank and preparing suggestions…</p> : null}
      </div>
      <form className="border-t p-4" onSubmit={(event) => { event.preventDefault(); void send(message); }}>
        {error ? <div role="alert" className="mb-3 text-sm text-red-700">{error}<button type="button" className="ml-2 underline" disabled={busy} onClick={() => setAttempt((value) => value + 1)}>Reload conversation</button></div> : null}
        <label htmlFor="interview-assistant-message" className="sr-only">Ask the interview assistant</label>
        <textarea id="interview-assistant-message" rows={3} maxLength={2000} value={message} onChange={(event) => setMessage(event.target.value)} disabled={busy} placeholder="Suggest a practical question about the required skills…" className="w-full resize-y rounded-xl border border-slate-300 p-3 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100" />
        <div className="mt-2 flex items-center justify-between gap-2"><p className="text-xs text-slate-500">Not shared with the candidate</p><button type="submit" disabled={busy || !message.trim()} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:bg-slate-300">Send</button></div>
      </form>
    </section>
  </aside>;
}
