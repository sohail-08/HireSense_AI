import { useState } from "react";
import { analysisApi, type Citation, type Segment } from "./analysisApi";
import { transcriptTime } from "./transcriptionApi";

/** Opens the exact immutable source version; never offers nonexistent audio playback. */
export function TranscriptCitation({ citation, runId, interviewId }: { citation: Citation; runId: number; interviewId: number }) {
  const [source, setSource] = useState<Segment>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function open() {
    setBusy(true); setError("");
    try {
      const state = await analysisApi.read(interviewId, runId);
      const segment = state.run?.snapshot.segments.find(s => s.id === citation.segment_id && s.hash === citation.revision);
      if (!segment || Array.from(segment.text).slice(citation.char_start, citation.char_end).join("") !== citation.quote) throw new Error("This source is unavailable or has expired.");
      setSource(segment);
    } catch (e) { setError(e instanceof Error ? e.message : "Could not load source."); }
    finally { setBusy(false); }
  }
  return <>
    <button type="button" disabled={busy} onClick={() => void open()} className="my-1 block text-left text-sm text-blue-700 underline">
      {citation.speaker === "CANDIDATE" ? "Candidate" : "Interviewer"} · {transcriptTime(citation.start_offset_ms)} · “{citation.quote}”
    </button>
    {error ? <p role="alert" className="text-sm text-red-700">{error}</p> : null}
    {source ? <div role="dialog" aria-modal="true" aria-label="Transcript source passage" className="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 p-5" onKeyDown={e => { if (e.key === "Escape") setSource(undefined); }}>
      <section className="max-h-[80vh] w-full max-w-2xl overflow-auto rounded-xl bg-white p-6 shadow-xl">
        <div className="flex justify-between gap-4"><h3 className="font-bold">Transcript source · {transcriptTime(source.start_offset_ms)}</h3><button autoFocus onClick={() => setSource(undefined)} className="rounded border px-3 py-1">Close</button></div>
        <p className="mt-4 whitespace-pre-wrap break-words">{Array.from(source.text).slice(0, citation.char_start).join("")}<mark>{Array.from(source.text).slice(citation.char_start, citation.char_end).join("")}</mark>{Array.from(source.text).slice(citation.char_end).join("")}</p>
        <p className="mt-3 break-all text-xs text-slate-500">Original finalized text · segment {source.id} · revision {source.hash.slice(0, 12)}</p>
      </section>
    </div> : null}
  </>;
}
