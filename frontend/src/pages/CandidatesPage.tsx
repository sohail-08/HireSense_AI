import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiRequest } from "../api/apiClient";
import { ErrorMessage } from "../components/common/ErrorMessage";
import { StyledSelect } from "../components/common/StyledSelect";
import { useSupervisor } from "../components/assistant/SupervisorProvider";
import { notifyApplicationsChanged } from "../components/common/applicationNotificationEvents";
import { CandidateDetailsModal } from "../components/candidates/CandidateDetailsModal";
import { DeleteApplicationsModal } from "../components/candidates/DeleteApplicationsModal";
import { applicationStatuses, candidateDate } from "../components/candidates/candidateDisplay";
import type { CandidateApplicationSummary, CandidateJobPostingOption, GoogleFormsConfiguration, GoogleFormsSyncResult } from "../types";

const pageSizes = [5, 10, 20, 50];
function message(error: unknown): string {
  return error instanceof Error ? error.message : "The request failed. Please try again.";
}

export function CandidatesPage() {
  const { refreshVersion, response } = useSupervisor();
  const [configuration, setConfiguration] = useState<GoogleFormsConfiguration>();
  const [postings, setPostings] = useState<CandidateJobPostingOption[]>([]);
  const [applications, setApplications] = useState<CandidateApplicationSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string>();
  const [setupError, setSetupError] = useState<string>();
  const [syncing, setSyncing] = useState(false);
  const [deletingId, setDeletingId] = useState<number>();
  const [syncResult, setSyncResult] = useState<GoogleFormsSyncResult>();
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const [search, setSearch] = useState("");
  const [jobFilter, setJobFilter] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [selectedId, setSelectedId] = useState<number>();
  const [selecting, setSelecting] = useState(false);
  const [checked, setChecked] = useState<number[]>([]);
  const [deleteIds, setDeleteIds] = useState<number[]>([]);
  const [bulkDeleting, setBulkDeleting] = useState(false);
  const deleteTrigger = useRef<HTMLElement | null>(null);
  const deleteBusy = useRef(false);
  const selectAll = useRef<HTMLInputElement>(null);
  const inspectTrigger = useRef<HTMLElement | null>(null);
  const listRequest = useRef(0);
  const syncBusy = useRef(false);

  const refreshApplications = useCallback(async () => {
    const request = ++listRequest.current;
    setLoadError(undefined);
    try {
      const items = await apiRequest<CandidateApplicationSummary[]>("/candidates/applications");
      if (request === listRequest.current) setApplications(items);
    } catch (failure) {
      if (request === listRequest.current) setLoadError(message(failure));
    } finally { if (request === listRequest.current) setLoading(false); }
  }, []);

  useEffect(() => {
    void refreshApplications();
    return () => { listRequest.current += 1; };
  }, [refreshVersion, refreshApplications]);

  useEffect(() => {
    let active = true;
    setSetupError(undefined);
    // Form setup must never block the collected-candidate list.
    void apiRequest<GoogleFormsConfiguration>("/candidates/google-forms/configuration")
      .then(value => { if (active) setConfiguration(value); })
      .catch(() => { if (active) setSetupError("Application collection settings are unavailable. Your saved candidates are still available."); });
    void apiRequest<CandidateJobPostingOption[]>("/candidates/job-postings")
      .then(items => { if (active) setPostings(items); })
      .catch(() => { if (active) setSetupError("Job posting settings could not be loaded. You can still browse saved applications."); });
    return () => { active = false; };
  }, [refreshVersion]);

  useEffect(() => { if (response?.sync_result) setSyncResult(response.sync_result); }, [response]);

  const jobs = useMemo(() => {
    const options = new Map(postings.map(posting => [posting.id, posting.title]));
    applications.forEach(application => options.set(application.job_posting_id, application.job_title));
    return Array.from(options, ([id, title]) => ({ id, title })).sort((a, b) => a.title.localeCompare(b.title) || a.id - b.id);
  }, [postings, applications]);
  const filtered = useMemo(() => {
    const query = search.trim().toLocaleLowerCase();
    return applications.filter(application => (!jobFilter || application.job_posting_id === Number(jobFilter)) &&
      (!query || [application.candidate.name, application.candidate.email, application.candidate.phone, application.job_title]
        .some(value => value?.toLocaleLowerCase().includes(query))));
  }, [applications, jobFilter, search]);
  const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, pages);
  useEffect(() => { setPage(value => Math.min(value, pages)); }, [pages]);
  const pageNumbers = pages <= 7 ? Array.from({ length: pages }, (_, index) => index + 1)
    : [1, ...Array.from({ length: 3 }, (_, index) => Math.max(2, Math.min(currentPage - 1, pages - 3)) + index), pages];
  const start = (currentPage - 1) * pageSize;
  const visible = filtered.slice(start, start + pageSize);
  const selected = applications.find(application => application.id === selectedId);
  const closeDetails = useCallback(() => setSelectedId(undefined), []);
  const closeDelete = useCallback(() => setDeleteIds([]), []);
  const checkedIds = checked.filter(id => applications.some(application => application.id === id));
  const allVisibleChecked = visible.length > 0 && visible.every(application => checkedIds.includes(application.id));
  useEffect(() => {
    if (selectAll.current) selectAll.current.indeterminate = !allVisibleChecked && visible.some(application => checkedIds.includes(application.id));
  });

  function requestDelete(ids: number[], trigger: HTMLElement) {
    deleteTrigger.current = trigger; setDeleteIds(ids);
  }
  async function deleteSelected() {
    if (deleteBusy.current) return;
    deleteBusy.current = true; setBulkDeleting(true); setNotice(undefined);
    try {
      const result = await apiRequest<{ deleted_application_ids: number[]; deleted_count: number }>("/candidates/applications/bulk-delete",
        { method: "POST", body: JSON.stringify({ application_ids: deleteIds }) });
      ++listRequest.current;
      setApplications(items => items.filter(item => !result.deleted_application_ids.includes(item.id)));
      setChecked(ids => ids.filter(id => !result.deleted_application_ids.includes(id)));
      setDeleteIds([]); notifyApplicationsChanged();
      setNotice(`${result.deleted_count} application${result.deleted_count === 1 ? "" : "s"} deleted.`);
    } finally { deleteBusy.current = false; setBulkDeleting(false); }
  }

  async function syncResponses() {
    if (syncBusy.current) return;
    syncBusy.current = true;
    setSyncing(true); setError(undefined); setNotice(undefined); setSyncResult(undefined);
    try {
      const result = await apiRequest<GoogleFormsSyncResult>("/candidates/google-forms/sync", { method: "POST", body: JSON.stringify({}) });
      setSyncResult(result); notifyApplicationsChanged();
      await refreshApplications();
    } catch (failure) { setError(message(failure)); }
    finally { syncBusy.current = false; setSyncing(false); }
  }

  async function deleteApplication(application: CandidateApplicationSummary) {
    if (deletingId !== undefined) return;
    setDeletingId(application.id); setNotice(undefined);
    try {
      await apiRequest<void>(`/candidates/applications/${application.id}`, { method: "DELETE" });
      ++listRequest.current; // A stale refresh must not resurrect a deleted row.
      setApplications(items => items.filter(item => item.id !== application.id));
      setSelectedId(undefined); notifyApplicationsChanged();
      setNotice(`Application for ${application.candidate.name || "this candidate"} deleted.`);
    } catch (failure) { throw new Error(message(failure)); }
    finally { setDeletingId(undefined); }
  }

  function clearFilters() { setSearch(""); setJobFilter(""); setPage(1); setChecked([]); }
  const collectionReady = configuration?.configured && postings.length > 0;

  return <section className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6">
    <header className="flex flex-wrap items-center justify-between gap-4">
      <div><h1 className="text-3xl font-bold tracking-tight text-slate-900">Candidates</h1>
        <p className="mt-1 text-sm text-slate-500">Your applicants, their details and CVs — all in one place.</p></div>
      <div className="flex flex-wrap items-center gap-2">
        {configuration?.form_url ? <a href={configuration.form_url} target="_blank" rel="noopener noreferrer"
          className="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50">Application form <span aria-hidden="true">↗</span></a> : null}
        <button type="button" disabled={syncing || !collectionReady} onClick={() => void syncResponses()}
          title={!collectionReady ? "Application sync is unavailable. Check the Google Forms connection and job postings." : "Import new application responses"}
          className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm shadow-blue-600/15 hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:shadow-none">
          <svg aria-hidden="true" className={`h-4 w-4 ${syncing ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M20 7v5h-5M4 17v-5h5M6.5 6.5A8 8 0 0 1 20 12M4 12a8 8 0 0 0 13.5 5.5" /></svg>
          {syncing ? "Syncing…" : "Sync responses"}
        </button>
      </div>
    </header>
    <ErrorMessage message={error} />
    {setupError ? <p role="status" className="mt-3 text-sm text-amber-800">{setupError}</p> : null}
    {notice ? <p role="status" className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p> : null}
    {syncResult ? <div role="status" className="mt-4 rounded-xl border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-900">
      <p className="font-medium">{syncResult.imported_applications ? `${syncResult.imported_applications} new application(s) added.` : "No new applications found."} {syncResult.downloaded_cvs ? `${syncResult.downloaded_cvs} CV(s) saved.` : ""}</p>
      {syncResult.issues.length || syncResult.unmatched_responses || syncResult.reassigned_applications ? <details className="mt-1">
        <summary className="cursor-pointer text-blue-700">See sync details</summary>
        <p className="mt-2">{syncResult.skipped_existing} unchanged · {syncResult.reassigned_applications} reassigned · {syncResult.unmatched_responses} not matched to a job.</p>
        {syncResult.issues.length ? <ul className="mt-2 list-disc space-y-1 pl-5">{syncResult.issues.map((issue, index) => <li key={index}>Response {issue.row_number}: {issue.message}</li>)}</ul> : null}
      </details> : null}
    </div> : null}

    <section aria-labelledby="candidate-list-title" className="mt-5 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-100 p-4 sm:p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2"><div className="flex items-center gap-2">
          <h2 id="candidate-list-title" className="font-semibold text-slate-900">All candidates</h2>
          <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-semibold text-slate-600">{applications.length}</span></div>
          <div className="flex flex-wrap items-center gap-3">
            {selecting ? <><span role="status" className="text-xs text-slate-500">{checkedIds.length} selected · up to 100</span>
              <button type="button" disabled={!checkedIds.length || bulkDeleting} onClick={event => requestDelete(checkedIds, event.currentTarget)} className="rounded-lg bg-red-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40">Delete selected</button></> : null}
            <button type="button" disabled={bulkDeleting} aria-pressed={selecting} onClick={() => { setSelecting(value => !value); setChecked([]); }} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50">{selecting ? "Cancel selection" : "Select candidates"}</button>
          </div></div>
        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,220px)]">
          <label className="block text-xs font-medium text-slate-500" htmlFor="candidate-search">Search candidates
            <div className="relative mt-1.5"><svg aria-hidden="true" className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/></svg>
              <input id="candidate-search" type="search" value={search} onChange={event => { setSearch(event.target.value); setPage(1); setChecked([]); }} placeholder="Name, email or phone…"
                className="w-full rounded-xl border border-slate-200 bg-slate-50/60 py-2.5 pl-9 pr-3 text-sm text-slate-900 outline-none focus:border-blue-400 focus:bg-white focus:ring-2 focus:ring-blue-100" /></div>
          </label>
          <label className="block text-xs font-medium text-slate-500" htmlFor="candidate-job">Job posting
            <StyledSelect id="candidate-job" label="Job posting" value={jobFilter} className="mt-1.5"
              options={[{ value: "", label: "All job postings" }, ...jobs.map(job => ({ value: String(job.id), label: job.title, description: `Posting #${job.id}` }))]}
              onChange={value => { setJobFilter(value); setPage(1); setChecked([]); }} />
          </label>
        </div>
      </div>
      {loadError ? <div role="alert" className="m-5 rounded-xl bg-red-50 p-4 text-sm text-red-700">{loadError} <button type="button" onClick={() => void refreshApplications()} className="ml-2 font-semibold underline">Try again</button></div> : null}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">Candidate applications and job postings, newest first</caption>
          <thead className="border-b border-slate-200 bg-slate-50/70 text-xs font-semibold text-slate-500"><tr>
            {selecting ? <th scope="col" className="py-3 pl-5"><input ref={selectAll} type="checkbox" aria-label="Select all on this page" checked={allVisibleChecked} disabled={!visible.length || bulkDeleting} onChange={() => setChecked(allVisibleChecked ? checkedIds.filter(id => !visible.some(item => item.id === id)) : [...new Set([...checkedIds, ...visible.map(item => item.id)])].slice(0, 100))} className="h-4 w-4 accent-blue-600" /></th> : null}
            <th scope="col" className="py-3 pl-5 pr-3">#</th><th scope="col" className="px-3 py-3">Candidate</th><th scope="col" className="px-3 py-3">Job posting</th>
            <th scope="col" className="hidden px-3 py-3 xl:table-cell">Applied</th>
            <th scope="col" className="px-3 py-3">Status</th><th scope="col" className="py-3 pl-3 pr-5 text-right"><span className="sr-only">Actions</span></th>
          </tr></thead>
          <tbody className="divide-y divide-slate-100">
            {loading ? <tr><td colSpan={selecting ? 7 : 6} className="px-5 py-12 text-center text-slate-500" role="status">Loading candidates…</td></tr>
              : visible.map((application, index) => {
                const status = applicationStatuses[application.status] ?? applicationStatuses.received;
                const name = application.candidate.name || "Unnamed candidate";
                return <tr key={application.id} className="transition-colors hover:bg-blue-50/35">
                  {selecting ? <td className="py-4 pl-5"><input type="checkbox" aria-label={`Select ${name}`} checked={checkedIds.includes(application.id)} disabled={bulkDeleting || (!checkedIds.includes(application.id) && checkedIds.length >= 100)} onChange={() => setChecked(checkedIds.includes(application.id) ? checkedIds.filter(id => id !== application.id) : [...checkedIds, application.id])} className="h-4 w-4 accent-blue-600" /></td> : null}
                  <td className="py-4 pl-5 pr-3 text-slate-400">{start + index + 1}</td>
                  <td className="px-3 py-4"><div className="min-w-[120px] max-w-[230px]"><p className="truncate font-semibold text-slate-900" title={name}>{name}</p><p className="mt-1 truncate text-xs text-slate-500" title={application.candidate.email || undefined}>{application.candidate.email || "No email provided"}</p></div></td>
                  <td className="max-w-[190px] px-3 py-4"><p className="line-clamp-2 font-medium text-slate-700">{application.job_title}</p><p className="mt-1 text-xs text-slate-400">Posting #{application.job_posting_id}</p></td>
                  <td className="hidden whitespace-nowrap px-3 py-4 text-xs text-slate-500 xl:table-cell">{candidateDate(application.submitted_at)}</td>
                  <td className="px-3 py-4"><span className={`inline-flex whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${status.style}`}>{status.label}</span></td>
                  <td className="py-4 pl-3 pr-5 text-right"><button type="button" aria-label={`Inspect ${name}`} onClick={event => { inspectTrigger.current = event.currentTarget; setSelectedId(application.id); }}
                    className="rounded-lg border border-blue-100 bg-blue-50/70 px-3 py-2 text-xs font-semibold text-blue-700 hover:border-blue-200 hover:bg-blue-100 focus-visible:outline-2 focus-visible:outline-blue-600">Inspect</button>
                    <button type="button" aria-label={`Delete ${name}`} disabled={bulkDeleting} onClick={event => requestDelete([application.id], event.currentTarget)} className="ml-2 rounded-lg px-3 py-2 text-xs font-semibold text-red-600 hover:bg-red-50 disabled:opacity-50">Delete</button></td>
                </tr>;
              })}
            {!loading && !visible.length && !loadError ? <tr><td colSpan={selecting ? 7 : 6} className="px-5 py-12 text-center">
              <p className="font-semibold text-slate-700">{applications.length ? "No candidates match your filters" : "No candidates yet"}</p>
              <p className="mx-auto mt-2 max-w-sm text-sm text-slate-500">{applications.length ? "Try another job posting or search term." : "Sync responses to bring in new applications and their CVs."}</p>
              {search || jobFilter ? <button type="button" onClick={clearFilters} className="mt-4 text-sm font-semibold text-blue-700 hover:underline">Clear filters</button> : null}
            </td></tr> : null}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 bg-slate-50/40 px-5 py-3 text-xs text-slate-500">
        <p aria-live="polite">{filtered.length ? `${start + 1}–${Math.min(start + pageSize, filtered.length)} of ${filtered.length} application${filtered.length === 1 ? "" : "s"}` : "0 applications"}{(search || jobFilter) && filtered.length !== applications.length ? ` · ${applications.length} total` : ""}</p>
        <label className="flex items-center gap-2 text-slate-600" htmlFor="candidate-page-size">Candidates per page
          <StyledSelect id="candidate-page-size" label="Candidates per page" value={String(pageSize)} disabled={loading} compact className="w-20"
            options={pageSizes.map(size => ({ value: String(size), label: String(size) }))} onChange={value => { setPageSize(Number(value)); setPage(1); }} />
        </label>
        <nav aria-label="Candidate pages" className="flex flex-wrap items-center gap-2">
          <span className="mr-1">Page {currentPage} of {pages}</span>
          <button type="button" disabled={loading || currentPage === 1} onClick={() => setPage(currentPage - 1)} className="rounded-lg border border-slate-200 bg-white px-3 py-2 font-medium text-slate-600 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40">Previous</button>
          {pageNumbers.map((number, index) => <span key={number} className="hidden items-center gap-2 sm:inline-flex">
            {index > 0 && number - pageNumbers[index - 1] > 1 ? <span aria-hidden="true" className="px-1">…</span> : null}
            <button type="button" aria-label={`Go to page ${number}`} aria-current={number === currentPage ? "page" : undefined} disabled={loading} onClick={() => setPage(number)}
              className={`min-w-8 rounded-lg border px-2 py-2 font-semibold ${number === currentPage ? "border-blue-600 bg-blue-600 text-white" : "border-slate-200 bg-white text-slate-600 hover:bg-slate-100"}`}>{number}</button>
          </span>)}
          <button type="button" disabled={loading || currentPage === pages} onClick={() => setPage(currentPage + 1)} className="rounded-lg border border-slate-200 bg-white px-3 py-2 font-medium text-slate-600 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40">Next</button>
        </nav>
      </div>
    </section>

    {deleteIds.length ? <DeleteApplicationsModal count={deleteIds.length} busy={bulkDeleting} restoreFocus={deleteTrigger.current} onClose={closeDelete} onConfirm={deleteSelected} /> : null}
    {selected ? <CandidateDetailsModal key={selected.id} application={selected} deleting={deletingId === selected.id} restoreFocus={inspectTrigger.current}
      onClose={closeDetails} onDelete={() => deleteApplication(selected)} /> : null}
  </section>;
}
