import { useEffect, useState } from "react";

import { ApiError, apiRequest } from "../api/apiClient";
import { ErrorMessage } from "../components/common/ErrorMessage";
import type {
  CandidateApplicationSummary,
  CandidateJobPostingOption,
  GoogleFormsConfiguration,
  GoogleFormsSyncResult,
} from "../types";


function errorMessage(error: unknown): string {
  return error instanceof ApiError
    ? error.message
    : "The request failed. Please try again.";
}

function fileSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function CandidatesPage() {
  const [configuration, setConfiguration] =
    useState<GoogleFormsConfiguration>();
  const [postings, setPostings] = useState<CandidateJobPostingOption[]>([]);
  const [applications, setApplications] =
    useState<CandidateApplicationSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<GoogleFormsSyncResult>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    let active = true;
    Promise.all([
      apiRequest<GoogleFormsConfiguration>(
        "/candidates/google-forms/configuration",
      ),
      apiRequest<CandidateJobPostingOption[]>("/candidates/job-postings"),
      apiRequest<CandidateApplicationSummary[]>("/candidates/applications"),
    ])
      .then(([config, postingItems, applicationItems]) => {
        if (!active) return;
        setConfiguration(config);
        setPostings(postingItems);
        setApplications(applicationItems);
      })
      .catch((requestError) => {
        if (active) setError(errorMessage(requestError));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function refreshApplications() {
    const items = await apiRequest<CandidateApplicationSummary[]>(
      "/candidates/applications",
    );
    setApplications(items);
  }

  async function syncResponses() {
    if (syncing) return;
    setSyncing(true);
    setError(undefined);
    setSyncResult(undefined);
    try {
      const result = await apiRequest<GoogleFormsSyncResult>(
        "/candidates/google-forms/sync",
        {
          method: "POST",
          body: JSON.stringify({}),
        },
      );
      setSyncResult(result);
      await refreshApplications();
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setSyncing(false);
    }
  }

  return (
    <section className="mx-auto w-full max-w-7xl px-4 py-8 sm:px-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-wide text-blue-600">
            F1 · CV collection
          </p>
          <h1 className="mt-1 text-3xl font-bold tracking-tight text-slate-900">
            Candidates and CVs
          </h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
            Import Google Form responses, preserve candidate information, and
            securely store CVs for screening and ranking.
          </p>
        </div>
        {configuration?.form_url ? (
          <a
            href={configuration.form_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex w-fit rounded-xl border border-blue-300 bg-white px-4 py-2.5 text-sm font-semibold text-blue-700 transition hover:bg-blue-50"
          >
            Open application form
          </a>
        ) : null}
      </div>

      <ErrorMessage message={error} />

      <section className="mt-7 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h2 className="font-semibold text-slate-900">
              Google Forms response sync
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              Existing response rows are skipped automatically, so this action
              is safe to run again.
            </p>
          </div>
          <div className="flex w-full flex-col gap-3 sm:flex-row lg:w-auto">
            <button
              type="button"
              onClick={() => void syncResponses()}
              disabled={
                syncing ||
                postings.length === 0 ||
                !configuration?.configured
              }
              className="rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              {syncing ? "Syncing responses…" : "Sync responses"}
            </button>
          </div>
        </div>

        {!configuration?.configured && !loading ? (
          <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            Complete backend configuration: {configuration?.missing_settings.join(", ")}.
            The linked Sheet and Form upload folder must also be shared with the
            service-account email.
          </div>
        ) : null}

        {configuration ? (
          <div className="mt-4 rounded-xl border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-950">
            <p>
              Every response must contain the required Form field “
              {configuration.job_column}”. Use one of these posting values:
            </p>
            {postings.length ? (
              <ul className="mt-2 list-disc space-y-1 pl-5">
                {postings.map((posting) => (
                  <li key={posting.id}>
                    <span className="font-semibold">Post #{posting.id}</span>
                    {" — "}{posting.title}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 font-medium">
                Create a job posting before importing candidates.
              </p>
            )}
          </div>
        ) : null}

        {syncResult ? (
          <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
            Imported {syncResult.imported_applications} application(s) and {" "}
            {syncResult.downloaded_cvs} CV(s). Reassigned {" "}
            {syncResult.reassigned_applications} existing application(s) and skipped {" "}
            {syncResult.skipped_existing} unchanged response(s)
            {syncResult.unmatched_responses
              ? ` and ${syncResult.unmatched_responses} response(s) with an unknown or missing job`
              : ""}
            .
            {syncResult.issues.length ? (
              <details className="mt-2">
                <summary className="cursor-pointer font-semibold">
                  {syncResult.issues.length} import warning(s)
                </summary>
                <ul className="mt-2 list-disc space-y-1 pl-5">
                  {syncResult.issues.map((issue, index) => (
                    <li key={`${issue.row_number}-${index}`}>
                      Row {issue.row_number}: {issue.message}
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
          </div>
        ) : null}
      </section>

      <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-end justify-between gap-3">
          <div>
            <h2 className="font-semibold text-slate-900">Collected applications</h2>
            <p className="mt-1 text-sm text-slate-500">
              Candidate information and locally stored CV status.
            </p>
          </div>
          <span className="text-sm font-medium text-slate-500">
            {applications.length} collected
          </span>
        </div>

        {loading ? (
          <p className="mt-5 text-sm text-slate-500" role="status">
            Loading candidates…
          </p>
        ) : applications.length ? (
          <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {applications.map((application) => (
              <article
                key={application.id}
                className="rounded-2xl border border-slate-200 p-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="truncate font-semibold text-slate-900">
                      {application.candidate.name ?? "Unnamed candidate"}
                    </h3>
                    <p className="mt-1 truncate text-sm text-slate-600">
                      {application.candidate.email ?? "No email supplied"}
                    </p>
                  </div>
                  <span className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-semibold capitalize text-blue-700">
                    {application.status}
                  </span>
                </div>
                <dl className="mt-4 space-y-2 text-sm">
                  <div>
                    <dt className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                      Job
                    </dt>
                    <dd className="mt-0.5 text-slate-700">{application.job_title}</dd>
                  </div>
                  {application.candidate.phone ? (
                    <div>
                      <dt className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                        Phone
                      </dt>
                      <dd className="mt-0.5 text-slate-700">
                        {application.candidate.phone}
                      </dd>
                    </div>
                  ) : null}
                  <div>
                    <dt className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                      Submitted
                    </dt>
                    <dd className="mt-0.5 text-slate-700">
                      {new Date(application.submitted_at).toLocaleString()}
                    </dd>
                  </div>
                </dl>

                <div className="mt-4 border-t border-slate-200 pt-3">
                  {application.cv_documents.length ? (
                    <ul className="space-y-2">
                      {application.cv_documents.map((document) => (
                        <li key={document.id} className="text-sm">
                          <p className="truncate font-medium text-slate-800">
                            {document.original_filename}
                          </p>
                          <p className="mt-0.5 text-xs capitalize text-emerald-700">
                            {document.status} · {fileSize(document.file_size_bytes)} · stored locally
                          </p>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-sm text-amber-700">CV not available</p>
                  )}
                </div>
              </article>
            ))}
          </div>
        ) : (
          <p className="mt-5 rounded-xl bg-slate-50 px-4 py-6 text-sm text-slate-500">
            No applications have been imported yet.
          </p>
        )}
      </section>
    </section>
  );
}
