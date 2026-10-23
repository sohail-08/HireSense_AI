import { useCallback, useEffect, useRef, useState } from "react";
import { analysisApi, type AnalysisState } from "./analysisApi";
import { transcriptTime } from "./transcriptionApi";
import { TranscriptCitation } from "./TranscriptCitation";
import { EvidenceSummary } from "../assessments/EvidenceSummary";

const dimensions = ["relevance", "accuracy", "completeness", "quality"] as const;
const label = (text: string) => text.replaceAll("_", " ");
const button = "min-h-10 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-50 disabled:opacity-50";
const runLabel = (status: string) => ({ completed: "Ready", processing: "Analyzing…", queued: "Waiting to start", failed: "Analysis failed" }[status] || label(status));
const pairLabel = (status: string) => ({ awaiting_answer: "Waiting for an answer", answer_in_progress: "Answer in progress", unanswered: "No answer recorded", excluded: "Not scored", analysis_failed: "Could not score this answer", needs_clarification: "Wording needs verification" }[status] || "");
const scoreLabel = (status: string) => ({ met: "Met", partially_met: "Partially met", unmet: "Unmet" }[status] || "Not scored");
const scoreStyle = (status: string) => ({ met: "border-emerald-200 bg-emerald-50 text-emerald-800", partially_met: "border-amber-200 bg-amber-50 text-amber-800", unmet: "border-rose-200 bg-rose-50 text-rose-800" }[status] || "border-slate-200 bg-slate-50 text-slate-600");

// Condense known boilerplate for display, without changing saved reasons or scores.
function shortReason(reason: string) {
  const text = reason.trim();
  if (/not established by a relevant cited answer guide or technical reference/i.test(text)) return "No supporting guide or reference was available.";
  if (/available transcript evidence does not establish|available transcript and answer guide do not establish/i.test(text)) return "Not enough supporting evidence in the transcript.";
  if (/accuracy is not established by the answer guide/i.test(text)) return "The answer guide does not confirm this.";
  return text.replace(/\s*No credit is awarded for (?:unsupported evidence|missing support)\./gi, "");
}

