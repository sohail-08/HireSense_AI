import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { assessmentApi, type Assessment, type Evidence, type Artifact, type Comparison } from "./assessmentApi";
import { displayPercent } from "../candidates/scoringDisplay";

export const text = (value: string) => value.replaceAll("_", " ");
export const score = (value: string | number | null | undefined) => value === null || value === undefined ? "Not available" : displayPercent(String(value));
export const reportButton = "rounded-lg border px-3 py-2 text-sm disabled:opacity-50";

export function ReportExports({ id, comparison = false }: { id: number; comparison?: boolean }) {
  const [artifact, setArtifact] = useState<Artifact>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!artifact || !["queued", "processing"].includes(artifact.status)) return;
    let alive = true;
    const timer = window.setInterval(() => { void assessmentApi.artifact(artifact.id).then(a => { if (alive) setArtifact(a); })
      .catch(() => { if (alive) setError("Export status is unavailable. Retry the format to reconnect."); }); }, 1500);
    return () => { alive = false; window.clearInterval(timer); };
  }, [artifact?.id, artifact?.status]);
  async function request(format: "html" | "pdf") {
    setBusy(true); setError("");
    try { setArtifact(await assessmentApi.export(id, format, comparison)); }
    catch (e) { setError(e instanceof Error ? e.message : "Export request failed."); }
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
    {artifact ? <span role="status" className="text-sm">{artifact.format.toUpperCase()} export: {text(artifact.status)}</span> : null}
    {artifact?.status === "completed" ? <><button className={`${reportButton} text-blue-700`} onClick={() => void download()}>Download {artifact.format.toUpperCase()}</button>
      {artifact.format === "html" ? <button className={reportButton} onClick={() => void download(true)}>Print report</button> : null}</> : null}
    {error || artifact?.error ? <p role="alert" className="w-full text-sm text-red-700">{error || artifact?.error} You can prepare HTML independently if PDF fails.</p> : null}
  </section>;
}

