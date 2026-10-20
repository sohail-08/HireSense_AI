import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { apiRequest } from "../api/apiClient";
import { useSupervisor } from "../components/assistant/SupervisorProvider";
import { assessmentApi, type Assessment, type Comparison, type FinalRanking } from "../components/assessments/assessmentApi";
import { AssessmentView, ComparisonView, ReportExports, reportButton, score } from "../components/assessments/AssessmentView";
import type { ScreeningJobOption } from "../types";

export function ConsolidatedAssessmentsPage() {
  const [params, setParams] = useSearchParams();
  const { setSelectedJobPostingId, setSelectedApplicationIds, refreshVersion } = useSupervisor();
  const [jobs, setJobs] = useState<ScreeningJobOption[]>([]);
  const [job, setJob] = useState<number>();
  const [ranking, setRanking] = useState<FinalRanking>();
  const [report, setReport] = useState<Assessment>();
  const [comparison, setComparison] = useState<Comparison>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    void apiRequest<ScreeningJobOption[]>("/screening/jobs").then(async values => {
      const app = Number(params.get("application"));
      const target = app ? await assessmentApi.application(app) : undefined;
      const requestedJob = Number(params.get("job"));
      if (alive) { setJobs(values); setJob(current => target?.job_posting_id ?? current ?? values.find(j => j.id === requestedJob)?.id ?? values[0]?.id); }
    }).catch(e => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, []);
  useEffect(() => {
    setSelectedJobPostingId(job);
    return () => { setSelectedJobPostingId(undefined); setSelectedApplicationIds([]); };
  }, [job, setSelectedJobPostingId, setSelectedApplicationIds]);
  useEffect(() => {
    if (!job) return;
    let alive = true;
    setRanking(undefined); setError("");
    void assessmentApi.ranking(job).then(value => { if (alive) setRanking(value); }).catch(e => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, [job, refreshVersion]);
  useEffect(() => {
    let alive = true;
    const id = Number(params.get("run")), comparisonId = Number(params.get("comparison"));
    setReport(undefined); setComparison(undefined);
    if (id) void assessmentApi.read(id).then(value => {
      if (alive) { setReport(value); setJob(value.job_posting_id); setSelectedApplicationIds([value.application_id]); }
    }).catch(e => { if (alive) setError(e.message); });
    else if (comparisonId) void assessmentApi.comparison(comparisonId).then(value => {
      if (alive) { setComparison(value); setJob(value.snapshot.assessments[0]?.job_posting_id); }
    }).catch(e => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, [params.get("run"), params.get("comparison"), setSelectedApplicationIds]);
  useEffect(() => {
    if (!job || ranking?.status !== "processing") return;
    let alive = true, pending = false;
    const timer = window.setInterval(() => {
      if (pending) return;
      pending = true;
      void assessmentApi.ranking(job).then(value => { if (alive) setRanking(value); })
        .catch(e => { if (alive) setError(e.message); }).finally(() => { pending = false; });
    }, 2000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [job, ranking?.status]);
  async function calculate() {
    if (!job) return;
    setBusy(true); setError(""); setReport(undefined); setParams({}); setSelectedApplicationIds([]);
    try { setRanking(await assessmentApi.calculate(job)); }
    catch (e) { setError(e instanceof Error ? e.message : "The ranking could not be calculated. Try again."); }
    finally { setBusy(false); }
  }
  return <div className="mx-auto max-w-6xl p-4 sm:p-6">
    <h1 className="text-3xl font-bold">Candidate ranking</h1>
    <p className="mt-2 text-slate-600">Compare CV scores and interview answers in one place.</p>
    {error ? <p role="alert" className="my-3 rounded bg-red-50 p-3 text-red-700">{error}</p> : null}
    <section className="my-5 rounded-2xl border bg-white p-5">
      <div className="flex flex-wrap items-end gap-4">
        <label className="min-w-0 flex-1 text-sm font-semibold">Job posting<select disabled={busy} className="mt-2 block w-full rounded-lg border p-3" value={job ?? ""} onChange={e => {
          setJob(Number(e.target.value)); setReport(undefined); setComparison(undefined); setParams({}); setSelectedApplicationIds([]);
        }}><option value="" disabled>Select a job</option>{jobs.map(j => <option key={j.id} value={j.id}>{j.title}</option>)}</select></label>
        <button className={`${reportButton} bg-blue-600 text-white`} disabled={busy || !job || !ranking?.candidates.length || ranking?.status === "processing"} onClick={() => void calculate()}>
          {busy || ranking?.status === "processing" ? "Calculating…" : "Calculate final ranking"}</button>
      </div>
      <p className="mt-4 text-sm font-medium">Final score = 50% CV score + 50% interview score</p>
      <p className="mt-1 text-sm text-slate-500">The interview score is the average of the scored questions. Unanswered questions score zero.</p>
    </section>
    {ranking ? <section aria-label="Final candidate ranking" className="rounded-2xl border bg-white p-5">
      {ranking.status === "processing" ? <p role="status" className="mb-4 text-blue-700">{ranking.stage === "scoring_answers" ? "Scoring interview answers…" : "Calculating final scores…"} You can leave this page and return later.</p> : null}
      {ranking.error ? <p role="alert" className="mb-3 text-red-700">{ranking.error}</p> : null}
      {ranking.stale ? <p role="status" className="mb-4 rounded bg-amber-50 p-3 text-sm">Candidates or scores have changed. Calculate the final ranking again to update these saved results.</p> : null}
      {ranking.incompatibilities.map(message => <p key={message} className="mb-3 rounded bg-amber-50 p-3 text-sm">{message}</p>)}
      {!ranking.candidates.length ? <p>No candidates have applied for this job yet.</p> : <div className="overflow-x-auto"><table className="w-full min-w-[620px] text-left text-sm">
        <thead><tr className="border-b text-slate-500">{["Rank", "Candidate", "CV score", "Interview score", "Final score", ""].map((label, i) => <th className="p-3" key={i}>{label}</th>)}</tr></thead>
        <tbody>{ranking.candidates.map(candidate => <tr className="border-b last:border-0" key={candidate.application_id}>
          <td className="p-3 font-semibold">{candidate.final_rank ?? "—"}</td>
          <td className="max-w-xs p-3"><p className="font-semibold">{candidate.candidate_name}</p>{candidate.final_rank === null ? <p className="mt-1 text-xs text-slate-500">{candidate.reason}</p> : null}</td>
          <td className="p-3">{score(candidate.cv_score)}</td><td className="p-3">{score(candidate.interview_score)}</td>
          <td className="p-3 font-bold text-blue-700">{score(candidate.final_score)}</td>
          <td className="p-3">{candidate.assessment_id && ranking.status === "completed" ? <button className="text-blue-700 hover:underline" onClick={() => setParams({ application: String(candidate.application_id), run: String(candidate.assessment_id) })}>View details<span className="sr-only"> for {candidate.candidate_name}</span></button> : null}</td>
        </tr>)}</tbody></table></div>}
      {ranking.status === "completed" && ranking.id ? <details className="mt-4"><summary className="cursor-pointer text-sm text-blue-700">Download ranking</summary><ReportExports id={ranking.id} comparison /></details> : null}
    </section> : <p role="status">Loading candidates…</p>}
    {comparison ? <ComparisonView value={comparison} /> : null}
    {report ? <><div className="mt-5 flex justify-end"><button className={reportButton} onClick={() => { setParams({}); setSelectedApplicationIds([]); }}>Close details</button></div><AssessmentView key={report.id} report={report} /></> : null}
  </div>;
}
