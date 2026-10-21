import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { apiRequest } from "../api/apiClient";
import { useSupervisor } from "../components/assistant/SupervisorProvider";
import { assessmentApi, type Assessment, type Comparison, type FinalRanking } from "../components/assessments/assessmentApi";
import { AssessmentView, ComparisonView } from "../components/assessments/AssessmentView";
import { FinalRankingTable } from "../components/assessments/FinalRankingTable";
import type { ScreeningJobOption } from "../types";
import { StyledSelect } from "../components/common/StyledSelect";
import { PreviewModal } from "../components/common/PreviewModal";

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
  const [jobsLoading, setJobsLoading] = useState(true);
  const [detailError, setDetailError] = useState("");
  const [detailRetry, setDetailRetry] = useState(0);
  const calculationLock = useRef(false);
  useEffect(() => {
    let alive = true;
    void apiRequest<ScreeningJobOption[]>("/screening/jobs").then(async values => {
      const app = Number(params.get("application"));
      const target = app ? await assessmentApi.application(app) : undefined;
      const requestedJob = Number(params.get("job"));
      if (alive) { setJobs(values); setJob(current => target?.job_posting_id ?? current ?? values.find(j => j.id === requestedJob)?.id ?? values[0]?.id); }
    }).catch(e => { if (alive) setError(e.message); }).finally(() => { if (alive) setJobsLoading(false); });
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
    setReport(undefined); setComparison(undefined); setDetailError("");
    if (id) void assessmentApi.read(id).then(value => {
      if (alive) { setReport(value); setJob(value.job_posting_id); setSelectedApplicationIds([value.application_id]); }
    }).catch(e => { if (alive) setDetailError(e instanceof Error ? e.message : "Candidate details could not be loaded."); });
    else if (comparisonId) void assessmentApi.comparison(comparisonId).then(value => {
      if (alive) { setComparison(value); setJob(value.snapshot.assessments[0]?.job_posting_id); }
    }).catch(e => { if (alive) setDetailError(e instanceof Error ? e.message : "The comparison could not be loaded."); });
    return () => { alive = false; };
  }, [params.get("run"), params.get("comparison"), detailRetry, setSelectedApplicationIds]);
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
    if (!job || calculationLock.current) return;
    calculationLock.current = true;
    setBusy(true); setError(""); setReport(undefined); setComparison(undefined); setParams({ job: String(job) }); setSelectedApplicationIds([]);
    try { setRanking(await assessmentApi.calculate(job)); }
    catch (e) { setError(e instanceof Error ? e.message : "The ranking could not be calculated. Try again."); }
    finally { calculationLock.current = false; setBusy(false); }
  }
  function closeDetails() { setParams(job ? { job: String(job) } : {}); setSelectedApplicationIds([]); }
  const calculating = busy || ranking?.status === "processing";
  const detailsOpen = Boolean(Number(params.get("run")) || Number(params.get("comparison")));
  return <div className="mx-auto w-full max-w-6xl px-4 py-7 sm:px-6">
    <header className="mb-6"><h1 className="text-3xl font-bold tracking-tight text-slate-900">Candidate ranking</h1><p className="mt-2 text-sm text-slate-500">Compare CV and interview scores to see the final ranking.</p></header>
    {error ? <p role="alert" className="my-4 rounded-xl border border-rose-100 bg-rose-50 p-3 text-sm text-rose-800">{error}</p> : null}
    <section aria-label="Ranking settings" className="mb-5 rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-end gap-4 p-5">
        <label className="min-w-0 flex-[1_1_16rem] text-xs font-semibold text-slate-600">Job posting<StyledSelect label="Job posting" disabled={busy || jobsLoading} className="mt-2" value={job === undefined ? "" : String(job)} placeholder={jobsLoading ? "Loading jobs…" : "Select a job"}
          options={jobs.map(j => ({ value: String(j.id), label: j.title, description: `Posting #${j.id}` }))} onChange={value => {
            setJob(Number(value)); setReport(undefined); setComparison(undefined); setParams({ job: value }); setSelectedApplicationIds([]);
          }} /></label>
        <button className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400 disabled:shadow-none" disabled={calculating || !job || !ranking?.candidates.length} onClick={() => void calculate()}>
          <svg aria-hidden="true" className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M5 20V10m7 10V4m7 16v-7M3 20h18"/></svg>{calculating ? "Calculating…" : "Calculate final ranking"}</button>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-b-2xl border-t border-slate-100 bg-slate-50/60 px-5 py-3"><div className="flex flex-wrap items-center gap-2 text-xs"><span className="font-medium text-slate-500">Final score</span><span className="rounded-lg border border-blue-100 bg-blue-50 px-2 py-1 font-semibold text-blue-700">CV 50%</span><span aria-hidden="true" className="text-slate-400">+</span><span className="rounded-lg border border-violet-100 bg-violet-50 px-2 py-1 font-semibold text-violet-700">Interview 50%</span></div>
        <details className="text-xs text-slate-500"><summary className="w-fit cursor-pointer font-medium hover:text-blue-700">How scores work</summary><p className="mt-2 max-w-md leading-6">Final score = 50% CV score + 50% interview score. The interview score is the average of the scored questions. Unanswered questions score zero. Missing scores stay unranked.</p></details>
      </div>
    </section>
    {ranking ? <FinalRankingTable key={job} ranking={ranking} onDetails={(applicationId, assessmentId) => setParams({ job: String(job), application: String(applicationId), run: String(assessmentId) })} /> : jobsLoading || job && !error ? <section role="status" className="rounded-2xl border border-slate-200 bg-white px-5 py-12 text-center text-sm text-slate-500">Loading candidates…</section> : !jobs.length && !error ? <section className="rounded-2xl border border-slate-200 bg-white px-5 py-12 text-center"><h2 className="font-semibold text-slate-700">No job postings yet</h2><p className="mt-2 text-sm text-slate-500">Create a job posting to start comparing candidates.</p><Link className="mt-4 inline-flex rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white" to="/interviewer/jobs">Go to jobs</Link></section> : null}
    {detailsOpen ? <PreviewModal title={Number(params.get("comparison")) ? "Candidate comparison" : "Candidate assessment"} onClose={closeDetails}>
      {detailError ? <div><p role="alert" className="rounded-xl bg-rose-50 p-3 text-sm text-rose-800">{detailError}</p><button type="button" onClick={() => setDetailRetry(value => value + 1)} className="mt-3 rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold text-blue-700">Try again</button></div> : report ? <AssessmentView key={report.id} report={report} /> : comparison ? <ComparisonView value={comparison} /> : <p role="status" className="py-8 text-center text-sm text-slate-500">Loading candidate details…</p>}
    </PreviewModal> : null}
  </div>;
}