export function AssessmentView({ report, onReviewed }: { report: Assessment; onReviewed?: (report: Assessment) => void }) {
  const [evidence, setEvidence] = useState<Evidence>();
  const [note, setNote] = useState("");
  const [reviewed, setReviewed] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const r = report.result;
  function refs(ids: string[]) { return ids.map(id => r.evidence[id] ? <button key={id} className="mr-2 mt-2 text-left text-xs text-blue-700 underline" onClick={() => setEvidence(r.evidence[id])}>Evidence: {r.evidence[id].locator}</button> : null); }
  if (report.status !== "completed") return <section className="mt-4 rounded-xl bg-white p-5"><p role="status">Assessment version {report.version}: {text(report.status)} · {text(report.stage)}</p>{report.error ? <p role="alert">{report.error}</p> : null}</section>;
  return <article aria-label="Consolidated candidate assessment" className="mt-4 rounded-2xl border bg-white p-5">
    <header><h2 className="text-2xl font-bold">{r.identification.candidate_name}</h2><p>{r.identification.job_title} · Application #{report.application_id}</p>
      <p className="mt-1 text-sm text-slate-600">Version {report.version} · {text(report.completeness)} evidence · {text(report.review_status)} · {new Date(report.completed_at || report.created_at).toLocaleString()}</p>
      <p className="mt-2 break-all text-xs text-slate-500">Requirement version: {r.identification.requirement_version}</p></header>
    {report.stale ? <p role="status" className="mt-3 rounded bg-amber-50 p-3">Relevant source versions changed. Generate a new version to use them; this saved report is preserved.</p> : null}
    {r.missing.length ? <details className="my-3 rounded border border-amber-200 p-3" open><summary>Partial report: missing or incompatible sources ({r.missing.length})</summary><ul className="ml-5 list-disc">{r.missing.map(m => <li key={m}>{m}</li>)}</ul></details> : null}
    <ReportExports key={report.id} id={report.id} />
    <h3 className="mt-4 font-bold">Overall suitability position</h3>{r.summary.position.map(f => <div key={f.id} className="mt-2"><p>{f.text}</p>{refs(f.evidence_ids)}</div>)}<p className="mt-2 text-xs text-slate-500">{r.summary.basis}</p>
    <h3 className="mt-6 font-bold">CV / job-requirement scores</h3>{r.cv ? <>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{[["Technical skills", r.cv.categories.technical], ["Experience", r.cv.categories.experience], ["Qualifications", r.cv.categories.qualification], ["Weighted CV score", r.cv.final_score]].map(([name,value]) => <div key={name} className="rounded-lg bg-slate-50 p-3"><p className="text-sm">{name}</p><p className="text-xl font-bold">{score(value)}</p></div>)}</div>
      <p className="mt-2 text-xs">Saved scoring run #{r.cv.scoring_run_id} · screening #{r.cv.screening_run_id} · CV #{r.cv.document_id} · configuration #{r.cv.configuration_id}</p>
      <p className="mt-2 text-sm">Original full-job CV rank: {r.cv.original_cv_rank ?? "Unavailable"}. Cohort: {r.cv.original_cohort.length} applications.</p>
      <p className="mt-2 text-sm">Category weights: {Object.entries(r.cv.configuration.category_weights).map(([key,value]) => `${text(key)} ${value}%`).join(" · ")}</p>
      <p className="text-sm">Match counts: {Object.entries(r.cv.breakdown.counts).map(([key,value]) => `${text(key)} ${value}`).join(" · ")}</p>
      <details className="mt-3"><summary className="cursor-pointer">Saved CV justification and formula</summary><p className="mt-2 text-sm">{r.cv.formula_version}</p><p className="whitespace-pre-wrap text-sm">{r.cv.written_justification}</p></details>
    </> : <p>No saved compatible CV score is available.</p>}
    <div className="mt-6 grid gap-4 lg:grid-cols-3">{(["strengths", "limitations", "verification"] as const).map(key => <section key={key} className="rounded-xl border p-4"><h3 className="font-bold">{key === "limitations" ? "Weaknesses and evidence gaps" : key === "verification" ? "Recommended verification" : "Evidence-supported strengths"}</h3>{r.summary[key].map(f => <div key={f.id} className="mt-3 text-sm"><p>{f.text}</p>{refs(f.evidence_ids)}</div>)}</section>)}</div>
    <h3 className="mt-6 font-bold">Requirement evidence matrix</h3><div className="mt-3 overflow-x-auto"><table className="w-full min-w-[750px] text-left text-sm"><thead><tr className="bg-slate-50"><th className="p-3">Requirement</th><th className="p-3">CV</th><th className="p-3">Interview</th><th className="p-3">Gaps / verification</th></tr></thead><tbody>{r.matrix.map(row => <tr key={row.requirement_id} className="border-t align-top"><td className="p-3"><p className="font-semibold">{row.name}</p><p className="text-xs">{row.classification} · Weight {row.weight}</p><p className="mt-1 text-xs">{row.requirement_id}</p></td><td className="p-3">{text(row.cv_status)}{refs(row.cv_evidence_ids)}</td><td className="p-3"><p>{text(row.interview_coverage)}</p>{row.interview_evidence.map((m,i) => <div key={i} className="mt-2"><p>{text(m.status)}: {m.conclusion}</p><p className="text-xs">Interview #{m.interview_id}, pair {m.pair_id}</p>{refs(m.evidence_ids)}</div>)}</td><td className="p-3">{row.conflict ? <p className="font-semibold text-amber-900">Conflicting evidence</p> : null}{row.uncertainty.map(u => <p className="mt-1" key={u}>{u}</p>)}<p className="mt-2">{row.verification}</p></td></tr>)}</tbody></table></div>
    <h3 className="mt-6 font-bold">Interview findings</h3>{r.interviews.map(interview => <section key={interview.id} className="mt-3 rounded-xl border p-4"><p className="font-semibold">Interview #{interview.id} · {new Date(interview.date).toLocaleString()}</p><p className="text-xs text-slate-500">Analysis #{interview.analysis_id ?? "Unavailable"}, version {interview.analysis_version ?? "Unavailable"} · {interview.rubric_version}</p><Link className="text-sm text-blue-700" to={`/interviews/${interview.id}/console`}>Open interview evidence</Link>
      {interview.limitations.map((l,i) => <p key={i} className="mt-2 text-xs text-amber-900">{text(l)}</p>)}
      {interview.pairs.map(pair => <details key={pair.id} className="mt-3 rounded border p-3"><summary className="cursor-pointer font-medium">{pair.question} · {text(pair.state)}{pair.score ? ` · Saved answer score ${pair.score.percentage}%` : ""}</summary><p className="mt-2 whitespace-pre-wrap text-sm"><strong>Answer:</strong> {pair.answer || "No answer recorded"}</p>{Object.entries(pair.dimensions).map(([name,d]) => <div key={name} className="mt-3 text-sm"><p><strong>{text(name)} · {text(d.label)}:</strong> {d.finding}</p>{refs(d.evidence_ids)}{d.gaps.map(g => <p key={g}>{g}</p>)}</div>)}</details>)}</section>)}
    <h3 className="mt-6 font-bold">Interviewer notes</h3>{report.notes.map(n => <div key={n.id} className="my-2 rounded bg-blue-50 p-3"><p className="whitespace-pre-wrap">{n.note}</p><p className="text-xs">Author #{n.author_id} · {new Date(n.created_at).toLocaleString()}</p></div>)}
    <textarea aria-label="Assessment review note" className="mt-2 w-full rounded border p-3" maxLength={4000} rows={3} value={note} onChange={e => setNote(e.target.value)} />
    <label className="mr-3 text-sm"><input type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)} /> Mark this assessment reviewed</label>
    <button className={reportButton} disabled={busy || !note.trim()} onClick={() => { setBusy(true); void assessmentApi.review(report.id, note, reviewed).then(value => { onReviewed?.(value); setNote(""); }).catch(e => setError(e.message)).finally(() => setBusy(false)); }}>Save note</button>
    {error ? <p role="alert">{error}</p> : null}<p className="mt-5 text-xs text-slate-500">{r.policy}</p>
    {evidence ? <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4" onKeyDown={e => { if (e.key === "Escape") setEvidence(undefined); }}><section role="dialog" aria-modal="true" aria-label="Assessment evidence" className="max-h-[85vh] w-full max-w-2xl overflow-auto rounded-2xl bg-white p-6"><div className="flex justify-between gap-4"><h3 className="font-bold">{evidence.locator}</h3><button autoFocus className={reportButton} onClick={() => setEvidence(undefined)}>Close</button></div><p className="mt-2 break-all text-xs">{text(evidence.kind)} · Source version {evidence.source_version}</p><blockquote className="my-4 whitespace-pre-wrap border-l-4 border-blue-400 bg-blue-50 p-3">{evidence.quote}</blockquote>{evidence.source_text ? <details><summary>Source context</summary><p className="mt-2 whitespace-pre-wrap text-sm">{evidence.source_text}</p></details> : null}</section></div> : null}
  </article>;
}

export function ComparisonView({ value }: { value: Comparison }) {
  const c = value.snapshot;
  return <section aria-label="Candidate comparison" className="mt-5 rounded-2xl border bg-white p-5"><h2 className="text-xl font-bold">{c.basis}</h2><p className="mt-2 text-sm">{c.policy}</p><p className="mt-2 text-xs">{c.cohort_policy}</p><p className="text-xs">Selected cohort: {c.selected_cohort_application_ids.join(", ")}</p>
    {value.stale_source_assessment_ids?.length ? <p role="status" className="mt-3 rounded bg-amber-50 p-3 text-sm">Relevant sources have changed. This is a historical comparison; generate new assessment versions and compare them to refresh it.</p> : null}
    {c.incompatibilities.concat(c.interview_incompatibilities).map(i => <p key={i} className="mt-2 rounded bg-amber-50 p-3 text-sm">{i}</p>)}<ReportExports id={value.id} comparison />
    <div className="mt-4 grid auto-cols-[minmax(260px,1fr)] grid-flow-col gap-4 overflow-x-auto">{c.assessments.map(run => <article key={run.id} className="rounded-xl border p-4"><h3 className="font-bold">{run.result.identification.candidate_name}</h3><p className="text-xs">Application #{run.application_id} · assessment v{run.version}</p><p>{text(run.completeness)} · {text(run.review_status)}</p><p className="mt-2 font-bold">CV score: {score(run.result.cv?.final_score)}</p><p className="text-xs">Original CV rank: {run.result.cv?.original_cv_rank ?? "Unavailable"}</p>{c.cv_order_compatible ? <p>Comparison cohort CV rank: {run.comparison_cv_rank}</p> : null}
      {Object.entries(run.result.cv?.categories || {}).map(([k,v]) => <p key={k} className="text-sm">{text(k)}: {score(v)}</p>)}<Link className="mt-3 block text-sm text-blue-700" to={`/interviewer/reports?application=${run.application_id}&run=${run.id}`}>Open complete report and evidence</Link>
      {(["strengths", "limitations", "verification"] as const).map(key => <details key={key} className="mt-3" open><summary className="font-semibold capitalize">{key}</summary>{run.result.summary[key].map(f => <p key={f.id} className="mt-2 text-sm">{f.text}</p>)}</details>)}
      <details className="mt-3"><summary className="font-semibold">Requirement and interview coverage</summary>{run.result.matrix.map(row => <p key={row.requirement_id} className="mt-2 text-sm">{row.name}: CV {text(row.cv_status)}; interview {text(row.interview_coverage)} ({row.interview_statuses.map(text).join(", ")})</p>)}</details>
    </article>)}</div></section>;
}
