import { useEffect, useMemo, useState } from "react";

import { ApiError, apiRequest } from "../api/apiClient";
import { ErrorMessage } from "../components/common/ErrorMessage";
import type {
  RankingItem,
  RequirementMatchResult,
  ScreeningBatch,
  ScreeningDashboard,
  ScreeningJobOption,
  ScreeningRunDetail,
  ScreeningRunStatus,
} from "../types";


function messageFor(error: unknown): string {
  return error instanceof ApiError
    ? error.message
    : "The screening request failed. Please try again.";
}

function statusStyle(status: ScreeningRunStatus | ScreeningBatch["status"]) {
  if (status === "completed") return "bg-emerald-100 text-emerald-700";
  if (status === "processing" || status === "queued") {
    return "bg-blue-100 text-blue-700";
  }
  if (status === "review_required" || status === "completed_with_errors") {
    return "bg-amber-100 text-amber-800";
  }
  if (status === "failed") return "bg-red-100 text-red-700";
  return "bg-slate-100 text-slate-600";
}

function matchStyle(status: RequirementMatchResult["status"]) {
  if (status === "met") return "bg-emerald-100 text-emerald-700";
  if (status === "partially_met") return "bg-amber-100 text-amber-800";
  if (status === "unmet") return "bg-red-100 text-red-700";
  return "bg-slate-200 text-slate-700";
}

function RankingCard({
  item,
  onInspect,
}: {
  item: RankingItem;
  onInspect: (runId: number) => void;
}) {
  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-wide text-blue-600">
            Rank {item.rank}
          </p>
          <h3 className="mt-1 truncate text-lg font-semibold text-slate-900">
            {item.candidate_name}
          </h3>
          <p className="truncate text-sm text-slate-500">
            {item.candidate_email ?? `Application #${item.application_id}`}
          </p>
        </div>
        <div className="text-right">
          <p className="text-2xl font-bold text-blue-700">
            {item.requirement_coverage?.toFixed(1)}%
          </p>
          <p className="text-xs text-slate-500">requirement coverage</p>
        </div>
      </div>
      <div className="mt-4 grid grid-cols-4 gap-2 text-center text-xs">
        <div className="rounded-lg bg-emerald-50 p-2 text-emerald-700">
          <strong className="block text-base">{item.met_count}</strong>Met
        </div>
        <div className="rounded-lg bg-amber-50 p-2 text-amber-700">
          <strong className="block text-base">{item.partially_met_count}</strong>Partial
        </div>
        <div className="rounded-lg bg-red-50 p-2 text-red-700">
          <strong className="block text-base">{item.unmet_count}</strong>Unmet
        </div>
        <div className="rounded-lg bg-slate-100 p-2 text-slate-700">
          <strong className="block text-base">{item.uncertain_count}</strong>Uncertain
        </div>
      </div>
      {item.suitability_summary ? (
        <p className="mt-4 text-sm leading-6 text-slate-600">
          {item.suitability_summary}
        </p>
      ) : null}
      <button
        type="button"
        onClick={() => onInspect(item.screening_run_id)}
        className="mt-4 text-sm font-semibold text-blue-700 hover:underline"
      >
        Inspect evidence and extracted CV
      </button>
    </article>
  );
}

