import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { assessmentApi, type Assessment, type Artifact, type Comparison } from "./assessmentApi";
import { displayPercent } from "../candidates/scoringDisplay";
import { ReportPdfDownload } from "./ReportPdfDownload";
import { EvidenceSummary } from "./EvidenceSummary";
import { PracticalAssessments } from "./PracticalAssessments";

export const text = (value: string) => value.replaceAll("_", " ");
export const score = (value: string | number | null | undefined) => value === null || value === undefined ? "—" : displayPercent(String(value));
export const reportButton = "min-h-10 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50";

export function ReportExports({ id, comparison = false }: { id: number; comparison?: boolean }) {
  const [artifact, setArtifact] = useState<Artifact>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!artifact || !["queued", "processing"].includes(artifact.status)) return;
    let alive = true;
    const timer = window.setInterval(() => { void assessmentApi.artifact(artifact.id).then(a => { if (alive) setArtifact(a); })
      .catch(() => { if (alive) setError("The download status is unavailable. Try again."); }); }, 1500);
    return () => { alive = false; window.clearInterval(timer); };
  }, [artifact?.id, artifact?.status]);
  async function request(format: "html" | "pdf") {
    setBusy(true); setError("");
    try { setArtifact(await assessmentApi.export(id, format, comparison)); }
    catch (e) { setError(e instanceof Error ? e.message : "The download could not be prepared."); }
    finally { setBusy(false); }
  }
  async function download(print = false) {
    if (!artifact) return;
    const popup = print ? window.open("", "_blank") : null;
    try {
      const blob = await assessmentApi.blob(artifact.id);
      const url = URL.createObjectURL(blob);
      if (popup) { popup.opener = null; popup.onload = () => { popup.print(); }; popup.location.href = url; }
      else { const anchor = document.createElement("a"); anchor.href = url; anchor.download = `hiresense-report-${id}.${artifact.format}`; anchor.click(); }
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (e) { popup?.close(); setError(e instanceof Error ? e.message : "Download failed."); }
  }
  return <section aria-label="Report exports" className="my-4 flex flex-wrap items-center gap-2">
    <button className={reportButton} disabled={busy} onClick={() => void request("html")}>Prepare HTML / print</button>
    <button className={reportButton} disabled={busy} onClick={() => void request("pdf")}>Prepare PDF</button>
    {artifact ? <span role="status" className="text-sm">{artifact.format.toUpperCase()}: {text(artifact.status)}</span> : null}
    {artifact?.status === "completed" ? <><button className={`${reportButton} text-blue-700`} onClick={() => void download()}>Download {artifact.format.toUpperCase()}</button>
      {artifact.format === "html" ? <button className={reportButton} onClick={() => void download(true)}>Print report</button> : null}</> : null}
    {error || artifact?.error ? <p role="alert" className="w-full text-sm text-red-700">{error || artifact?.error} You can try HTML if PDF fails.</p> : null}
  </section>;
}

