import type { JobDescriptionResponse } from "../../types";
import { DiscordJobPostPanel } from "./DiscordJobPostPanel";
import { jobStatusLabel, jobStatusStyle } from "./SavedJobsCards";

export function JobDescriptionEditor({ job, title, content, busy, approving, onTitle, onContent, onSave, onApprove, onRevise, refreshKey }: {
  job: JobDescriptionResponse; title: string; content: string; busy: boolean; approving: boolean;
  onTitle: (value: string) => void; onContent: (value: string) => void;
  onSave: () => void; onApprove: () => void; onRevise: () => void; refreshKey: number;
}) {
  const editable = job.status === "draft";
  const changed = title !== job.title || content !== job.content;
  return <div className="space-y-5">
    <div className="flex flex-wrap items-center gap-2"><span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${jobStatusStyle(job.status)}`}>{jobStatusLabel(job.status)}</span><span className="text-xs text-slate-500">Version {job.version}</span>{changed ? <span role="status" className="text-xs font-medium text-amber-800">Unsaved changes</span> : null}</div>
    {editable ? <>
      <div><label htmlFor="jd-title" className="text-sm font-semibold text-slate-700">Job title</label><input id="jd-title" value={title} disabled={busy || approving} onChange={event => onTitle(event.target.value)} className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100 disabled:opacity-60" /></div>
      <div><label htmlFor="jd-content" className="text-sm font-semibold text-slate-700">Job description</label><textarea id="jd-content" value={content} disabled={busy || approving} onChange={event => onContent(event.target.value)} rows={14} className="mt-2 w-full resize-y rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm leading-7 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100 disabled:opacity-60" /></div>
      <div className="flex flex-wrap items-center gap-3"><button type="button" disabled={busy || approving || !changed || !title.trim() || !content.trim()} onClick={onSave} className="min-h-10 rounded-xl border border-blue-200 px-4 py-2 text-sm font-semibold text-blue-700 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50">{busy ? "Saving…" : "Save changes"}</button><button type="button" disabled={busy || approving || changed} onClick={onApprove} className="min-h-10 rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50">{approving ? "Approving…" : "Approve job description"}</button>{changed ? <p className="text-xs text-slate-500">Save changes before approving.</p> : null}</div>
    </> : <><div className="rounded-2xl border border-slate-100 bg-slate-50/60 p-5"><h3 className="break-words text-xl font-bold text-slate-800">{job.title}</h3><p className="mt-4 whitespace-pre-wrap text-sm leading-7 text-slate-700 [overflow-wrap:anywhere]">{job.content}</p></div>{job.status === "approved" ? <button type="button" disabled={busy || approving} onClick={onRevise} className="min-h-10 rounded-xl border border-blue-200 bg-blue-50 px-4 py-2 text-sm font-semibold text-blue-700 hover:bg-blue-100 disabled:opacity-50">{busy ? "Creating draft…" : "Edit as new draft"}</button> : null}</>}
    {job.status === "approved" ? <DiscordJobPostPanel key={job.id} jobDescription={job} refreshKey={refreshKey} /> : null}
    {job.source_references.length ? <details className="rounded-xl border border-slate-200 px-4 py-3"><summary className="cursor-pointer text-sm font-semibold text-slate-600">Reference documents</summary><ul className="mt-3 space-y-2">{[...new Set(job.source_references.map(source => source.document_title))].map(name => <li key={name} className="rounded-lg bg-sky-50 px-3 py-2 text-sm text-sky-800">{name}</li>)}</ul></details> : null}
  </div>;
}