export function ScreeningPage() {
  const [jobs, setJobs] = useState<ScreeningJobOption[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<number>();
  const [dashboard, setDashboard] = useState<ScreeningDashboard>();
  const [selectedApplications, setSelectedApplications] = useState<number[]>([]);
  const [batch, setBatch] = useState<ScreeningBatch>();
  const [detail, setDetail] = useState<ScreeningRunDetail>();
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string>();

  async function loadJobs() {
    const items = await apiRequest<ScreeningJobOption[]>("/screening/jobs");
    setJobs(items);
    setSelectedJobId((current) => current ?? items[0]?.id);
  }

  async function loadDashboard(jobId: number) {
    const value = await apiRequest<ScreeningDashboard>(`/screening/jobs/${jobId}`);
    setDashboard(value);
    setSelectedApplications((current) =>
      current.filter((id) => value.applications.some((item) => item.id === id)),
    );
  }

  useEffect(() => {
    loadJobs()
      .catch((requestError) => setError(messageFor(requestError)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selectedJobId) {
      setDashboard(undefined);
      return;
    }
    setError(undefined);
    void loadDashboard(selectedJobId).catch((requestError) =>
      setError(messageFor(requestError)),
    );
  }, [selectedJobId]);

  useEffect(() => {
    if (!batch || !["queued", "processing"].includes(batch.status)) return;
    const timer = window.setInterval(() => {
      void apiRequest<ScreeningBatch>(`/screening/batches/${batch.id}`)
        .then(async (next) => {
          setBatch(next);
          if (!["queued", "processing"].includes(next.status)) {
            window.clearInterval(timer);
            await Promise.all([
              loadJobs(),
              loadDashboard(next.job_posting_id),
            ]);
          }
        })
        .catch((requestError) => setError(messageFor(requestError)));
    }, 2000);
    return () => window.clearInterval(timer);
  }, [batch?.id, batch?.status]);

  const pendingIds = useMemo(
    () =>
      dashboard?.applications
        .filter((item) => item.screening_status === "pending")
        .map((item) => item.id) ?? [],
    [dashboard],
  );

  async function startBatch(applicationIds: number[] | null) {
    if (!selectedJobId || starting) return;
    setStarting(true);
    setError(undefined);
    try {
      const value = await apiRequest<ScreeningBatch>("/screening/batches", {
        method: "POST",
        body: JSON.stringify({
          job_posting_id: selectedJobId,
          application_ids: applicationIds,
        }),
      });
      setBatch(value);
      setSelectedApplications([]);
    } catch (requestError) {
      setError(messageFor(requestError));
    } finally {
      setStarting(false);
    }
  }

  async function retryBatch() {
    if (!batch || starting) return;
    setStarting(true);
    setError(undefined);
    try {
      setBatch(
        await apiRequest<ScreeningBatch>(
          `/screening/batches/${batch.id}/retry`,
          { method: "POST" },
        ),
      );
    } catch (requestError) {
      setError(messageFor(requestError));
    } finally {
      setStarting(false);
    }
  }

  async function inspectRun(runId: number) {
    setError(undefined);
    try {
      setDetail(await apiRequest<ScreeningRunDetail>(`/screening/runs/${runId}`));
    } catch (requestError) {
      setError(messageFor(requestError));
    }
  }

  function toggleApplication(applicationId: number) {
    setSelectedApplications((current) =>
      current.includes(applicationId)
        ? current.filter((id) => id !== applicationId)
        : [...current, applicationId],
    );
  }

  return (
    <section className="mx-auto w-full max-w-7xl px-4 py-8 sm:px-6">
      <p className="text-sm font-semibold uppercase tracking-wide text-blue-600">
        F1 · CV screening and ranking
      </p>
      <h1 className="mt-1 text-3xl font-bold tracking-tight text-slate-900">
        Candidate requirement coverage
      </h1>
      <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
        Process the CVs already collected for one job, inspect source-backed
        requirement matches, and compare candidates using deterministic coverage.
      </p>

      <ErrorMessage message={error} />

      <section className="mt-7 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <label htmlFor="screening-job" className="text-sm font-semibold text-slate-800">
          Job posting
        </label>
        <select
          id="screening-job"
          value={selectedJobId ?? ""}
          onChange={(event) => {
            setSelectedJobId(Number(event.target.value));
            setSelectedApplications([]);
            setBatch(undefined);
            setDetail(undefined);
          }}
          className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm sm:max-w-xl"
        >
          {jobs.map((job) => (
            <option key={job.id} value={job.id}>
              {job.title} · {job.application_count} applications · {job.pending_count} pending
            </option>
          ))}
        </select>

        {batch ? (
          <div className="mt-4 rounded-xl border border-blue-100 bg-blue-50 p-4 text-sm text-blue-950">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="font-semibold">Batch #{batch.id}</p>
              <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${statusStyle(batch.status)}`}>
                {batch.status.replaceAll("_", " ")}
              </span>
            </div>
            <p className="mt-2">
              Processed {batch.processed_applications}/{batch.total_applications} · {batch.successful_applications} completed · {batch.review_applications} review · {batch.failed_applications} failed
            </p>
            {batch.error_message ? <p className="mt-2 text-red-700">{batch.error_message}</p> : null}
            {(batch.review_applications > 0 || batch.failed_applications > 0) && !["queued", "processing"].includes(batch.status) ? (
              <button
                type="button"
                onClick={() => void retryBatch()}
                disabled={starting}
                className="mt-3 rounded-lg border border-blue-300 bg-white px-3 py-2 font-semibold text-blue-700 disabled:opacity-50"
              >
                Retry failed and review-required applications
              </button>
            ) : null}
          </div>
        ) : null}
      </section>

      <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="font-semibold text-slate-900">Collected applications</h2>
            <p className="mt-1 text-sm text-slate-500">
              Select specific applications, or process every pending CV.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void startBatch(selectedApplications)}
              disabled={!selectedApplications.length || starting}
              className="rounded-xl border border-blue-300 px-4 py-2 text-sm font-semibold text-blue-700 disabled:opacity-40"
            >
              Screen selected ({selectedApplications.length})
            </button>
            <button
              type="button"
              onClick={() => void startBatch(null)}
              disabled={!pendingIds.length || starting}
              className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:bg-slate-300"
            >
              Screen all pending ({pendingIds.length})
            </button>
          </div>
        </div>

        {loading ? (
          <p className="mt-5 text-sm text-slate-500">Loading applications…</p>
        ) : dashboard?.applications.length ? (
          <div className="mt-5 overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-sm">
              <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-3 py-3">Select</th>
                  <th className="px-3 py-3">Candidate</th>
                  <th className="px-3 py-3">CV</th>
                  <th className="px-3 py-3">Status</th>
                  <th className="px-3 py-3">Coverage</th>
                  <th className="px-3 py-3">Result</th>
                </tr>
              </thead>
              <tbody>
                {dashboard.applications.map((application) => (
                  <tr key={application.id} className="border-b border-slate-100">
                    <td className="px-3 py-3">
                      <input
                        type="checkbox"
                        checked={selectedApplications.includes(application.id)}
                        onChange={() => toggleApplication(application.id)}
                        aria-label={`Select ${application.candidate_name}`}
                      />
                    </td>
                    <td className="px-3 py-3">
                      <p className="font-medium text-slate-900">{application.candidate_name}</p>
                      <p className="text-xs text-slate-500">{application.candidate_email ?? `Application #${application.id}`}</p>
                    </td>
                    <td className="max-w-56 truncate px-3 py-3 text-slate-600">
                      {application.cv_filename ?? "Missing CV"}
                    </td>
                    <td className="px-3 py-3">
                      <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${statusStyle(application.screening_status)}`}>
                        {application.screening_status.replaceAll("_", " ")}
                      </span>
                      {application.error_message ? <p className="mt-1 max-w-72 text-xs text-red-600">{application.error_message}</p> : null}
                    </td>
                    <td className="px-3 py-3 font-semibold text-slate-800">
                      {application.requirement_coverage === null ? "—" : `${application.requirement_coverage.toFixed(1)}%`}
                    </td>
                    <td className="px-3 py-3">
                      {application.screening_run_id ? (
                        <button
                          type="button"
                          onClick={() => void inspectRun(application.screening_run_id!)}
                          className="font-semibold text-blue-700 hover:underline"
                        >
                          Inspect
                        </button>
                      ) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="mt-5 rounded-xl bg-slate-50 p-5 text-sm text-slate-500">
            This job posting has no collected applications.
          </p>
        )}
      </section>

      <section className="mt-6">
        <div className="flex items-end justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold text-slate-900">Semantic ranking</h2>
            <p className="mt-1 text-sm text-slate-500">
              Coverage is not a hiring-success probability. Ties share the same rank.
            </p>
          </div>
          {dashboard?.ranking.created_at ? (
            <p className="text-xs text-slate-500">
              Snapshot {new Date(dashboard.ranking.created_at).toLocaleString()}
            </p>
          ) : null}
        </div>
        {dashboard?.ranking.ranked.length ? (
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            {dashboard.ranking.ranked.map((item) => (
              <RankingCard key={item.application_id} item={item} onInspect={inspectRun} />
            ))}
          </div>
        ) : (
          <p className="mt-4 rounded-xl border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-500">
            No current candidates have completed reliable screening yet.
          </p>
        )}

        {dashboard?.ranking.review.length ? (
          <div className="mt-6 rounded-2xl border border-amber-200 bg-amber-50 p-5">
            <h3 className="font-semibold text-amber-950">Manual review required</h3>
            <div className="mt-3 space-y-2">
              {dashboard.ranking.review.map((item) => (
                <div key={item.application_id} className="flex items-center justify-between rounded-xl bg-white px-4 py-3 text-sm">
                  <span className="font-medium text-slate-900">{item.candidate_name}</span>
                  <button type="button" onClick={() => void inspectRun(item.screening_run_id)} className="font-semibold text-amber-800 hover:underline">
                    Inspect issue
                  </button>
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </section>

      {detail ? (
        <section className="mt-6 rounded-2xl border border-blue-200 bg-white p-5 shadow-sm">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-xl font-semibold text-slate-900">Screening evidence</h2>
              <p className="mt-1 text-sm text-slate-500">
                Run #{detail.id} · {detail.calculation_version} · {detail.model_name ?? "No model"}
              </p>
            </div>
            <button type="button" onClick={() => setDetail(undefined)} className="text-sm font-semibold text-slate-600 hover:text-slate-900">
              Close
            </button>
          </div>
          {detail.error_message ? <p className="mt-4 rounded-xl bg-red-50 p-3 text-sm text-red-700">{detail.error_message}</p> : null}
          {detail.extracted_profile ? (
            <details className="mt-4 rounded-xl border border-slate-200 p-4">
              <summary className="cursor-pointer font-semibold text-slate-900">Structured CV information</summary>
              <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap text-xs text-slate-700">{JSON.stringify(detail.extracted_profile, null, 2)}</pre>
            </details>
          ) : null}
          <div className="mt-5 space-y-4">
            {detail.matches.map((match) => (
              <article key={match.requirement_key} className="rounded-xl border border-slate-200 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="font-semibold text-slate-900">{match.name}</h3>
                  <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${matchStyle(match.status)}`}>
                    {match.status.replaceAll("_", " ")} · weight {match.weight}
                  </span>
                </div>
                <p className="mt-2 text-sm leading-6 text-slate-600">{match.explanation}</p>
                {match.evidence.map((evidence, index) => (
                  <blockquote key={`${evidence.block_id}-${index}`} className="mt-3 border-l-4 border-blue-300 bg-blue-50 px-4 py-3 text-sm text-slate-700">
                    “{evidence.quote}”
                    <footer className="mt-1 text-xs font-semibold text-blue-700">{evidence.locator}</footer>
                  </blockquote>
                ))}
                {match.evidence_gaps.length ? (
                  <p className="mt-3 text-xs text-amber-800">Evidence gap: {match.evidence_gaps.join("; ")}</p>
                ) : null}
              </article>
            ))}
          </div>
        </section>
      ) : null}
    </section>
  );
}
