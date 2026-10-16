import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useRoomContext } from "@livekit/components-react";
import { RoomEvent } from "livekit-client";
import { transcriptionApi, transcriptTime, mergeFinals, verifyCaptionMessage, type TranscriptionStatus, type TranscriptLine } from "./transcriptionApi";

type Context = {
  status?: TranscriptionStatus; finals: TranscriptLine[]; interim: Record<string, TranscriptLine>;
  error?: string; busy: boolean; consent: (yes: boolean) => Promise<void>;
  control: (action: "start" | "stop") => Promise<void>; receive: (sender: string, value: unknown) => Promise<void>;
  restore: () => Promise<void>; interviewer: boolean;
};
const TranscriptionContext = createContext<Context | undefined>(undefined);

export function TranscriptionProvider({ interviewId, closed = false, children }: { interviewId?: number; closed?: boolean; children: ReactNode }) {
  const [status, setStatus] = useState<TranscriptionStatus>();
  const [finals, setFinals] = useState<TranscriptLine[]>([]);
  const [interim, setInterim] = useState<Record<string, TranscriptLine>>({});
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const statusRef = useRef(status);
  const alive = useRef(true);
  const restoring = useRef(false);
  const restoreAgain = useRef(false);
  const actionLock = useRef(false);
  const lastInterimIndex = useRef(new Map<string, number>());
  const finalizedEnd = useRef(new Map<string, number>());
  statusRef.current = status;
  const apply = useCallback((next: TranscriptionStatus) => {
    if (!alive.current) return;
    statusRef.current = next;
    setStatus(next);
    if (next.status !== "active" || !next.consented) setInterim({});
  }, []);
  const restore = useCallback(async (): Promise<void> => {
    if (interviewId === undefined) return;
    if (restoring.current) { restoreAgain.current = true; return; }
    restoring.current = true;
    try {
      let cursor: string | undefined;
      do {
        const page = await transcriptionApi.history(interviewId, cursor);
        if (!alive.current) return;
        setFinals(previous => mergeFinals(previous, page.segments));
        cursor = page.next_cursor || undefined;
      } while (cursor);
    } catch { if (alive.current) setError("Saved transcript could not be loaded. Live captions may still work; reconnect or refresh to retry."); }
    finally {
      restoring.current = false;
      if (restoreAgain.current && alive.current) { restoreAgain.current = false; queueMicrotask(() => void restore()); }
    }
  }, [interviewId]);
  useEffect(() => {
    alive.current = true;
    let refreshing = false;
    async function refresh() {
      if (refreshing || !alive.current) return;
      refreshing = true;
      try {
        const next = await transcriptionApi.status(interviewId);
        apply(next);
      } catch { if (alive.current && !closed) setError("Transcription status is unavailable. Audio/video is unaffected."); }
      finally { refreshing = false; }
    }
    void refresh();
    void restore();
    // Lifecycle only. Interim/final captions arrive over LiveKit, never polling.
    const timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, 3000);
    return () => { alive.current = false; window.clearInterval(timer); };
  }, [interviewId, closed, apply, restore]);
  useEffect(() => { if (status?.session_id) void restore(); }, [status?.session_id, status?.status, restore]);
  async function action(work: () => Promise<TranscriptionStatus>) {
    if (actionLock.current) return;
    actionLock.current = true; setBusy(true); setError(undefined);
    try { apply(await work()); }
    catch (failure) { if (alive.current) setError(failure instanceof Error ? failure.message : "Transcription action failed."); }
    finally { actionLock.current = false; if (alive.current) setBusy(false); }
  }
  const receive = useCallback(async (sender: string, envelope: unknown) => {
    let value: Awaited<ReturnType<typeof verifyCaptionMessage>>;
    try { value = await verifyCaptionMessage(envelope, sender, statusRef.current); }
    catch { if (alive.current) setError("Live caption verification is unavailable. Use HTTPS or localhost in a supported browser. Saved text can still be loaded."); return; }
    // Consent/session can change while WebCrypto verifies a message.
    if (!alive.current || !value || !statusRef.current?.consented || !statusRef.current?.both_consented
      || value.session_id !== statusRef.current.session_id) return;
    const key = `${value.session_id}:${value.stream_id}`;
    if (value.kind === "interim") {
      const index = value.event_index || 0;
      if (index < (lastInterimIndex.current.get(key) || 0) || value.end_offset_ms <= (finalizedEnd.current.get(key) || -1)) return;
      if (lastInterimIndex.current.size > 512) lastInterimIndex.current.clear();
      lastInterimIndex.current.set(key, index);
      if (statusRef.current?.status === "active") setInterim(previous => ({ ...previous, [value.speaker]: value }));
    } else {
      if (finalizedEnd.current.size > 512) finalizedEnd.current.clear();
      finalizedEnd.current.set(key, Math.max(finalizedEnd.current.get(key) || 0, value.end_offset_ms));
      setFinals(previous => mergeFinals(previous, [value], interviewId === undefined ? 80 : 10000));
      setInterim(previous => {
        const next = { ...previous };
        if (next[value.speaker]?.stream_id === value.stream_id && next[value.speaker].start_offset_ms <= value.end_offset_ms) delete next[value.speaker];
        return next;
      });
    }
  }, [interviewId]);
  return <TranscriptionContext.Provider value={{ status, finals, interim, error, busy,
    interviewer: interviewId !== undefined, receive, restore,
    consent: yes => action(() => transcriptionApi.consent(yes, interviewId)),
    control: choice => interviewId === undefined ? Promise.resolve() : action(() => transcriptionApi.control(interviewId, choice)) }}>{children}</TranscriptionContext.Provider>;
}

