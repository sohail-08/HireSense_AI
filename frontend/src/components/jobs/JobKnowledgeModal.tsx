import { useEffect, useRef, useState, type FormEvent } from "react";
import { apiRequest } from "../../api/apiClient";
import type { KnowledgeDocumentResponse } from "../../types";
import { PreviewModal } from "../common/PreviewModal";

export function JobKnowledgeModal({ onClose }: { onClose: () => void }) {
  const [documents, setDocuments] = useState<KnowledgeDocumentResponse[]>([]);
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File>();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [reload, setReload] = useState(0);
  const [fileKey, setFileKey] = useState(0);
  const lock = useRef(false);
  useEffect(() => {
    let alive = true; setLoading(true); setError("");
    void apiRequest<KnowledgeDocumentResponse[]>("/knowledge/documents").then(value => { if (alive) setDocuments(value); })
      .catch(() => { if (alive) setError("Reference documents could not be loaded. Please try again."); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [reload]);
  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || lock.current) return;
    lock.current = true; setBusy(true); setError(""); setNotice("");
    try {
      const body = new FormData(); body.append("file", file);
      if (title.trim()) body.append("title", title.trim());
      const document = await apiRequest<KnowledgeDocumentResponse>("/knowledge/documents/upload", { method: "POST", body });
      setDocuments(items => [document, ...items.filter(item => item.id !== document.id)]);
      setFile(undefined); setTitle(""); setFileKey(key => key + 1);
      setNotice(`Added “${document.title}”. Start a new job to use the updated references.`);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "The PDF could not be uploaded. Please try again."); }
    finally { lock.current = false; setBusy(false); }
  }
  async function remove(document: KnowledgeDocumentResponse) {
    if (lock.current || !window.confirm(`Remove “${document.title}” from the reference library? The document and its indexed content will be deleted.`)) return;
    lock.current = true; setBusy(true); setError(""); setNotice("");
    try {
      await apiRequest(`/knowledge/documents/${document.id}`, { method: "DELETE" });
      setDocuments(items => items.filter(item => item.id !== document.id)); setNotice(`Removed “${document.title}”.`);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "The document could not be removed."); }
    finally { lock.current = false; setBusy(false); }
  }
  return <PreviewModal title="Reference documents" onClose={onClose} busy={busy}>
    <p className="text-sm leading-6 text-slate-600">Add previous job descriptions to help the assistant write future drafts.</p>
    <form onSubmit={event => void upload(event)} className="mt-5 space-y-4 rounded-2xl border border-sky-100 bg-sky-50/50 p-4">
      <div><label htmlFor="knowledge-title" className="text-sm font-semibold text-slate-700">Document title <span className="font-normal text-slate-500">(optional)</span></label><input id="knowledge-title" value={title} disabled={busy || loading} onChange={event => setTitle(event.target.value)} placeholder="For example, Backend Engineer" className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100" /></div>
      <div><label htmlFor="knowledge-pdf" className="text-sm font-semibold text-slate-700">Job description PDF</label><input key={fileKey} id="knowledge-pdf" type="file" accept="application/pdf,.pdf" disabled={busy || loading} onChange={event => setFile(event.target.files?.[0])} className="mt-2 block w-full rounded-xl border border-dashed border-sky-200 bg-white p-3 text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-blue-50 file:px-3 file:py-1.5 file:font-semibold file:text-blue-700" /><p className="mt-2 text-xs leading-5 text-slate-500">PDFs with selectable text, up to 15 MB and 100 pages.</p></div>
      <button type="submit" disabled={!file || busy || loading} className="rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50">{busy ? "Working…" : "Upload PDF"}</button>
    </form>
    {notice ? <p role="status" className="mt-4 rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p> : null}
    {error ? <div role="alert" className="mt-4 rounded-xl bg-rose-50 p-3 text-sm text-rose-800">{error}<button type="button" disabled={busy} onClick={() => setReload(value => value + 1)} className="ml-2 font-semibold underline">Reload documents</button></div> : null}
    <h3 className="mt-6 font-semibold text-slate-800">Saved references <span className="ml-1 text-xs font-normal text-slate-500">{documents.length}</span></h3>
    {loading ? <p role="status" className="mt-3 text-sm text-slate-500">Loading references…</p> : documents.length ? <ul className="mt-3 space-y-2">{documents.map(document => <li key={document.id} className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 p-3"><div className="min-w-0"><p className="break-words text-sm font-medium text-slate-700">{document.title}</p><p className="mt-1 text-xs text-slate-500">{document.metadata_json.page_count ? `PDF · ${document.metadata_json.page_count} pages` : "Job description reference"}</p></div><button type="button" disabled={busy} onClick={() => void remove(document)} aria-label={`Remove reference: ${document.title}`} className="rounded-lg px-3 py-2 text-xs font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-50">Remove</button></li>)}</ul> : !error ? <p className="mt-3 rounded-xl bg-slate-50 p-4 text-sm text-slate-500">No reference documents yet. You can still create a job without them.</p> : null}
  </PreviewModal>;
}
