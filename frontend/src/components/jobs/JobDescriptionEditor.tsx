import { useEffect, useRef } from "react";
import type { JobDescriptionResponse } from "../../types";
import { DiscordJobPostPanel } from "./DiscordJobPostPanel";
import { JobDescriptionPreview } from "./JobDescriptionPreview";
import { jobStatusLabel, jobStatusStyle } from "./SavedJobsCards";

export function JobDescriptionEditor({ job, title, content, editing, busy, approving, onEdit, onCancel, onTitle, onContent, onSave, onApprove, onRevise, refreshKey }: {
  job: JobDescriptionResponse; title: string; content: string; editing: boolean; busy: boolean; approving: boolean;
  onEdit: () => void; onCancel: () => void; onTitle: (value: string) => void; onContent: (value: string) => void;
  onSave: () => void; onApprove: () => void; onRevise: () => void; refreshKey: number;
}) {
  const editable = job.status === "draft";
  const changed = title !== job.title || content !== job.content;
  const editButton = useRef<HTMLButtonElement>(null);
  const wasEditing = useRef(false);
  useEffect(() => {
    if (wasEditing.current && !editing) editButton.current?.focus();
    wasEditing.current = editing;
  }, [editing]);

  return <div id="job-description-review" className="workflow-section space-y-5">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${jobStatusStyle(job.status)}`}>{jobStatusLabel(job.status)}</span>
        <span className="text-xs text-slate-500">Version {job.version}</span>
        {changed ? <span role="status" className="rounded-full bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-800">Unsaved changes</span> : null}
      </div>
      {editable && !editing ? <button ref={editButton} type="button" disabled={busy || approving} onClick={onEdit} className="inline-flex min-h-10 items-center gap-2 rounded-xl border border-blue-200 bg-white px-4 py-2 text-sm font-semibold text-blue-700 hover:bg-blue-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:cursor-not-allowed disabled:opacity-50">
        <svg aria-hidden="true" className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="m16 3 5 5-12 12-6 1 1-6Z" strokeLinejoin="round" /><path d="m14 5 5 5" /></svg>Edit
      </button> : null}
      {job.status === "approved" ? <button type="button" disabled={busy || approving} onClick={onRevise} className="min-h-10 rounded-xl border border-blue-200 bg-blue-50 px-4 py-2 text-sm font-semibold text-blue-700 hover:bg-blue-100 disabled:opacity-50">{busy ? "Creating draft…" : "Edit as new draft"}</button> : null}
    </div>

    {editable && editing ? <section aria-label="Edit job description" className="rounded-2xl border border-blue-100 bg-slate-50/60 p-4 sm:p-5">
      <div className="mb-5"><h3 className="font-semibold text-slate-900">Edit job description</h3><p className="mt-1 text-xs leading-5 text-slate-500">Update the title or description, then save your changes.</p></div>
      <div><label htmlFor="jd-title" className="text-sm font-semibold text-slate-700">Job title</label><input id="jd-title" autoFocus value={title} disabled={busy || approving} onChange={event => onTitle(event.target.value)} className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-base font-medium outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100 disabled:opacity-60" /></div>
      <div className="mt-5"><label htmlFor="jd-content" className="text-sm font-semibold text-slate-700">Job description</label><textarea id="jd-content" value={content} disabled={busy || approving} onChange={event => onContent(event.target.value)} rows={18} className="mt-2 min-h-80 w-full resize-y rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm leading-7 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100 disabled:opacity-60" /></div>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button type="button" disabled={busy || approving || !changed || !title.trim() || !content.trim()} onClick={onSave} className="min-h-10 rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50">{busy && !approving ? "Saving…" : "Save changes"}</button>
        <button type="button" disabled={busy || approving} onClick={onCancel} className="min-h-10 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50">Cancel</button>
      </div>
    </section> : <JobDescriptionPreview title={job.title} content={job.content} />}

    {editable ? <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4">
      <p className="text-xs text-slate-500">{changed ? "Save changes before approving." : "Ready to use this job description?"}</p>
      <button type="button" disabled={busy || approving || changed} onClick={onApprove} className="min-h-10 rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50">{approving ? "Approving…" : "Approve job description"}</button>
    </div> : null}
    {job.status === "approved" ? <DiscordJobPostPanel key={job.id} jobDescription={job} refreshKey={refreshKey} /> : null}
    {job.source_references.length ? <details className="rounded-xl border border-slate-200 px-4 py-3"><summary className="cursor-pointer text-sm font-semibold text-slate-600">Reference documents</summary><ul className="mt-3 space-y-2">{[...new Set(job.source_references.map(source => source.document_title))].map(name => <li key={name} className="rounded-lg bg-sky-50 px-3 py-2 text-sm text-sky-800">{name}</li>)}</ul></details> : null}
  </div>;
}
