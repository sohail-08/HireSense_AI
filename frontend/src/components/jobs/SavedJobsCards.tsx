import { useState } from "react";
import type { JobDescriptionResponse } from "../../types";
import { formatDate, formatTime } from "../../utils/dateTime";
import { StyledSelect } from "../common/StyledSelect";

export const jobStatusStyle = (status: string) => status === "approved" ? "border-emerald-100 bg-emerald-50 text-emerald-800" : status === "draft" ? "border-amber-100 bg-amber-50 text-amber-800" : "border-slate-200 bg-slate-100 text-slate-600";
export const jobStatusLabel = (status: string) => status === "approved" ? "Approved" : status === "draft" ? "Draft" : "Archived";

export function SavedJobsCards({ jobs, loading, error, busy, onRetry, onOpen, onRevise, onDelete, onCreate }: {
  jobs: JobDescriptionResponse[]; loading: boolean; error?: string; busy: boolean; onRetry: () => void;
  onOpen: (job: JobDescriptionResponse) => void; onRevise: (job: JobDescriptionResponse) => void;
  onDelete: (job: JobDescriptionResponse) => void; onCreate: () => void;
}) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const filtered = jobs.filter(job => (!status || job.status === status) && job.title.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const current = Math.min(page, pages), start = (current - 1) * pageSize;
  const visible = filtered.slice(start, start + pageSize);
  const reset = () => { setSearch(""); setStatus(""); setPage(1); };
  return <section aria-label="Saved jobs" className="mt-6 min-w-0 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
    <header className="border-b border-slate-100 p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="flex items-center gap-2 font-semibold text-slate-800">Saved jobs<span className="rounded-full bg-blue-50 px-2.5 py-0.5 text-xs tabular-nums text-blue-700">{jobs.length}</span></h2><div className="flex gap-2 text-xs"><span className="rounded-lg bg-emerald-50 px-2.5 py-1 text-emerald-800">{jobs.filter(job => job.status === "approved").length} approved</span><span className="rounded-lg bg-amber-50 px-2.5 py-1 text-amber-800">{jobs.filter(job => job.status === "draft").length} {jobs.filter(job => job.status === "draft").length === 1 ? "draft" : "drafts"}</span></div></div>
      <div className="mt-4 grid gap-3 sm:grid-cols-[minmax(0,1fr)_12rem]">
        <div><label htmlFor="job-search" className="sr-only">Search jobs</label><div className="relative"><svg aria-hidden="true" className="pointer-events-none absolute top-3 left-3 h-4 w-4 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 4 4" /></svg><input id="job-search" type="search" placeholder="Search by job title…" value={search} onChange={event => { setSearch(event.target.value); setPage(1); }} className="min-h-11 w-full rounded-xl border border-slate-200 bg-slate-50/60 py-2.5 pr-3 pl-9 text-sm outline-none focus:border-blue-400 focus:bg-white focus:ring-2 focus:ring-blue-100" /></div></div>
        <StyledSelect label="Job status" value={status} onChange={value => { setStatus(value); setPage(1); }} options={[{ value: "", label: "All statuses" }, { value: "draft", label: "Draft" }, { value: "approved", label: "Approved" }, { value: "archived", label: "Archived" }]} />
      </div>
    </header>
    {loading ? <p role="status" className="p-10 text-center text-sm text-slate-500">Loading jobs…</p> : error ? <div role="alert" className="m-5 rounded-xl bg-rose-50 p-4 text-sm text-rose-800">{error}<button type="button" onClick={onRetry} className="ml-3 font-semibold underline">Try again</button></div> : !jobs.length ? <div className="px-5 py-12 text-center"><span aria-hidden="true" className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-blue-50 text-blue-600"><svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><rect x="3" y="7" width="18" height="14" rx="3" /><path d="M8 7V4h8v3M3 12h18M10 12v3h4v-3" /></svg></span><h3 className="mt-4 font-semibold text-slate-800">Create your first job</h3><p className="mt-2 text-sm text-slate-500">Write a job description yourself or create one with the assistant.</p><button type="button" disabled={busy} onClick={onCreate} className="mt-5 rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50">Get started</button></div> : !filtered.length ? <div className="p-10 text-center"><p className="text-sm text-slate-600">No jobs match your search.</p><button type="button" onClick={reset} className="mt-2 text-sm font-semibold text-blue-700 hover:underline">Clear filters</button></div> : <ul aria-label="Saved job cards" className="grid grid-cols-1 gap-4 p-4 md:grid-cols-2 2xl:grid-cols-3 sm:p-5">{visible.map(job => <li key={job.id} className="min-w-0">
      <article aria-labelledby={`job-card-${job.id}`} className="flex h-full min-w-0 flex-col rounded-2xl border border-slate-200 bg-white p-5 transition hover:border-blue-200 hover:shadow-md hover:shadow-blue-900/5">
        <div className="flex items-center justify-between gap-3"><span aria-hidden="true" className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 text-blue-600"><svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><rect x="3" y="7" width="18" height="14" rx="3" /><path d="M8 7V4h8v3M3 12h18M10 12v3h4v-3" /></svg></span><span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${jobStatusStyle(job.status)}`}>{jobStatusLabel(job.status)}</span></div>
        <h3 id={`job-card-${job.id}`} className="mt-4 break-words text-base font-semibold leading-6 text-slate-800">{job.title}</h3>
        <p className="mt-2 line-clamp-3 whitespace-pre-wrap break-words text-sm leading-6 text-slate-500">{job.structured_content.summary || job.content}</p>
        <div className="mt-auto pt-4"><div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500"><span className="rounded-md bg-slate-100 px-2 py-1 font-medium">Version {job.version}</span><span>Updated {formatDate(job.updated_at)}</span><span>{formatTime(job.updated_at)} · Dhaka time</span></div>
          <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-4">
            <button type="button" disabled={busy} onClick={() => onOpen(job)} aria-label={`${job.status === "draft" ? "Edit draft" : "View job"}: ${job.title}`} className="min-h-10 rounded-xl border border-blue-200 bg-blue-50/50 px-3 py-2 text-xs font-semibold text-blue-700 hover:bg-blue-100 disabled:opacity-50">{job.status === "draft" ? "Edit draft" : "View job"}</button>
            {job.status === "approved" ? <button type="button" disabled={busy} onClick={() => onRevise(job)} aria-label={`New draft: ${job.title}`} className="min-h-10 rounded-xl border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-50 disabled:opacity-50">New draft</button> : null}
            <button type="button" disabled={busy} onClick={() => onDelete(job)} aria-label={`Delete job: ${job.title}`} title="Delete job" className="ml-auto flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-rose-600 hover:bg-rose-50 focus-visible:outline-2 focus-visible:outline-rose-600 disabled:opacity-50"><svg aria-hidden="true" className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7" /></svg></button>
          </div>
        </div>
      </article>
    </li>)}</ul>}
    {!loading && !error && jobs.length ? <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-5 py-3 text-xs text-slate-500"><p aria-live="polite">{filtered.length ? `${start + 1}–${Math.min(start + pageSize, filtered.length)} of ${filtered.length} jobs` : "0 jobs"}</p><label className="flex items-center gap-2">Jobs per page<StyledSelect label="Jobs per page" compact value={String(pageSize)} onChange={value => { setPageSize(Number(value)); setPage(1); }} options={[5, 10, 20, 50].map(size => ({ value: String(size), label: String(size) }))} /></label><nav aria-label="Job pages" className="flex items-center gap-2"><span>Page {current} of {pages}</span><button type="button" disabled={current === 1} onClick={() => setPage(current - 1)} className="rounded-lg border border-slate-200 px-3 py-2 font-medium hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40">Previous</button><button type="button" disabled={current === pages} onClick={() => setPage(current + 1)} className="rounded-lg border border-slate-200 px-3 py-2 font-medium hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40">Next</button></nav></footer> : null}
  </section>;
}