export function InterviewAnalysisPanel({ interviewId }: { interviewId: number }) {
  const [state, setState] = useState<AnalysisState>();
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [automatic, setAutomatic] = useState(true);
  const lock = useRef(false);
  const generation = useRef(0);
  const refresh = useCallback(async () => {
    const request = ++generation.current;
    try {
      const result = await analysisApi.read(interviewId);
      if (request === generation.current) setState(result);
    } catch (e) { if (request === generation.current) setError(e instanceof Error ? e.message : "Could not load analysis."); }
  }, [interviewId]);
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, 5000);
    return () => { generation.current++; window.clearInterval(timer); };
  }, [refresh]);
  async function action(work: () => Promise<unknown>, message: string) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(""); setNotice("");
    try { await work(); setNotice(message); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : "Analysis action failed."); }
    finally { lock.current = false; setBusy(false); }
  }
  const run = state?.run;
  const segments = run?.snapshot.segments || [];
  const source = (ids: string[]) => ids.map(id => segments.find(s => s.id === id)?.text || "Source unavailable").join("\n");
  const gaps = [...new Set(run?.result.gaps || [])];
  return <section id="interview-analysis" aria-label="Private interview analysis" className="hiresense-answer-analysis mt-5 min-w-0 rounded-2xl bg-white p-5 shadow-sm">
    <header className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-lg font-bold tracking-tight text-slate-800">Answer analysis</h2>
      {run ? <span role="status" className={`rounded-full border px-2.5 py-1 text-xs font-medium ${run.status === "completed" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-slate-200 bg-slate-50 text-slate-600"}`}>{runLabel(run.status)}</span> : null}</header>
    <p className="mt-1 text-sm text-slate-500">Questions, answers and scores from the interview.</p>
    <div className="mt-4 flex flex-wrap items-center gap-3">
      <button className="min-h-10 rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50" disabled={busy || ["queued", "processing"].includes(run?.status || "")} onClick={() => void action(() => analysisApi.start(interviewId, automatic, false, run?.status === "failed" || !!run?.result.pairs?.some(pair => pair.state === "analysis_failed")), "Analysis requested. Results will update here.")}>Analyze answers</button>
      <label className="flex items-center gap-2 text-xs text-slate-600"><input type="checkbox" checked={automatic} disabled={busy} onChange={e => setAutomatic(e.target.checked)} />Update as answers arrive</label>
    </div>
    <details className="hiresense-analysis-options mt-3"><summary className="w-fit cursor-pointer text-xs font-semibold text-slate-500">Scoring options</summary><div className="mt-3 space-y-3 rounded-xl border border-slate-100 bg-slate-50/70 p-3">
      <div className="flex flex-wrap items-center gap-2">{run ? <button className={button} disabled={busy || ["queued", "processing"].includes(run.status)} onClick={() => void action(() => analysisApi.start(interviewId, automatic, false, true), "Analysis requested. Validated scores are kept when their inputs are unchanged.")}>Analyze again</button> : null}{state?.automatic ? <button className={button} disabled={busy} onClick={() => void action(async () => { await analysisApi.start(interviewId, false); setAutomatic(false); }, "Live updates stopped.")}>Stop live updates</button> : null}</div>
      <p className="text-xs leading-5 text-slate-500">Relevance, accuracy, completeness and quality each count for 25%. Met = 1, partially met = 0.5, unmet = 0.</p>
      <p className="text-xs leading-5 text-slate-500">Unclear wording or incomplete evidence checks stay unscored. An approved reference is needed for correctness; a failed check is not a zero.</p>
    </div></details>
    {error || run?.error ? <p role="alert" className="mt-3 rounded-xl bg-rose-50 p-3 text-sm text-rose-800">{error || run?.error}</p> : null}
    {notice ? <p role="status" className="mt-3 text-sm text-emerald-800">{notice}</p> : null}
    {run?.stale ? <p className="mt-3 rounded-xl border border-amber-100 bg-amber-50 p-3 text-sm text-amber-900">The transcript or reference material has changed. Update the analysis to include it.</p> : null}
    {gaps.length ? <div className="mt-3 space-y-1 rounded-xl border border-amber-100 bg-amber-50/70 p-3 text-xs leading-5 text-amber-900">{gaps.map(gap => <p key={gap}>{gap}</p>)}</div> : null}
    {!run ? <p className="mt-5 rounded-xl bg-slate-50 p-4 text-sm text-slate-500">Analyze the saved transcript to see answer scores.</p> : null}
    {run?.result.pairs ? <>
      {run.result.evidence_summary ? <EvidenceSummary value={run.result.evidence_summary} evidence={finding => <>
        {finding.citations.map((citation, i) => <TranscriptCitation key={i} citation={citation} runId={run.id} interviewId={interviewId} />)}
        {finding.references.map((ref, i) => <figure className="mt-2" key={i}><blockquote className="border-l-2 border-blue-300 pl-2">{ref.quote}</blockquote><figcaption className="mt-1 text-slate-500">{ref.title} · version {ref.version.slice(0, 12)}</figcaption></figure>)}
        <p className="mt-2 text-slate-500">{label(finding.rule)}{finding.source.requirement_id ? ` · Approved requirement ${finding.source.requirement_id} · ${finding.source.version}` : finding.source.state ? ` · ${label(finding.source.state)}` : ""}</p>
      </>} /> : null}
      <div className="mt-6 mb-3 flex items-center justify-between gap-3"><h3 className="font-semibold text-slate-800">Questions & answers</h3><span className="text-xs text-slate-500">{run.result.pairs.length} {run.result.pairs.length === 1 ? "question" : "questions"}</span></div>
      {!run.result.pairs.length ? <p className="rounded-xl bg-slate-50 p-4 text-sm text-slate-500">No interview questions were found in the saved transcript yet.</p> : null}
      <div className="space-y-3">{run.result.pairs.map((pair, index) => {
        const first = segments.find(segment => pair.question_ids.includes(segment.id));
        return <details key={pair.id} aria-label={`Question ${index + 1}`} className="hiresense-analysis-question overflow-hidden rounded-2xl border border-slate-200 bg-white" open={index === run.result.pairs!.length - 1}>
          <summary className="hiresense-analysis-question-summary cursor-pointer"><span aria-hidden="true" className="hiresense-analysis-number">{index + 1}</span><span className="min-w-0 flex-1"><span className="block whitespace-pre-wrap break-words text-sm font-semibold leading-6 text-slate-800">{source(pair.question_ids) || "Question unavailable"}</span><span className="mt-1 flex flex-wrap gap-2 text-xs text-slate-500">{first ? <span>{transcriptTime(first.start_offset_ms)}</span> : null}{pairLabel(pair.state) ? <span>{pairLabel(pair.state)}</span> : null}</span></span>
            {pair.score ? <span aria-label={`Answer score ${pair.score.percentage}%`} className="shrink-0 rounded-xl border border-blue-100 bg-blue-50 px-2.5 py-1.5 text-sm font-bold text-blue-700">{pair.score.percentage}%</span> : null}<svg aria-hidden="true" className="hiresense-analysis-chevron h-4 w-4 shrink-0 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="m6 9 6 6 6-6"/></svg></summary>
          <div className="border-t border-slate-100 p-4">
            <div className="rounded-xl bg-slate-50 p-3"><h4 className="text-xs font-semibold text-slate-500">Candidate’s answer</h4><p className="mt-1.5 whitespace-pre-wrap break-words text-sm leading-7 text-slate-700">{source(pair.answer_ids) || "No answer recorded yet."}</p></div>
            {pair.analysis_error ? <p className="mt-3 text-sm text-amber-800">{pair.analysis_error}</p> : null}
            {pair.score_unavailable_reason ? <p role="status" className="mt-3 rounded-xl bg-amber-50 p-3 text-sm text-amber-900">{pair.score_unavailable_reason}</p> : null}
            {pair.assessment?.interpretation?.status === "context_supported" && pair.assessment.interpretation.support_status === "supported_by_check" ? <details className="mt-3 rounded-xl border border-blue-100 bg-blue-50/40 p-3 text-sm"><summary className="cursor-pointer font-medium text-blue-800">Transcription interpretation</summary><p className="mt-2 text-xs text-slate-500">Original text above is unchanged. These contextual readings were used for analysis, not verified against audio.</p>{pair.assessment.interpretation.notes.map((note, i) => <div key={i} className="mt-3"><p><span className="font-medium">Read as: </span>{note.interpreted_as}</p><p className="mt-1 text-xs text-slate-600">{note.reason}</p><TranscriptCitation citation={note.original} runId={run.id} interviewId={interviewId} />{note.context.map((citation, j) => <TranscriptCitation key={j} citation={citation} runId={run.id} interviewId={interviewId} />)}</div>)}</details> : null}
            {["answer_in_progress", "awaiting_answer"].includes(pair.state) ? <button className={`${button} mt-3`} disabled={busy} onClick={() => void action(() => analysisApi.start(interviewId, automatic, true), "The latest answer will be scored.")}>Score this answer now</button> : null}
            {pair.assessment || pair.score ? <div className="hiresense-analysis-score-grid mt-4">{dimensions.map(dimension => {
              const item = pair.assessment?.[dimension];
              const points = pair.score?.breakdown[dimension];
              const uncertainMeaning = pair.assessment?.interpretation && (pair.assessment.interpretation.status === "uncertain" || pair.assessment.interpretation.support_status !== "supported_by_check");
              const reason = uncertainMeaning ? "Verify the answer’s wording before drawing a conclusion." : points?.reason || item?.justification || "No score explanation is available yet.";
              return <section aria-label={`${dimension} score`} key={dimension} className="min-w-0 rounded-xl border border-slate-100 bg-white p-3"><div className="flex flex-wrap items-center justify-between gap-2"><h4 className="text-sm font-semibold capitalize text-slate-700">{dimension}</h4><span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${scoreStyle(points?.status || "")}`}>{scoreLabel(points?.status || "")}</span></div><p className="mt-2 text-xs leading-6 text-slate-600">{shortReason(reason)}</p></section>;
            })}</div> : null}
          </div>
        </details>;
      })}</div>
      {run.result.unpaired?.length ? <details className="group mt-4 overflow-hidden rounded-2xl border border-slate-200 bg-white">
        <summary className="flex min-h-12 cursor-pointer list-none items-center gap-2.5 px-4 py-3 text-sm font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-blue-500 [&::-webkit-details-marker]:hidden">
          <span className="min-w-0 flex-1">Other transcript passages</span><span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs tabular-nums text-slate-500">{run.result.unpaired.length}</span>
          <svg aria-hidden="true" className="h-4 w-4 shrink-0 text-slate-400 transition-transform group-open:rotate-180" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="m6 9 6 6 6-6" /></svg>
        </summary>
        <div className="border-t border-slate-100 p-3 sm:p-4"><ol aria-label="Other transcript passages" className="hiresense-transcript-thread">{run.result.unpaired.map(item => {
          const segment = segments.find(segment => segment.id === item.segment_id);
          const side = segment?.speaker === "INTERVIEWER" ? "outgoing" : segment?.speaker === "CANDIDATE" ? "incoming" : "neutral";
          const speaker = segment?.speaker === "INTERVIEWER" ? "Interviewer" : segment?.speaker === "CANDIDATE" ? "Candidate" : "Unknown speaker";
          return <li key={item.segment_id} data-speaker={segment?.speaker} data-side={side} aria-label={segment ? `${speaker} · ${transcriptTime(segment.start_offset_ms)}` : "Unavailable passage"} className="hiresense-transcript-entry">
            <div className="hiresense-transcript-message">
              <div className="hiresense-transcript-bubble"><p className="hiresense-transcript-copy">{segment?.text || "Source unavailable"}</p></div>
              {segment ? <div className="hiresense-transcript-meta"><span aria-label={`At ${transcriptTime(segment.start_offset_ms)}`} title="Time from the start of transcription" className="hiresense-transcript-time">{transcriptTime(segment.start_offset_ms)}</span></div> : null}
            </div>
          </li>;
        })}</ol></div>
      </details> : null}
    </> : null}
  </section>;
}
