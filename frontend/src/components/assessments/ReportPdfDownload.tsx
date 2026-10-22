import { useEffect, useRef, useState } from "react";
import { assessmentApi, type Artifact } from "./assessmentApi";

export function ReportPdfDownload({ id }: { id: number }) {
  const [artifact, setArtifact] = useState<Artifact>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const locked = useRef(false);
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    if (!artifact) return;
    let alive = true;
    function fail(message: string) {
      if (alive) { setError(message); setBusy(false); locked.current = false; }
    }
    if (["queued", "processing"].includes(artifact.status)) {
      const timer = window.setTimeout(() => {
        void assessmentApi.artifact(artifact.id).then(next => { if (alive) setArtifact(next); })
          .catch(() => fail("Could not check the PDF status. Please try again."));
      }, 1500);
      return () => { alive = false; window.clearTimeout(timer); };
    }
    if (artifact.status !== "completed") {
      fail("The PDF could not be prepared. Please try again.");
      return;
    }
    void assessmentApi.blob(artifact.id).then(blob => {
      if (!alive) return;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url; anchor.download = `hiresense-report-${id}.pdf`;
      document.body.appendChild(anchor); anchor.click(); anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
      setBusy(false); locked.current = false;
    }).catch(() => fail("The PDF could not be downloaded. Please try again."));
    return () => { alive = false; };
  }, [artifact, id]);

  async function download() {
    if (locked.current) return;
    locked.current = true; setBusy(true); setError(""); setArtifact(undefined);
    try {
      const next = await assessmentApi.export(id, "pdf");
      if (mounted.current) setArtifact(next);
    } catch {
      if (mounted.current) { setError("The PDF could not be prepared. Please try again."); setBusy(false); locked.current = false; }
    }
  }
  return <section aria-label="Download report" className="mt-4">
    <button type="button" disabled={busy} aria-busy={busy} onClick={() => void download()} className="inline-flex min-h-10 items-center gap-2 rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:cursor-wait disabled:opacity-60">
      <svg aria-hidden="true" className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3v12m-4-4 4 4 4-4M4 16v4h16v-4" /></svg>
      {busy ? "Preparing PDF…" : "Download this report"}
    </button>
    {busy ? <p role="status" className="mt-2 text-xs text-slate-500">Your PDF will download when it is ready.</p> : null}
    {error ? <p role="alert" className="mt-2 text-sm text-red-700">{error}</p> : null}
  </section>;
}
