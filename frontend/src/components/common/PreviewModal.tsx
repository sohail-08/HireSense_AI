import { useId, useLayoutEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

export function PreviewModal({ title, children, onClose, busy = false }: {
  title: string; children: ReactNode; onClose: () => void; busy?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const heading = useId();
  useLayoutEffect(() => {
    const element = dialog.current;
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    element?.showModal();
    closeButton.current?.focus();
    document.body.style.overflow = "hidden";
    return () => {
      element?.close(); document.body.style.overflow = overflow;
      if (previous?.isConnected) previous.focus();
    };
  }, []);
  return createPortal(<dialog ref={dialog} aria-modal="true" aria-labelledby={heading} aria-busy={busy}
    onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}
    onClick={event => { if (!busy && event.target === event.currentTarget) onClose(); }}
    className="fixed inset-0 m-auto max-h-[90dvh] w-[94vw] max-w-2xl overflow-hidden rounded-3xl border-0 bg-white p-0 text-slate-900 shadow-2xl backdrop:bg-slate-900/45 backdrop:backdrop-blur-sm">
    <div className="flex max-h-[90dvh] flex-col">
      <header className="flex shrink-0 items-center justify-between gap-4 border-b border-blue-100 bg-blue-50/60 px-6 py-5">
        <h2 id={heading} className="text-xl font-bold">{title}</h2>
        <button ref={closeButton} type="button" aria-label="Close preview" disabled={busy} onClick={onClose}
          className="rounded-xl px-3 py-1 text-2xl text-slate-500 hover:bg-slate-200/70 focus-visible:outline-2 focus-visible:outline-blue-600 disabled:opacity-40">×</button>
      </header>
      <div className="overflow-y-auto p-6">{children}</div>
    </div>
  </dialog>, document.body);
}
