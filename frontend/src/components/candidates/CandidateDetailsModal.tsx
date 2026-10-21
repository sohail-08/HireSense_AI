import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { apiBlob } from "../../api/apiClient";
import type { CandidateApplicationSummary, CandidateCVDocument } from "../../types";
import { applicationStatuses, candidateDate, cvSize, safeCandidateWebsite } from "./candidateDisplay";

type Props = {
  application: CandidateApplicationSummary; deleting: boolean; restoreFocus: HTMLElement | null;
  onClose: () => void; onDelete: () => Promise<void>;
};

export function CandidateDetailsModal({ application, deleting, restoreFocus, onClose, onDelete }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const request = useRef<AbortController | null>(null);
  const blankWindow = useRef<Window | null>(null);
  const [openingId, setOpeningId] = useState<number>();
  const [error, setError] = useState<string>();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const candidate = application.candidate;
  const status = applicationStatuses[application.status] ?? applicationStatuses.received;

  useEffect(() => {
    const element = dialog.current;
    const overflow = document.body.style.overflow;
    element?.showModal();
    document.body.style.overflow = "hidden";
    return () => {
      request.current?.abort();
      blankWindow.current?.close();
      element?.close();
      document.body.style.overflow = overflow;
      if (restoreFocus?.isConnected) restoreFocus.focus();
      else document.getElementById("candidate-search")?.focus();
    };
  }, [onClose, restoreFocus]);

  async function openCV(cv: CandidateCVDocument, download: boolean) {
    if (request.current || deleting) return;
    const popup = download ? null : window.open("", "_blank");
    if (!download && !popup) { setError("Your browser blocked the CV window. Allow pop-ups or use Download instead."); return; }
    if (popup) {
      popup.opener = null;
      popup.document.title = "Candidate CV";
      popup.document.body.textContent = "Opening CV…";
    }
    const controller = new AbortController();
    request.current = controller; blankWindow.current = popup;
    setOpeningId(cv.id); setError(undefined);
    try {
      const blob = await apiBlob(`/candidates/applications/${application.id}/cvs/${cv.id}${download ? "?download=true" : ""}`, { signal: controller.signal });
      if (controller.signal.aborted) return;
      const url = URL.createObjectURL(blob);
      // Native PDF viewers may still be reading the blob after navigation.
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
      if (download) {
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = cv.original_filename.replace(/[<>:"/\\|?*\x00-\x1f]/g, "_");
        document.body.appendChild(anchor); anchor.click(); anchor.remove();
      } else if (popup && !popup.closed) {
        popup.location.replace(url);
        blankWindow.current = null;
      } else {
        URL.revokeObjectURL(url);
        throw new Error("The CV window was closed. Select Open CV to try again.");
      }
    } catch (failure) {
      popup?.close(); blankWindow.current = null;
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "The CV could not be opened. Please try again.");
    } finally {
      request.current = null;
      if (!controller.signal.aborted) setOpeningId(undefined);
    }
  }

  async function deleteConfirmed() {
    setError(undefined);
    try { await onDelete(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "The application could not be deleted."); }
  }

  return createPortal(<dialog ref={dialog} aria-modal="true" aria-labelledby="candidate-detail-title"
    onCancel={event => { event.preventDefault(); onClose(); }}
    onClick={event => { if (event.target === event.currentTarget) onClose(); }}
    className="fixed inset-0 m-auto max-h-[90dvh] w-[94vw] max-w-2xl overflow-hidden rounded-3xl border-0 bg-white p-0 text-slate-900 shadow-2xl backdrop:bg-slate-900/45 backdrop:backdrop-blur-sm">
    <div className="flex max-h-[90dvh] flex-col">
      <header className="flex shrink-0 items-start justify-between gap-4 border-b border-teal-100 bg-teal-50/60 px-6 py-5">
        <div className="flex min-w-0 items-center gap-4">
          <div className="min-w-0"><p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Candidate details</p>
            <h2 id="candidate-detail-title" className="mt-1 break-words text-xl font-bold">{candidate.name || "Unnamed candidate"}</h2>
            <p className="mt-1 break-words text-sm text-slate-600">{application.job_title}</p></div>
        </div>
        <button type="button" autoFocus aria-label="Close candidate details" onClick={onClose} className="rounded-xl p-2 text-slate-500 hover:bg-slate-200/70 focus-visible:outline-2 focus-visible:outline-blue-600">
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5"><path d="m6 6 12 12M18 6 6 18" /></svg>
        </button>
      </header>
      <div className="overflow-y-auto px-6 py-5">
        <div className="flex flex-wrap items-center gap-2"><span className={`rounded-full px-3 py-1 text-xs font-semibold ring-1 ring-inset ${status.style}`}>{status.label}</span>
          <span className="text-xs text-slate-500">Application #{application.id} · Posting #{application.job_posting_id}</span></div>
        <dl className="mt-5 grid gap-5 text-sm sm:grid-cols-2">
          <div><dt className="text-slate-500">Email</dt><dd className="mt-1 break-all font-medium">{candidate.email ? <a href={`mailto:${encodeURIComponent(candidate.email)}`} className="text-blue-700 hover:underline">{candidate.email}</a> : "Not provided"}</dd></div>
          <div><dt className="text-slate-500">Phone</dt><dd className="mt-1 font-medium">{candidate.phone || "Not provided"}</dd></div>
          <div><dt className="text-slate-500">Applied</dt><dd className="mt-1 font-medium">{candidateDate(application.submitted_at, true)}</dd></div>
          {([['LinkedIn', candidate.linkedin_url], ['Portfolio', candidate.portfolio_url]] as const).map(([label, value]) => {
            const url = safeCandidateWebsite(value);
            return value ? <div key={label}><dt className="text-slate-500">{label}</dt><dd className="mt-1 break-all">{url ? <a href={url} target="_blank" rel="noopener noreferrer" className="font-medium text-blue-700 hover:underline">Open {label.toLowerCase()} ↗</a> : "Link unavailable"}</dd></div> : null;
          })}
        </dl>
        <section aria-labelledby="candidate-cv-title" className="mt-6 border-t border-slate-100 pt-5">
          <h3 id="candidate-cv-title" className="font-semibold">CV documents</h3>
          <p className="mt-1 text-sm text-slate-500">Open a PDF in a new tab or download a copy.</p>
          {application.cv_documents.length ? <ul className="mt-3 space-y-3">{application.cv_documents.map(cv => {
            const pdf = cv.mime_type === "application/pdf" || cv.original_filename.toLowerCase().endsWith(".pdf");
            return <li key={cv.id} className="rounded-2xl border border-slate-200 bg-slate-50/60 p-4">
              <div className="flex items-start gap-3"><span aria-hidden="true" className="rounded-lg bg-white px-2 py-2 text-xs font-bold text-blue-700 ring-1 ring-slate-200">{pdf ? "PDF" : "DOCX"}</span>
                <div className="min-w-0"><p className="break-words text-sm font-semibold">{cv.original_filename}</p><p className="mt-1 text-xs text-slate-500">{cvSize(cv.file_size_bytes)}{!pdf ? " · Word file — download to open on your device" : ""}</p></div></div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                {pdf ? <button type="button" disabled={openingId !== undefined || deleting} onClick={() => void openCV(cv, false)} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50">{openingId === cv.id ? "Opening…" : "Open CV"}</button> : null}
                <button type="button" disabled={openingId !== undefined || deleting} onClick={() => void openCV(cv, true)} className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100 disabled:opacity-50">{openingId === cv.id && !pdf ? "Preparing…" : "Download"}</button>
              </div>
            </li>;
          })}</ul> : <p className="mt-3 rounded-xl bg-amber-50 p-4 text-sm text-amber-800">No CV was collected for this application. Try syncing responses again.</p>}
        </section>
        {error ? <p role="alert" className="mt-4 rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</p> : null}
        {confirmDelete ? <div className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-900">
          <p className="font-semibold">Delete this application?</p><p className="mt-1">The application, its CV files and linked results will be permanently removed.</p>
          <div className="mt-3 flex flex-wrap gap-3"><button type="button" disabled={deleting || openingId !== undefined} onClick={() => void deleteConfirmed()} className="rounded-lg bg-red-600 px-3 py-2 font-semibold text-white disabled:opacity-50">{deleting ? "Deleting…" : "Delete permanently"}</button>
            <button type="button" disabled={deleting} onClick={() => setConfirmDelete(false)} className="rounded-lg border border-red-200 bg-white px-3 py-2 font-medium">Keep application</button></div>
        </div> : null}
      </div>
      <footer className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-6 py-4">
        <button type="button" disabled={deleting || openingId !== undefined} onClick={() => setConfirmDelete(true)} className="text-sm font-medium text-red-600 hover:text-red-800 disabled:opacity-50">Delete application</button>
        <div className="flex items-center gap-3"><Link to={`/interviewer/reports?application=${application.id}`} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">View assessment</Link>
          <button type="button" onClick={onClose} className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-700">Done</button></div>
      </footer>
    </div>
  </dialog>, document.body);
}
