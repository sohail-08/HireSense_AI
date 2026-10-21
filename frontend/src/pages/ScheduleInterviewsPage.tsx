import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiRequest } from "../api/apiClient";
import { useSupervisor } from "../components/assistant/SupervisorProvider";
import { JobPostingSelect } from "../components/candidates/JobPostingSelect";
import { RankingPagination } from "../components/candidates/RankingPagination";
import { ErrorMessage } from "../components/common/ErrorMessage";
import { InterviewSchedulingPanel } from "../components/interviews/InterviewSchedulingPanel";
import type { ScreeningJobOption } from "../types";

type Candidate = { id: number; application_id: number; candidate_name: string; rank: number | null; display_score: string };
type Ranking = { id: number; job_posting_id: number; status: string; results: Candidate[] };

export function ScheduleInterviewsPage() {
  const { refreshVersion, setSelectedJobPostingId, setSelectedApplicationIds } = useSupervisor();
  const [jobs, setJobs] = useState<ScreeningJobOption[]>([]);
  const [jobId, setJobId] = useState<number>();
  const [ranking, setRanking] = useState<Ranking>();
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [loadingJobs, setLoadingJobs] = useState(true);
  const [loadingRanking, setLoadingRanking] = useState(false);
  const [jobsError, setJobsError] = useState<string>();
  const [rankingError, setRankingError] = useState<string>();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [reload, setReload] = useState(0);
  const [schedulingBusy, setSchedulingBusy] = useState(false);

  useEffect(() => {
    let active = true;
    setJobsError(undefined); setLoadingJobs(true);
    void apiRequest<ScreeningJobOption[]>("/screening/jobs").then(items => {
      if (!active) return;
      setJobs(items); setJobId(current => items.some(job => job.id === current) ? current : items[0]?.id);
    }).catch(error => { if (active) setJobsError(error instanceof Error ? error.message : "Could not load jobs."); })
      .finally(() => { if (active) setLoadingJobs(false); });
    return () => { active = false; };
  }, [refreshVersion, reload]);

  useEffect(() => {
    let active = true;
    setRanking(undefined); setSelectedIds([]); setRankingError(undefined); setPage(1); setLoadingRanking(Boolean(jobId));
    if (jobId) void apiRequest<{ id: number; status: string }[]>(`/scoring/jobs/${jobId}/runs`).then(async runs => {
      if (!active || !runs[0] || runs[0].status !== "completed") return;
      const saved = await apiRequest<Ranking>(`/scoring/runs/${runs[0].id}`);
      if (active) setRanking(saved);
    }).catch(error => { if (active) setRankingError(error instanceof Error ? error.message : "Could not load ranked candidates."); })
      .finally(() => { if (active) setLoadingRanking(false); });
    return () => { active = false; };
  }, [jobId, refreshVersion, reload]);

  useEffect(() => {
    setSelectedJobPostingId(jobId);
    return () => { setSelectedJobPostingId(undefined); setSelectedApplicationIds([]); };
  }, [jobId, setSelectedJobPostingId, setSelectedApplicationIds]);
  useEffect(() => { setSelectedApplicationIds(selectedIds); }, [selectedIds, setSelectedApplicationIds]);

  const activeRanking = ranking?.job_posting_id === jobId ? ranking : undefined;
  const ranked = activeRanking?.results.slice().sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity) || a.application_id - b.application_id) ?? [];
  const pages = Math.max(1, Math.ceil(ranked.length / pageSize));
  const currentPage = Math.min(page, pages);
  const visible = ranked.slice((currentPage - 1) * pageSize, currentPage * pageSize);
  const selectedJob = jobs.find(job => job.id === jobId);
  const canSchedule = activeRanking?.status === "completed" && ranked.some(candidate => candidate.rank !== null);

  return <section className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6">
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div><h1 className="text-3xl font-bold tracking-tight">Schedule interviews</h1>
        <p className="mt-2 text-sm text-slate-600">Choose a job and candidates, then preview the times and invitation email.</p></div>
      <Link to="/interviewer/interviews" className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-blue-700 hover:bg-blue-50">View scheduled interviews</Link>
    </header>
    <ErrorMessage message={jobsError ?? rankingError} />
    {jobsError || rankingError ? <button type="button" onClick={() => setReload(value => value + 1)} className="mt-2 text-sm font-semibold text-blue-700">Try again</button> : null}
    <section aria-labelledby="interview-candidates-title" className="mt-5 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div><h2 id="interview-candidates-title" className="text-lg font-semibold">Choose candidates</h2><p className="mt-1 text-sm text-slate-500">Based on the latest saved CV ranking.</p></div>
        <div className="w-full sm:w-80"><JobPostingSelect jobs={jobs} value={jobId} loading={loadingJobs || schedulingBusy} onChange={setJobId} /></div>
      </div>
      {loadingRanking || loadingJobs ? <p role="status" className="mt-5 text-sm text-slate-500">Loading ranked candidates…</p> : rankingError ? null : canSchedule ? <>
        {selectedJob && selectedJob.pending_count > 0 ? <p className="mt-4 text-sm text-amber-800">Some CVs are waiting for screening. Update the ranking in <Link to="/interviewer/assessments" className="font-semibold underline">CV Screening</Link> to include them.</p> : null}
        <div className="mt-4 overflow-x-auto"><table className="w-full text-left text-sm"><caption className="sr-only">Ranked candidates for interview selection</caption>
          <thead className="border-b border-slate-200 text-xs text-slate-500"><tr>{["Select", "Rank", "Candidate", "CV score"].map(title => <th key={title} scope="col" className="px-2 py-3">{title}</th>)}</tr></thead>
          <tbody>{visible.map(candidate => <tr key={candidate.id} className="border-b border-slate-100 last:border-0 hover:bg-blue-50/30">
            <td className="px-2 py-4"><input type="checkbox" aria-label={`Select ${candidate.candidate_name} for interview`} disabled={schedulingBusy || candidate.rank === null} checked={selectedIds.includes(candidate.application_id)} onChange={() => setSelectedIds(ids => ids.includes(candidate.application_id) ? ids.filter(id => id !== candidate.application_id) : [...ids, candidate.application_id])} /></td>
            <td className="px-2 py-4 font-semibold">{candidate.rank ?? "—"}</td><td className="px-2 py-4 font-medium">{candidate.candidate_name}</td><td className="px-2 py-4 font-semibold text-blue-700">{candidate.display_score}%</td>
          </tr>)}</tbody>
        </table></div>
        <RankingPagination count={ranked.length} page={currentPage} pageSize={pageSize} loading={schedulingBusy} selectedCount={selectedIds.length} onPage={setPage} onPageSize={size => { setPageSize(size); setPage(1); }} />
      </> : <div className="mt-5 rounded-xl bg-slate-50 p-4 text-sm text-slate-600">
        {!jobs.length ? "Create a job posting before scheduling interviews." : <>No ranked candidates are available for this job. Rank candidates in <Link className="font-semibold text-blue-700 underline" to="/interviewer/assessments">CV Screening</Link> first.</>}
      </div>}
    </section>
    {!loadingRanking && !loadingJobs && !rankingError && canSchedule && activeRanking ? <InterviewSchedulingPanel key={`${jobId}-${activeRanking.id}`} jobId={jobId} rankingRunId={activeRanking.id} selectedIds={selectedIds} onBusyChange={setSchedulingBusy} /> : null}
  </section>;
}
