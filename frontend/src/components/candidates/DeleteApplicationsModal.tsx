import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

type Props = { count: number; busy: boolean; restoreFocus: HTMLElement | null; onClose: () => void; onConfirm: () => Promise<void> };

export function DeleteApplicationsModal({ count, busy, restoreFocus, onClose, onConfirm }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [error, setError] = useState<string>();
  useEffect(() => {
    const element = dialog.current;
    const overflow = document.body.style.overflow;
    element?.showModal(); document.body.style.overflow = "hidden";
    return () => {
      element?.close(); document.body.style.overflow = overflow;
      if (restoreFocus?.isConnected) restoreFocus.focus();
      else document.getElementById("candidate-search")?.focus();
    };
  }, [restoreFocus, onClose]);
  async function confirm() {
    setError(undefined);
    try { await onConfirm(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "Could not delete the applications. Please try again."); }
  }
  return createPortal(<dialog ref={dialog} aria-modal="true" aria-labelledby="delete-applications-title"
    onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}
    className="fixed inset-0 m-auto w-[94vw] max-w-md rounded-2xl border-0 bg-white p-6 text-slate-900 shadow-2xl backdrop:bg-slate-900/45">
    <h2 id="delete-applications-title" className="text-lg font-bold">Delete {count === 1 ? "this application" : `${count} applications`}?</h2>
    <p className="mt-3 text-sm leading-6 text-slate-600">The selected applications, CV files and linked results will be permanently removed. This cannot be undone.</p>
    {error ? <p role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p> : null}
    <div className="mt-5 flex justify-end gap-3">
      <button autoFocus type="button" disabled={busy} onClick={onClose} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold disabled:opacity-50">Cancel</button>
      <button type="button" disabled={busy} onClick={() => void confirm()} className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50">{busy ? "Deleting…" : "Delete permanently"}</button>
    </div>
  </dialog>, document.body);
}
