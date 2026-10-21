import { useCallback, useEffect, useRef, useState } from "react";
import { analysisApi, type AnalysisState, type PairEdit, type Segment, type Citation } from "./analysisApi";
import { TranscriptCitation } from "./TranscriptCitation";
import { transcriptTime } from "./transcriptionApi";
import { StyledSelect } from "../common/StyledSelect";

const label = (text: string) => text.replaceAll("_", " ");
const button = "rounded-lg border px-3 py-2 text-sm disabled:opacity-50";

export function InterviewAnalysisPanel({ interviewId }: { interviewId: number }) {
  const [state, setState] = useState<AnalysisState>();
  const [version, setVersion] = useState<number>();
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [automatic, setAutomatic] = useState(true);
  const [editing, setEditing] = useState<PairEdit[]>();
  const [reason, setReason] = useState("");
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [linked, setLinked] = useState<Record<string, string>>({});
  const lock = useRef(false);
  const generation = useRef(0);
  const refresh = useCallback(async () => {
    const request = ++generation.current;
    try {
      const result = await analysisApi.read(interviewId, version);
      if (request === generation.current) setState(result);
    } catch (e) { if (request === generation.current) setError(e instanceof Error ? e.message : "Could not load analysis."); }
  }, [interviewId, version]);
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
  const citations = (items: Citation[] = []) => run ? items.map((citation, i) => <TranscriptCitation key={`${citation.segment_id}-${i}`} citation={citation} runId={run.id} interviewId={interviewId} />) : null;
  function editPair(index: number, change: Partial<PairEdit>) { setEditing(previous => previous?.map((p, i) => i === index ? { ...p, ...change } : p)); }
  function edit() {
    setEditing((run?.result.pairs || []).map(({ id, question_ids, answer_ids, context_ids, subparts, excluded, unanswered }) => ({ id, question_ids, answer_ids, context_ids, subparts, excluded, unanswered })));
  }
  const current = !version || state?.versions[0]?.id === version;
  return <section id="interview-analysis" aria-label="Private interview analysis" className="mt-5 min-w-0 rounded-2xl bg-white p-5 shadow-sm">
    <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-lg font-bold">Interview answers & evidence</h2>
      {run ? <span role="status" className="rounded-full bg-slate-100 px-3 py-1 text-sm">Version {run.version} · {label(run.status)}{run.status === "processing" ? ` · ${label(run.stage)}` : ""}</span> : null}</div>
    <p className="mt-2 text-sm text-slate-600">Answers are scored using the question bank’s answer guides and transcript evidence.</p>
    <p className="mt-1 text-xs text-slate-500">Relevance, accuracy, completeness and quality each contribute 25%. Met = 1, partially met = 0.5, unmet = 0.</p>
    <div className="mt-4 flex flex-wrap items-center gap-3">
      <button className={`${button} bg-blue-600 text-white`} disabled={busy} onClick={() => { setVersion(undefined); void action(() => analysisApi.start(interviewId, automatic), "Analysis requested. Progress will update here."); }}>Analyze saved answers</button>
      <label className="text-sm"><input type="checkbox" checked={automatic} onChange={e => setAutomatic(e.target.checked)} /> Continue as new answers arrive</label>
      {state?.automatic ? <button className={button} disabled={busy} onClick={() => void action(() => analysisApi.start(interviewId, false), "Automatic updates stopped.")}>Stop automatic updates</button> : null}
      {run ? <button className={button} disabled={busy} onClick={() => { setVersion(undefined); void action(() => analysisApi.start(interviewId, automatic, false, true), "A new analysis version was requested."); }}>Reanalyze</button> : null}
    </div>
    <p className="mt-2 text-xs text-slate-500">An answer stays in progress until a new question or the end of transcription. A pause alone does not finish it.</p>
    {state?.versions.length ? <label className="mt-3 block text-sm">Analysis version <StyledSelect label="Analysis version" className="mt-1" value={version ? String(version) : ""}
      options={[{ value: "", label: "Latest" }, ...state.versions.map(v => ({ value: String(v.id), label: `Version ${v.version} · ${label(v.status)}` }))]}
      onChange={value => { setVersion(value ? Number(value) : undefined); setEditing(undefined); }} /></label> : null}
    {error || run?.error ? <p role="alert" className="mt-3 text-sm text-red-700">{error || run?.error}</p> : null}
    {notice ? <p role="status" className="mt-3 text-sm text-emerald-800">{notice}</p> : null}
    {run?.stale ? <p className="mt-3 rounded bg-amber-50 p-3 text-sm text-amber-900">This version uses earlier transcript or reference material. Analyze saved answers to update it.</p> : null}
    {run?.result.gaps?.map(gap => <p key={gap} className="mt-2 text-sm text-amber-900">{gap}</p>)}
    {!run ? <p className="mt-4 text-sm text-slate-500">Start with saved final transcript text. Results will remain available after refresh.</p> : null}
    {run?.result.pairs ? <>
      <div className="mt-5 flex flex-wrap justify-between gap-2"><h3 className="font-bold">Question–answer timeline</h3><button className={button} disabled={busy || !current || run.status !== "completed"} onClick={edit}>Correct pairing / merge / split</button></div>
      {!run.result.pairs.length ? <p className="mt-3 text-sm">No substantive interviewer questions were detected. Review the unpaired transcript below.</p> : null}
      {run.result.pairs.map((pair, index) => <details key={pair.id} className="mt-3 rounded-xl border p-4" open={index === run.result.pairs!.length - 1}>
        <summary className="cursor-pointer font-semibold">{index + 1}. {source(pair.question_ids).slice(0, 150)} <span className="ml-2 text-xs font-normal text-slate-500">{label(pair.state)}</span>
          {pair.score ? <span className="ml-3 inline-block rounded-full bg-blue-50 px-3 py-1 text-sm text-blue-800" aria-label={`Answer score ${pair.score.percentage}%`}>{pair.score.percentage}%</span> : null}</summary>
        <p className="mt-3 whitespace-pre-wrap text-sm"><strong>Question:</strong> {source(pair.question_ids)}</p>
        <p className="mt-3 whitespace-pre-wrap text-sm"><strong>Answer:</strong> {source(pair.answer_ids) || "No answer associated yet."}</p>
        {pair.subparts.length ? <p className="mt-2 text-sm">Question parts: {pair.subparts.join("; ")}</p> : null}
        {pair.flags.length ? <p className="mt-2 text-sm text-slate-600">Transcript notes: {pair.flags.map(label).join(", ")}</p> : null}
        <p className="mt-2 text-xs text-slate-500">Pairing: {label(pair.pairing_confidence)}. {pair.pairing_reasons.join(" ")}</p>
        {pair.analysis_error ? <p className="mt-2 text-sm text-amber-900">{pair.analysis_error}</p> : null}
        {["answer_in_progress", "awaiting_answer"].includes(pair.state) && current ? <button className={`${button} mt-3`} disabled={busy} onClick={() => void action(() => analysisApi.start(interviewId, automatic, true), "The current exchange will be analyzed as complete.")}>The answer is finished — analyze it</button> : null}
        {pair.score ? <p className="mt-3 text-sm font-medium">Answer score: {pair.score.percentage}% · {pair.score.earned}/{pair.score.possible} points</p> : null}
        {pair.assessment ? <div className="mt-4 grid gap-3 md:grid-cols-2">{(["relevance", "accuracy", "completeness", "quality"] as const).map(dimension => {
          const item = pair.assessment![dimension];
          const points = pair.score?.breakdown[dimension];
          return <section key={dimension} className="min-w-0 rounded-lg bg-slate-50 p-3"><h4 className="font-semibold capitalize">{dimension} · {points ? `${label(points.status)} (${points.value})` : label(item.label)}</h4><p className="mt-2 text-sm">{points?.reason || item.justification}</p>
            {citations(item.citations)}{item.evidence_gaps.map((gap, i) => <p key={i} className="mt-1 text-sm text-amber-900">{gap}</p>)}
            {item.flags.length ? <p className="mt-2 text-xs text-amber-900">{item.flags.map(label).join(", ")}</p> : null}
            {item.references.map((ref, i) => <blockquote key={i} className="mt-2 border-l-2 pl-2 text-xs"><strong>Answer guide: {ref.title}</strong><p>{ref.quote}</p><p>Version {ref.version.slice(0, 12)}</p></blockquote>)}
          </section>;
        })}</div> : null}
        {pair.assessment?.expected_elements.length ? <p className="mt-3 text-sm">Expected elements ({label(pair.assessment.expected_elements_basis)}): {pair.assessment.expected_elements.join("; ")}</p> : null}
        <label className="mt-3 block text-sm">Your review<textarea className="mt-1 w-full rounded border p-2" maxLength={2000} rows={2} value={notes[pair.id] || ""} onChange={e => setNotes({ ...notes, [pair.id]: e.target.value })} /></label>
        <button className={button} disabled={busy || !notes[pair.id]?.trim()} onClick={() => void action(() => analysisApi.review(interviewId, run.id, "assessment_review", pair.id, notes[pair.id]), "Review saved alongside the original assessment.")}>Save review</button>
        {run.reviews.filter(r => r.target_id === pair.id && r.kind === "assessment_review").map(r => <p key={r.id} className="mt-2 rounded bg-blue-50 p-2 text-sm">Interviewer review: {r.payload.note}</p>)}
        {pair.suggestions?.length ? <h4 className="mt-5 font-semibold">Suggested follow-ups</h4> : null}
        {pair.suggestions?.map(s => {
          const reviews = run.reviews.filter(r => r.target_id === s.id);
          return <article key={s.id} className="mt-3 rounded-lg border p-3"><p className="font-medium">{s.question}</p><p className="mt-2 text-sm">{s.reason}</p><p className="mt-2 text-xs">{label(s.priority)} priority: {s.priority_reason}</p><p className="mt-2 text-sm">Clarify: {s.expected_clarification}</p>{citations(s.citations)}
            <p className="mt-1 text-xs text-slate-500">Requirements: {s.requirement_ids.join(", ") || "Question clarification"}</p>
            <div className="mt-2 flex flex-wrap gap-2"><button className={button} disabled={busy} onClick={() => void action(() => analysisApi.review(interviewId, run.id, "suggestion_used", s.id), "Marked used. Link a spoken question to confirm it was asked.")}>Mark used</button><button className={button} disabled={busy} onClick={() => void action(() => analysisApi.review(interviewId, run.id, "suggestion_dismissed", s.id), "Suggestion dismissed.")}>Dismiss</button></div>
            {reviews.length ? <p className="mt-2 text-xs">{reviews.map(r => label(r.kind)).join(" · ")}</p> : null}
            <label className="mt-2 block text-xs">Confirm the spoken question<StyledSelect label="Confirm the spoken question" className="mt-1" value={linked[s.id] || ""}
              options={[{ value: "", label: "Choose a transcript passage" }, ...segments.filter(seg => seg.speaker === "INTERVIEWER").map(seg => ({ value: seg.id, label: `${transcriptTime(seg.start_offset_ms)} · ${seg.text.slice(0, 100)}` }))]}
              onChange={value => setLinked({ ...linked, [s.id]: value })} /></label>
            <button className={`${button} mt-2`} disabled={busy || !linked[s.id]} onClick={() => void action(() => analysisApi.review(interviewId, run.id, "suggestion_linked", s.id, "Confirmed by interviewer", [linked[s.id]]), "Suggestion linked to the spoken question.")}>Link spoken question</button>
          </article>;
        })}
      </details>)}
      <details className="mt-4 rounded-xl border p-3"><summary className="cursor-pointer font-semibold">Requirement evidence coverage</summary>
        {run.result.coverage?.map(item => <article key={item.requirement_id} className="mt-3 border-t pt-3"><p className="font-medium">{item.name} · {item.statuses.map(label).join(" / ")}</p><p className="text-xs">{label(item.coverage_status ?? "not_explored")}{item.question_pair_ids?.length ? ` · Questions: ${item.question_pair_ids.join(", ")}` : ""}</p>
          {item.statuses.includes("not_assessed") ? <p className="text-sm text-slate-500">This requirement has not been assessed; this is not a failure to meet it.</p> : null}
          {item.evidence.map((mapping, i) => <div key={i} className="mt-2 text-sm"><p>{mapping.explanation}</p>{citations(mapping.citations)}</div>)}</article>)}
      </details>
      <details className="mt-4 rounded-xl border p-3"><summary className="cursor-pointer font-semibold">Unpaired / procedural transcript ({run.result.unpaired?.length || 0})</summary>
        {run.result.unpaired?.map(item => <p key={item.segment_id} className="mt-2 text-sm">{label(item.kind)}: {source([item.segment_id])}</p>)}
      </details>
    </> : null}
    {editing && run ? <section aria-label="Correct question answer pairing" className="mt-5 rounded-xl border-2 border-blue-200 p-4">
      <h3 className="font-bold">Correct pairing</h3><p className="mt-2 text-sm">Select the original segments for each exchange. Keep every existing segment in a question, answer, or context. Use context for acknowledgements and clarification. Saving creates a new version.</p>
      {editing.map((pair, i) => <div key={pair.id} className="mt-4 border-t pt-3"><h4 className="font-semibold">Exchange {i + 1}</h4>
        <SegmentSelect title="Question segments" values={pair.question_ids} segments={segments.filter(s => s.speaker === "INTERVIEWER")} onChange={question_ids => editPair(i, { question_ids })} />
        <SegmentSelect title="Answer segments" values={pair.answer_ids} segments={segments.filter(s => s.speaker === "CANDIDATE")} onChange={answer_ids => editPair(i, { answer_ids, unanswered: false })} />
        <SegmentSelect title="Context / clarification segments" values={pair.context_ids} segments={segments} onChange={context_ids => editPair(i, { context_ids })} />
        <label className="mr-3 text-sm"><input type="checkbox" checked={pair.excluded} onChange={e => editPair(i, { excluded: e.target.checked })} /> Exclude procedural conversation</label>
        <label className="text-sm"><input type="checkbox" checked={pair.unanswered} onChange={e => editPair(i, { unanswered: e.target.checked, ...(e.target.checked ? { answer_ids: [], context_ids: [...new Set([...pair.context_ids, ...pair.answer_ids])] } : {}) })} /> Unanswered</label>
        <div className="mt-2 flex gap-2">{i < editing.length - 1 ? <button className={button} onClick={() => { const next = editing[i + 1]; setEditing(editing.flatMap((p, index) => index === i ? [{ ...p, question_ids: [...p.question_ids, ...next.question_ids], answer_ids: [...p.answer_ids, ...next.answer_ids], context_ids: [...p.context_ids, ...next.context_ids], subparts: [...p.subparts, ...next.subparts] }] : index === i + 1 ? [] : [p])); }}>Merge with next</button> : null}
          <button className={button} onClick={() => setEditing([...editing.slice(0, i + 1), { id: crypto.randomUUID(), question_ids: [], answer_ids: [], context_ids: [], subparts: [], excluded: false, unanswered: false }, ...editing.slice(i + 1)])}>Split — add exchange after this</button></div>
      </div>)}
      {!editing.length ? <button className={`${button} mt-2`} onClick={() => setEditing([{ id: crypto.randomUUID(), question_ids: [], answer_ids: [], context_ids: [], subparts: [], excluded: false, unanswered: false }])}>Add exchange</button> : null}
      <label className="mt-3 block text-sm">Reason for correction<textarea className="mt-1 w-full rounded border p-2" value={reason} maxLength={2000} onChange={e => setReason(e.target.value)} /></label>
      <div className="mt-2 flex gap-2"><button className={button} disabled={busy || !reason.trim() || editing.some(p => !p.question_ids.length)} onClick={() => void action(async () => { await analysisApi.correct(interviewId, run.id, editing, reason); setEditing(undefined); setVersion(undefined); }, "Correction saved. A new analysis version is queued.")}>Save correction & reanalyze</button><button className={button} onClick={() => setEditing(undefined)}>Cancel</button></div>
    </section> : null}
  </section>;
}

function SegmentSelect({ title, values, segments, onChange }: { title: string; values: string[]; segments: Segment[]; onChange: (value: string[]) => void }) {
  return <label className="my-2 block text-sm">{title}<StyledSelect multiple label={title} value={values} onChange={onChange} className="mt-1" placeholder="Choose transcript passages"
    options={segments.map(s => ({ value: s.id, label: `${transcriptTime(s.start_offset_ms)} · ${s.speaker.toLowerCase()}`, description: s.text.slice(0, 160) }))} />
    <span className="text-xs text-slate-500">Choose one or more passages. Click a selected passage to remove it.</span></label>;
}
