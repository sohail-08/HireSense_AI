import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { apiRequest } from "../api/apiClient";
import { useSupervisor } from "../components/assistant/SupervisorProvider";
import { JobPostingSelect } from "../components/candidates/JobPostingSelect";
import { RankingPagination } from "../components/candidates/RankingPagination";
import { ErrorMessage } from "../components/common/ErrorMessage";
import { StyledSelect } from "../components/common/StyledSelect";
import { InterviewSchedulingPanel } from "../components/interviews/InterviewSchedulingPanel";
import { blocksInvitation, candidateSchedules, schedulingStatus, type CandidateSchedule, type SchedulingFilter } from "../components/interviews/schedulingStatus";
import { formatDateTime } from "../utils/dateTime";
import type { ScreeningJobOption } from "../types";

type Candidate = { id: number; application_id: number; candidate_name: string; rank: number | null; display_score: string };
type Ranking = { id: number; job_posting_id: number; status: string; results: Candidate[] };

export function ScheduleInterviewsPage() {
  const location = useLocation();
  const appliedSelection = useRef<string | undefined>(undefined);
  const [params] = useSearchParams();
  const requestedJob = Number(params.get("job"));
  const appliedJob = useRef(0);
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
  const [scheduleData, setScheduleData] = useState<{ jobId: number; items: CandidateSchedule[] }>();
  const [loadingSchedules, setLoadingSchedules] = useState(false);
  const [schedulesError, setSchedulesError] = useState<string>();
  const [scheduleReload, setScheduleReload] = useState(0);
  const [statusFilter, setStatusFilter] = useState<SchedulingFilter>("all");

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
    if (appliedJob.current !== requestedJob && jobs.some(job => job.id === requestedJob)) {
      appliedJob.current = requestedJob; setJobId(requestedJob);
    }
  }, [requestedJob, jobs]);

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
    let active = true;
    setSchedulesError(undefined); setLoadingSchedules(Boolean(jobId));
    if (jobId) void apiRequest<CandidateSchedule[]>(`/interviews/schedules?job_posting_id=${jobId}`).then(items => {
      if (!active) return;
      setScheduleData({ jobId, items });
      const current = candidateSchedules(items, jobId);
      setSelectedIds(ids => ids.filter(id => !current.has(id) || !blocksInvitation(current.get(id)!)));
    }).catch(error => { if (active) setSchedulesError(error instanceof Error ? error.message : "Could not load interview statuses."); })
      .finally(() => { if (active) setLoadingSchedules(false); });
    return () => { active = false; };
  }, [jobId, refreshVersion, reload, scheduleReload]);

  useEffect(() => { setStatusFilter("all"); setPage(1); }, [jobId]);
  useEffect(() => {
    const refresh = () => { if (!document.hidden && !schedulingBusy) setScheduleReload(value => value + 1); };
    window.addEventListener("focus", refresh);
    const timer = window.setInterval(refresh, 30000);
    return () => { window.removeEventListener("focus", refresh); window.clearInterval(timer); };
  }, [schedulingBusy]);

  useEffect(() => {
    setSelectedJobPostingId(jobId);
    return () => { setSelectedJobPostingId(undefined); setSelectedApplicationIds([]); };
  }, [jobId, setSelectedJobPostingId, setSelectedApplicationIds]);
  useEffect(() => { setSelectedApplicationIds(selectedIds); }, [selectedIds, setSelectedApplicationIds]);

  const activeRanking = ranking?.job_posting_id === jobId ? ranking : undefined;
  const ranked = activeRanking?.results.slice().sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity) || a.application_id - b.application_id) ?? [];
  const statusesKnown = scheduleData?.jobId === jobId && !!scheduleData && !schedulesError;
  const schedules = candidateSchedules(statusesKnown ? scheduleData.items : [], jobId ?? 0);
  const filtered = ranked.filter(candidate => !statusesKnown || statusFilter === "all" || schedulingStatus(schedules.get(candidate.application_id)).group === statusFilter);
  const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, pages);
  const visible = filtered.slice((currentPage - 1) * pageSize, currentPage * pageSize);
  const count = (group: SchedulingFilter) => ranked.filter(candidate => schedulingStatus(schedules.get(candidate.application_id)).group === group).length;
  const selectedJob = jobs.find(job => job.id === jobId);
  const canSchedule = activeRanking?.status === "completed" && ranked.some(candidate => candidate.rank !== null);

  // Apply only the latest chat-triggered navigation, after both async reads.
  // Polls/restored chat history must not overwrite manual checkbox changes.
  useEffect(() => {
    const selection = (location.state as { interviewSelection?: { job_posting_id: number; application_ids: number[] } } | null)?.interviewSelection;
    if (!selection || appliedSelection.current === location.key || selection.job_posting_id !== jobId
      || !activeRanking || !statusesKnown || loadingSchedules || loadingRanking) return;
    appliedSelection.current = location.key;
    const ids = selection.application_ids.filter(id => ranked.some(candidate => candidate.application_id === id && candidate.rank !== null)
      && (!schedules.has(id) || !blocksInvitation(schedules.get(id)!)));
    setSelectedIds(ids); setStatusFilter("all");
    const index = ranked.findIndex(candidate => ids.includes(candidate.application_id));
    setPage(index < 0 ? 1 : Math.floor(index / pageSize) + 1);
  }, [location.key, location.state, jobId, activeRanking, statusesKnown, loadingSchedules, loadingRanking, pageSize]);

  return <section className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6">
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div><h1 className="text-3xl font-bold tracking-tight">Schedule interviews</h1>
        <p className="mt-2 text-sm text-slate-600">Choose a job and candidates, then preview the times and invitation email.</p></div>
      <Link to="/interviewer/interviews" className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-blue-700 hover:bg-blue-50">View scheduled interviews</Link>
    </header>
    <ErrorMessage message={jobsError ?? rankingError ?? schedulesError} />
    {jobsError || rankingError || schedulesError ? <button type="button" onClick={() => setReload(value => value + 1)} className="mt-2 text-sm font-semibold text-blue-700">Try again</button> : null}
    <section id="interview-candidates" aria-labelledby="interview-candidates-title" className="workflow-section mt-5 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div><h2 id="interview-candidates-title" className="text-lg font-semibold">Choose candidates</h2><p className="mt-1 text-sm text-slate-500">Based on the latest saved CV ranking.</p></div>
        <div className="w-full sm:w-80"><JobPostingSelect jobs={jobs} value={jobId} loading={loadingJobs || schedulingBusy} onChange={setJobId} /></div>
      </div>
      {loadingRanking || loadingJobs ? <p role="status" className="mt-5 text-sm text-slate-500">Loading ranked candidates…</p> : rankingError ? null : canSchedule ? <>
        {selectedJob && selectedJob.pending_count > 0 ? <p className="mt-4 text-sm text-amber-800">Some CVs are waiting for screening. Update the ranking in <Link to="/interviewer/assessments" className="font-semibold underline">CV Screening</Link> to include them.</p> : null}
        <div className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-xl bg-slate-50 px-3 py-3">
          <div><p className="text-xs font-semibold text-slate-600">Interview scheduling</p><p className="mt-1 text-xs text-slate-500">{statusesKnown ? `${count("not_scheduled")} not scheduled · ${count("scheduled")} scheduled · ${count("completed")} completed` : loadingSchedules ? "Checking interview statuses…" : "Interview statuses unavailable. Retry before selecting candidates."}</p></div>
          <div className="w-full sm:w-52"><StyledSelect label="Interview status" value={statusFilter} disabled={schedulingBusy || !statusesKnown} onChange={value => { setStatusFilter(value as SchedulingFilter); setPage(1); }}
            options={[{ value: "all", label: "All candidates" }, { value: "not_scheduled", label: "Not scheduled" }, { value: "scheduled", label: "Already scheduled" }, { value: "completed", label: "Completed" }]} /></div>
        </div>
        <div className="mt-4 overflow-x-auto"><table className="w-full text-left text-sm"><caption className="sr-only">Ranked candidates for interview selection</caption>
          <thead className="border-b border-slate-200 text-xs text-slate-500"><tr>{["Select", "Rank", "Candidate", "CV score", "Interview status"].map(title => <th key={title} scope="col" className="px-2 py-3">{title}</th>)}</tr></thead>
          <tbody>{visible.map(candidate => {
            const schedule = schedules.get(candidate.application_id);
            const status = schedulingStatus(schedule);
            const blocked = !!schedule && blocksInvitation(schedule);
            return <tr key={candidate.id} className="border-b border-slate-100 last:border-0 hover:bg-blue-50/30">
            <td className="px-2 py-4"><input type="checkbox" aria-label={`Select ${candidate.candidate_name} for interview`} aria-describedby={blocked ? `interview-status-${candidate.application_id}` : undefined} disabled={schedulingBusy || loadingSchedules || !statusesKnown || candidate.rank === null || blocked} checked={!blocked && selectedIds.includes(candidate.application_id)} onChange={() => setSelectedIds(ids => ids.includes(candidate.application_id) ? ids.filter(id => id !== candidate.application_id) : [...ids, candidate.application_id])} /></td>
            <td className="px-2 py-4 font-semibold">{candidate.rank ?? "—"}</td><td className="px-2 py-4 font-medium">{candidate.candidate_name}</td><td className="px-2 py-4 font-semibold text-blue-700">{candidate.display_score}%</td>
            <td id={`interview-status-${candidate.application_id}`} className="min-w-48 px-2 py-4">{statusesKnown ? <>
              <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${status.style}`}>{status.label}</span>
              {schedule ? <><p className="mt-1.5 text-xs text-slate-500">{formatDateTime(schedule.start_utc, schedule.timezone)}</p>
                {blocked && ["failed", "uncertain", "pending"].includes(schedule.delivery_status) ? <p className="mt-1 text-xs text-amber-800">{schedule.delivery_in_flight ? "Invitation sending…" : schedule.delivery_status === "failed" ? "Invitation delivery failed" : schedule.delivery_status === "uncertain" ? "Invitation delivery uncertain" : "Invitation pending"}</p> : null}
                <Link to={`/interviews/${schedule.id}/console`} className="mt-1 inline-block text-xs font-semibold text-blue-700 hover:underline">View interview</Link></> : null}
            </> : <span className="text-xs text-slate-500">{loadingSchedules ? "Checking status…" : "Status unavailable"}</span>}</td>
          </tr>; })}{!visible.length ? <tr><td colSpan={5} className="px-2 py-8 text-center text-sm text-slate-500">No candidates match this interview status.</td></tr> : null}</tbody>
        </table></div>
        <RankingPagination count={filtered.length} page={currentPage} pageSize={pageSize} loading={schedulingBusy} selectedCount={selectedIds.length} onPage={setPage} onPageSize={size => { setPageSize(size); setPage(1); }} />
      </> : <div className="mt-5 rounded-xl bg-slate-50 p-4 text-sm text-slate-600">
        {!jobs.length ? "Create a job posting before scheduling interviews." : <>No ranked candidates are available for this job. Rank candidates in <Link className="font-semibold text-blue-700 underline" to="/interviewer/assessments">CV Screening</Link> first.</>}
      </div>}
    </section>
    {!loadingRanking && !loadingJobs && !rankingError && canSchedule && activeRanking && scheduleData?.jobId === jobId ? <InterviewSchedulingPanel key={`${jobId}-${activeRanking.id}`} jobId={jobId} rankingRunId={activeRanking.id} selectedIds={selectedIds} onBusyChange={setSchedulingBusy} onUpdated={() => setScheduleReload(value => value + 1)} /> : null}
  </section>;
}