const dimensions: Record<string, string> = { relevance: "Answered the question", accuracy: "Correctness", completeness: "Complete answer", quality: "Clear explanation" };
export function AssessmentView({ report }: { report: Assessment; onReviewed?: (report: Assessment) => void }) {
  if (report.status !== "completed") return <section className="mt-4 rounded-xl bg-white p-5"><p role="status">{report.status === "failed" ? "The candidate's scores could not be calculated. Calculate the ranking again." : "Preparing candidate details…"}</p></section>;
  const r = report.result, totals = r.score_summary;
  function refs(ids: string[]) {
    return [...new Set(ids)].map(id => {
      const evidence = r.evidence[id];
      return evidence ? <figure key={id} className="mt-3 rounded-lg bg-slate-50 p-3"><blockquote className="whitespace-pre-wrap border-l-2 border-blue-400 pl-3">{evidence.quote}</blockquote><figcaption className="mt-2 text-xs text-slate-500">{evidence.locator} · Source version {evidence.source_version.slice(0, 12)}</figcaption></figure> : null;
    });
  }
  return <article aria-label="Consolidated candidate assessment" className="min-w-0 rounded-2xl bg-white">
    <h2 className="text-2xl font-bold">{r.identification.candidate_name}</h2><p className="text-sm text-slate-500">{r.identification.job_title}</p>
    {report.stale ? <p role="status" className="mt-3 rounded bg-amber-50 p-3 text-sm">These are saved results. Calculate the final ranking again to include recent changes.</p> : null}
    <div className="my-5 grid gap-3 sm:grid-cols-3">{[["CV score", totals?.cv_score ?? r.cv?.final_score], ["Interview score", totals?.interview_score], ["Final score", totals?.final_score]].map(([name,value]) => <div key={name} className={`rounded-2xl border p-4 ${name === "Final score" ? "border-blue-200 bg-blue-50" : name === "CV score" ? "border-teal-100 bg-teal-50/70" : "border-violet-100 bg-violet-50/70"}`}><p className="text-xs font-medium text-slate-600">{name}</p><p className={`mt-2 text-2xl font-bold tabular-nums ${name === "CV score" ? "text-teal-800" : name === "Interview score" ? "text-violet-800" : "text-blue-700"}`}>{score(value)}</p></div>)}</div>
    <p className="text-sm">{totals?.reason ?? "Calculate the final ranking to add interview and final scores to this older report."}</p>
    {totals?.ready ? <p className="mt-2 text-sm text-slate-500">CV {totals.cv_weight ?? 50}% + interview {totals.interview_weight ?? 50}%. Interview score: average of {totals.question_count} {totals.question_count === 1 ? "question" : "questions"}{totals.unanswered_count ? `, including ${totals.unanswered_count} unanswered (zero)` : ""}.</p> : null}
    {r.evidence_summary && Object.keys(r.evidence_summary).length ? <EvidenceSummary value={r.evidence_summary} evidence={finding => refs(finding.evidence_ids)} /> : r.simple_summary ? <div className="mt-5 grid gap-4 sm:grid-cols-2">{(["strengths", "improvements"] as const).map(key => <section className={`rounded-2xl border p-4 ${key === "strengths" ? "border-emerald-100 bg-emerald-50/40" : "border-amber-100 bg-amber-50/40"}`} key={key}><h3 className="text-sm font-semibold text-slate-700">{key === "strengths" ? "Strengths" : "Areas to improve"}</h3>{r.simple_summary![key].length ? <ul className="mt-2 list-disc space-y-2 pl-5 text-sm leading-6 text-slate-600">{r.simple_summary![key].map((fact, i) => <li key={i}>{fact.text}</li>)}</ul> : <p className="mt-2 text-sm text-slate-500">No additional points recorded.</p>}</section>)}</div> : null}
    <PracticalAssessments values={r.practical_assessments ?? []} />
    <h3 className="mt-6 text-lg font-bold">Interview questions and scores</h3>
    {!r.interviews.length ? <p className="mt-2 text-sm text-slate-500">Interview not scored yet.</p> : null}
    {r.interviews.map(interview => <section key={interview.id} className="mt-3">
      {interview.pairs.filter(pair => pair.state !== "excluded").map(pair => <details key={pair.id} className="mt-3 rounded-xl border border-slate-200 p-4"><summary className="flex cursor-pointer items-start justify-between gap-4"><span className="font-medium text-slate-700">{pair.question}</span><span className="shrink-0 rounded-lg bg-blue-50 px-2 py-1 text-sm font-bold text-blue-700">{score(pair.score?.percentage)}</span></summary>
        <p className="mt-3 whitespace-pre-wrap text-sm"><strong>Answer: </strong>{pair.answer || "No answer recorded. This question scores zero."}</p>
        {pair.score_unavailable_reason ? <p className="mt-3 text-sm text-amber-800">{pair.score_unavailable_reason}</p> : null}
        {pair.interpretation?.status === "context_supported" ? <details className="mt-3 text-sm"><summary className="cursor-pointer text-blue-700">Transcription interpretation</summary><p className="mt-2 text-xs text-slate-500">Contextual reading used for analysis; original transcript is unchanged.</p>{pair.interpretation.notes.map((note, i) => <p key={i} className="mt-2">“{note.original.quote}” → {note.interpreted_as}. {note.reason}</p>)}</details> : null}
        <details className="mt-4"><summary className="cursor-pointer text-sm text-blue-700">Why this score?</summary>{Object.entries(pair.dimensions).map(([name, dimension]) => <section key={name} className="mt-4 text-sm"><h4 className="font-semibold">{dimensions[name] ?? text(name)}</h4><p className="mt-1">{dimension.simple_reason ?? dimension.finding}</p></section>)}</details>
      </details>)}
    </section>)}
    <details className="mt-5 rounded-xl border border-slate-200 p-4"><summary className="cursor-pointer text-sm text-blue-700">CV evidence</summary>{r.matrix.map(row => <section key={row.requirement_id} className="mt-4 text-sm"><p className="font-semibold">{row.name} · {text(row.cv_status)}</p>{refs(row.cv_evidence_ids)}</section>)}</details>
    <ReportPdfDownload key={report.id} id={report.id} />
    <p className="mt-5 text-xs text-slate-500">Scores show evidence against the job requirements, not a guarantee of job performance. The interviewer makes the hiring decision.</p>
  </article>;
}

export function ComparisonView({ value }: { value: Comparison }) {
  return <section aria-label="Candidate comparison" className="mt-5 rounded-2xl border bg-white p-5"><h2 className="text-xl font-bold">Saved comparison</h2>
    <p className="mt-2 text-sm">{value.snapshot.policy}</p>
    <div className="mt-4 overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th className="p-3">Candidate</th><th>CV score</th><th>Interview score</th><th>Final score</th><th /></tr></thead><tbody>{value.snapshot.assessments.map(run => <tr key={run.id} className="border-t"><td className="p-3">{run.result.identification.candidate_name}</td><td>{score(run.result.cv?.final_score)}</td><td>{score(run.result.score_summary?.interview_score)}</td><td>{score(run.result.score_summary?.final_score)}</td><td><Link className="text-blue-700" to={`/interviewer/reports?application=${run.application_id}&run=${run.id}`}>View details</Link></td></tr>)}</tbody></table></div>
    <details className="mt-4"><summary>Download comparison</summary><ReportExports id={value.id} comparison /></details>
  </section>;
}