/** Must live under LiveKitRoom, while the visible panel can remain below the video. */
export function TranscriptReceiver() {
  const room = useRoomContext();
  const context = useContext(TranscriptionContext);
  useEffect(() => {
    if (!context) return;
    let active = true;
    const topic = "hiresense.transcript.v1";
    room.registerTextStreamHandler(topic, async (reader, sender) => {
      try {
        // Bound messages before JSON parsing, even for an unexpected sender.
        let text = "";
        for await (const chunk of reader) {
          text += chunk;
          if (text.length > 200000) return;
        }
        if (active) await context.receive(sender.identity, JSON.parse(text));
      } catch { /* Malformed/untrusted captions are ignored, never rendered as HTML. */ }
    });
    const reconnect = () => { void context.restore(); };
    room.on(RoomEvent.Reconnected, reconnect);
    void context.restore();
    return () => { active = false; room.unregisterTextStreamHandler(topic); room.off(RoomEvent.Reconnected, reconnect); };
  }, [room, context?.receive, context?.restore]);
  return null;
}

export function TranscriptionPanel({ closed = false }: { closed?: boolean }) {
  const context = useContext(TranscriptionContext);
  const scroll = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  useEffect(() => {
    if (scroll.current && follow.current) scroll.current.scrollTop = scroll.current.scrollHeight;
  }, [context?.finals, context?.interim]);
  if (!context) return null;
  const { status, finals, interim, error, busy, interviewer } = context;
  if (!status) return <section className="mt-5 rounded-2xl bg-white p-5"><h2 className="font-semibold">Live transcript</h2><p role="status">{error || "Loading transcription status…"}</p></section>;
  const running = ["starting", "active", "stopping"].includes(status.status);
  const label = status.status === "active" ? status.connection_status === "transcribing" ? "Transcription active" : status.connection_status
    : { not_started: "Not started", starting: "Connecting", stopping: "Stopping and saving", completed: "Stopped", failed: "Failed" }[status.status];
  const lines = [...finals, ...Object.values(interim)];
  return <section className="mt-5 min-w-0 rounded-2xl bg-white p-5 shadow-sm" aria-label={interviewer ? "Interview transcript" : "Live captions"}>
    <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-lg font-semibold">{interviewer ? "Live transcript" : "Live captions"}</h2>
      <span role="status" className={`rounded-full px-3 py-1 text-sm ${status.status === "active" ? "bg-emerald-100 text-emerald-900" : "bg-slate-100"}`}>{label}</span></div>
    {!closed && status.enabled ? <>
      <p className="mt-3 text-sm text-slate-600">{status.notice} Saved text is retained for {status.retention_days} days.</p>
      <label className="mt-3 flex items-start gap-2 text-sm"><input className="mt-1" type="checkbox" checked={status.consented} disabled={busy}
        onChange={event => void context.consent(event.target.checked)} />I consent to live transcription and storage of the final text.</label>
      {!status.both_consented ? <p className="mt-2 text-sm text-amber-800">Waiting for both participants to consent. No transcription can start yet.</p> : null}
      {interviewer ? <div className="mt-3 flex gap-3"><button className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:bg-slate-300"
        disabled={busy || !status.can_start} onClick={() => void context.control("start")}>{status.status === "failed" ? "Retry transcription" : "Start transcription"}</button>
        <button className="rounded-lg border px-4 py-2 text-sm disabled:text-slate-400" disabled={busy || !running || status.status === "stopping"}
          onClick={() => void context.control("stop")}>Stop transcription</button></div> : null}
    </> : !status.enabled && !closed ? <p className="mt-3 text-sm text-slate-600">Transcription is not configured. The video interview works independently.</p> : null}
    {status.failure_code ? <p role="alert" className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">Transcription stopped ({status.failure_code.replaceAll("_", " ")}). Audio/video is unaffected. Ask the interviewer to retry after checking configuration.</p> : null}
    {error ? <p role="alert" className="mt-3 text-sm text-amber-900">{error}</p> : null}
    <div ref={scroll} onScroll={() => { const el = scroll.current; if (el) follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60; }}
      className="mt-4 max-h-80 space-y-3 overflow-y-auto overscroll-contain" aria-label="Transcript segments" tabIndex={0}>
      {!lines.length ? <p className="py-5 text-sm text-slate-500">{closed ? "No saved transcript is available." : "Speech will appear here after both participants consent and transcription starts."}</p> : lines.map(line => <article key={line.id || `interim-${line.speaker}`}
        className={`rounded-xl border-l-4 p-3 ${line.speaker === "INTERVIEWER" ? "border-blue-500 bg-blue-50" : "border-emerald-500 bg-emerald-50"} ${line.kind === "interim" ? "italic opacity-70" : ""}`}>
        <p className="text-xs font-semibold">{line.speaker === "INTERVIEWER" ? "Interviewer" : "Candidate"} · {transcriptTime(line.start_offset_ms)}{line.kind === "interim" ? " · Live draft" : " · Final"}</p>
        <p className="mt-1 whitespace-pre-wrap break-words text-sm">{line.text}</p></article>)}
    </div>
    {!interviewer ? <p className="mt-2 text-xs text-slate-500">Live captions only. Saved transcript history is interviewer-only.</p> : null}
  </section>;
}
