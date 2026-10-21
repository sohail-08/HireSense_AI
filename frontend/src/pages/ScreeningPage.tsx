import { useEffect, useRef, useState } from "react";

import { ApiError, apiRequest } from "../api/apiClient";
import { ErrorMessage } from "../components/common/ErrorMessage";
import { useSupervisor } from "../components/assistant/SupervisorProvider";
import { CandidateScoringPanel } from "../components/candidates/CandidateScoringPanel";
import type { ScreeningBatch, ScreeningDashboard, ScreeningJobOption } from "../types";

function messageFor(error: unknown): string {
  return error instanceof Error ? error.message : "Could not prepare the candidates. Please try again.";
}

export function ScreeningPage() {
  const { setSelectedJobPostingId, setSelectedApplicationIds, refreshVersion, batch: assistantBatch } = useSupervisor();
  const [jobs, setJobs] = useState<ScreeningJobOption[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<number>();
  const [dashboard, setDashboard] = useState<ScreeningDashboard>();
  const [batch, setBatch] = useState<ScreeningBatch>();
  const [loading, setLoading] = useState(true);
  const [preparing, setPreparing] = useState(false);
  const [error, setError] = useState<string>();
  const selectedJobRef = useRef(selectedJobId);
  const jobsRequest = useRef(0);
  const dashboardRequest = useRef(0);
  selectedJobRef.current = selectedJobId;

  async function loadJobs() {
    const request = ++jobsRequest.current;
    const items = await apiRequest<ScreeningJobOption[]>("/screening/jobs");
    if (request !== jobsRequest.current) return;
    setJobs(items);
    setSelectedJobId((current) => items.some((job) => job.id === current) ? current : items[0]?.id);
  }

  async function loadDashboard(jobId: number) {
    if (selectedJobRef.current !== jobId) return;
    const request = ++dashboardRequest.current;
    const value = await apiRequest<ScreeningDashboard>("/screening/jobs/" + jobId);
    if (selectedJobRef.current === jobId && request === dashboardRequest.current) setDashboard(value);
  }

  useEffect(() => {
    void loadJobs().catch((failure) => setError(messageFor(failure))).finally(() => setLoading(false));
    return () => { jobsRequest.current += 1; };
  }, []);

  useEffect(() => {
    setDashboard(undefined);
    setError(undefined);
    if (selectedJobId) void loadDashboard(selectedJobId).catch((failure) => {
      if (selectedJobRef.current === selectedJobId) setError(messageFor(failure));
    });
  }, [selectedJobId]);

  useEffect(() => {
    setSelectedJobPostingId(selectedJobId);
    setSelectedApplicationIds([]);
    return () => { setSelectedJobPostingId(undefined); setSelectedApplicationIds([]); };
  }, [selectedJobId, setSelectedJobPostingId, setSelectedApplicationIds]);

  useEffect(() => {
    if (assistantBatch) setBatch(assistantBatch);
  }, [assistantBatch]);

  useEffect(() => {
    if (!refreshVersion) return;
    void loadJobs().catch((failure) => setError(messageFor(failure)));
    if (selectedJobId) void loadDashboard(selectedJobId).catch((failure) => setError(messageFor(failure)));
  }, [refreshVersion]);

  useEffect(() => {
    if (!batch || batch.id === assistantBatch?.id || !["queued", "processing"].includes(batch.status)) return;
    let active = true;
    let polling = false;
    const timer = window.setInterval(() => {
      if (polling) return;
      polling = true;
      void apiRequest<ScreeningBatch>("/screening/batches/" + batch.id).then(async (next) => {
        if (!active) return;
        setBatch(next);
        if (!["queued", "processing"].includes(next.status)) {
          window.clearInterval(timer);
          await Promise.all([loadJobs(), loadDashboard(next.job_posting_id)]);
        }
      }).catch((failure) => { if (active) setError(messageFor(failure)); })
        .finally(() => { polling = false; });
    }, 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, [batch?.id, batch?.status, assistantBatch?.id]);

  async function screenPending() {
    if (!selectedJobId || preparing) throw new Error("Candidate processing is already starting. Please wait.");
    setPreparing(true);
    setError(undefined);
    try {
      const value = await apiRequest<ScreeningBatch>("/screening/batches", {
        method: "POST", body: JSON.stringify({ job_posting_id: selectedJobId, application_ids: null }),
      });
      setBatch(value);
      return true;
    } catch (failure) {
      // Another completed screening request can make the pending list stale.
      if (failure instanceof ApiError && failure.message.includes("already have current screening results")) {
        await loadDashboard(selectedJobId);
        return false;
      }
      throw failure;
    } finally { setPreparing(false); }
  }

  const currentBatch = batch?.job_posting_id === selectedJobId ? batch : undefined;
  const processing = preparing || Boolean(currentBatch && ["queued", "processing"].includes(currentBatch.status));
  const selectedJob = jobs.find((job) => job.id === selectedJobId);
  const activeDashboard = dashboard && dashboard.job_posting_id === selectedJobId ? dashboard : undefined;
  const failedApplications = activeDashboard?.applications.filter(application => application.screening_status === "failed") ?? [];
  const pendingCount = activeDashboard
    ? activeDashboard.applications.filter((application) => application.screening_status !== "completed").length
    : selectedJob?.pending_count ?? 0;
  const jobSelector = <div>
    <label htmlFor="screening-job" className="block text-xs font-semibold text-slate-600">Job posting</label>
    <select id="screening-job" value={selectedJobId ?? ""} disabled={loading || !jobs.length}
      onChange={event => setSelectedJobId(Number(event.target.value))}
      className="mt-1.5 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100">
      {!jobs.length ? <option value="">{loading ? "Loading jobs…" : "No job postings available"}</option> : null}
      {jobs.map(job => <option key={job.id} value={job.id}>{job.title + " · #" + job.id}</option>)}
    </select>
    {selectedJob ? <p className="mt-1.5 text-xs text-slate-500">{selectedJob.application_count} {selectedJob.application_count === 1 ? "candidate" : "candidates"}</p> : null}
  </div>;

  return (
    <section className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6">
      <h1 className="text-3xl font-bold tracking-tight text-slate-900">CV Screening</h1>
      <p className="mt-2 text-sm text-slate-600">Choose a job, adjust the weights, and compare candidates.</p>
      <ErrorMessage message={error} />

      {!selectedJobId ? <section className="mt-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        {jobSelector}
        {!loading && !jobs.length ? <p className="mt-3 text-sm text-slate-500">Create and approve a job description, then prepare a job posting to get started.</p> : null}
      </section> : null}

      {failedApplications.length ? <section role="status" className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
        <p>{failedApplications.length} CV(s) could not be processed. They have not been assigned a zero score. Fix the file or service issue, then retry.</p>
        <details className="mt-2"><summary className="cursor-pointer font-medium">See affected candidates</summary>
          <ul className="mt-2 list-disc space-y-2 pl-5">{failedApplications.map(application => <li key={application.id}><strong>{application.candidate_name}:</strong> {application.error_message || "CV screening could not finish. Please retry."}</li>)}</ul>
        </details>
      </section> : null}
      {selectedJobId ? <CandidateScoringPanel key={selectedJobId} jobId={selectedJobId}
        jobSelector={jobSelector}
        refreshToken={String(refreshVersion) + "-" + currentBatch?.id + "-" + currentBatch?.status}
        applicationCount={activeDashboard?.applications.length ?? selectedJob?.application_count ?? 0}
        pendingCount={pendingCount} processing={processing} ready={Boolean(activeDashboard)}
        processingError={currentBatch?.status === "failed" ? currentBatch.error_message ?? "Candidate processing failed. Please try again." : undefined}
        progress={currentBatch && processing ? currentBatch.processed_applications + " of " + currentBatch.total_applications + " CVs prepared" : undefined}
        onScreenPending={screenPending}
      /> : null}
    </section>
  );
}
