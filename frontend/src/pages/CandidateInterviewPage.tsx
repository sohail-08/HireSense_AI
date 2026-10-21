import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { DeviceCheck } from "../components/interviews/DeviceCheck";
import { InterviewMediaRoom } from "../components/interviews/InterviewMediaRoom";
import { roomApi, RoomApiError, type CandidateRoomInfo, type DeviceChoices, type MediaAccess } from "../components/interviews/roomApi";
import { accessMessage, formatRoomTime } from "../components/interviews/roomState";
import { TranscriptionProvider, TranscriptionPanel } from "../components/interviews/TranscriptionPanel";

export function CandidateInterviewPage() {
  const { token } = useParams();
  const invitation = useRef(token);
  const initial = useRef<Promise<CandidateRoomInfo> | null>(null);
  const [info, setInfo] = useState<CandidateRoomInfo>();
  const [fatal, setFatal] = useState<RoomApiError>();
  const [message, setMessage] = useState<string>();
  const [view, setView] = useState<"prejoin" | "waiting" | "room" | "left">("prejoin");
  const [devices, setDevices] = useState<DeviceChoices>();
  const [access, setAccess] = useState<MediaAccess>();
  const busy = useRef(false);
  const operation = useRef(0);
  useEffect(() => {
    let active = true;
    // Remove the email credential from the address bar before any further action.
    window.history.replaceState(window.history.state, "", "/interview/join");
    if (!initial.current) initial.current = invitation.current ? roomApi.exchange(invitation.current) : roomApi.candidateStatus();
    void initial.current.then((result) => { if (active) { setInfo(result); invitation.current = undefined; } })
      .catch((failure) => { if (active) setFatal(failure instanceof RoomApiError ? failure : new RoomApiError("network_error", 0)); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    if (!info || fatal || (view !== "waiting" && view !== "room")) return;
    let active = true;
    let polling = false;
    const timer = window.setInterval(() => {
      if (polling) return;
      polling = true;
      void roomApi.candidateStatus().then(async (result) => {
        if (!active) return;
        setInfo(result);
        if (view === "waiting" && result.admitted && devices && !result.media_notice && !busy.current) {
          busy.current = true;
          const attempt = operation.current;
          setMessage("You have been admitted. Connecting…");
          try {
            const credential = await roomApi.candidateMedia();
            if (active && attempt === operation.current) { setAccess(credential); setView("room"); setMessage(undefined); }
          } catch (failure) {
            if (active) setMessage(failure instanceof RoomApiError && failure.status === 503 ? "Media service unavailable. Retrying…" : "Could not connect yet. Retrying…");
          } finally { busy.current = false; }
        }
      }).catch((failure) => {
        if (active) setFatal(failure instanceof RoomApiError ? failure : new RoomApiError("network_error", 0));
      }).finally(() => { polling = false; });
    }, 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, [Boolean(info), fatal, view, devices]);
  async function ready(choices: DeviceChoices) {
    if (busy.current) return;
    busy.current = true;
    const attempt = ++operation.current;
    try { const result = await roomApi.waiting(); if (attempt === operation.current) { setInfo(result); setDevices(choices); setView("waiting"); setMessage(undefined); } }
    catch (failure) { setFatal(failure instanceof RoomApiError ? failure : new RoomApiError("network_error", 0)); }
    finally { busy.current = false; }
  }
  async function leave() {
    operation.current += 1;
    setAccess(undefined); setView("left");
    try { setInfo(await roomApi.candidateLeave()); }
    catch (failure) { setFatal(failure instanceof RoomApiError ? failure : new RoomApiError("network_error", 0)); }
  }
  const linkState = fatal ? accessMessage(fatal.code) : null;
  return (
    <main className="min-h-screen bg-slate-100 px-4 py-8">
      <div className="mx-auto max-w-5xl">
        <p className="text-xl font-bold text-blue-600">HireSense · Interview</p>
        {linkState ? <section className="mt-6 rounded-2xl bg-white p-6 shadow-sm"><h1 className="text-2xl font-bold">{linkState.title}</h1><p className="mt-3 text-slate-600">{linkState.message}</p></section> : !info ? <p role="status" className="mt-6">Checking your interview invitation…</p> : <>
          <h1 className="mt-6 text-2xl font-bold">{info.job_title} interview</h1>
          <p className="mt-2 text-sm text-slate-600">{formatRoomTime(info.scheduled_start, info.timezone)} · Private one-to-one room · No recording</p>
          {info.media_notice ? <p role="alert" className="mt-4 rounded-xl bg-amber-50 p-4 text-amber-900">{info.media_notice}</p> : null}
          <TranscriptionProvider>
          <div className="mt-6">
            {view === "prejoin" ? <DeviceCheck role="candidate" onReady={(choices) => void ready(choices)} /> : null}
            {view === "waiting" ? <section className="rounded-2xl bg-white p-6 shadow-sm"><h2 className="text-xl font-semibold">{info.admitted && info.media_notice ? "Admitted — audio/video unavailable" : "Waiting for interviewer"}</h2><p role="status" className="mt-3 text-slate-600">{info.admitted && info.media_notice ? "The interviewer admitted you. Audio/video will connect once the media service is configured." : message || "You will enter when the interviewer admits you. No live media connection has been made yet."}</p><p className="mt-3 text-sm text-slate-500">Microphone: {devices?.audioEnabled ? "ready" : "off"} · Camera: {devices?.videoEnabled ? "ready" : "off"}</p><button className="mt-5 rounded-lg border px-4 py-2" onClick={() => void leave()}>Leave waiting room</button></section> : null}
            {view === "room" && access && devices ? <InterviewMediaRoom access={access} devices={devices}
              onConnected={() => { void roomApi.candidateConnected().then(setInfo).catch(() => setMessage("Media connected; interview status could not be updated yet.")); }}
              onLeave={() => void leave()} onEnded={() => setFatal(new RoomApiError("ended", 410))} /> : null}
            {view === "room" && message ? <p role="status" className="mt-3 text-sm text-slate-600">{message}</p> : null}
            <TranscriptionPanel />
            {view === "left" ? <section className="rounded-2xl bg-white p-6"><h2 className="text-xl font-semibold">You left the interview room</h2><p className="mt-2 text-slate-600">Leaving does not end the interview. You can rejoin while access remains open.</p><button className="mt-4 rounded-lg bg-blue-600 px-4 py-2 text-white" onClick={() => { setMessage(undefined); setView("prejoin"); }}>Check devices and rejoin</button></section> : null}
          </div>
          </TranscriptionProvider>
        </>}
      </div>
    </main>
  );
}
