import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { DeviceCheck } from "../components/interviews/DeviceCheck";
import { InterviewMediaRoom } from "../components/interviews/InterviewMediaRoom";
import { roomApi, RoomApiError, type CandidateRoomInfo, type DeviceChoices, type MediaAccess } from "../components/interviews/roomApi";
import { accessMessage, formatRoomTime } from "../components/interviews/roomState";
import { TranscriptionProvider, TranscriptionPanel } from "../components/interviews/TranscriptionPanel";
import { MeetingIcon } from "../components/interviews/MeetingIcon";
import { CandidateWorkSample } from "../components/interviews/CandidateWorkSample";

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
        if (active) {
          if (failure instanceof RoomApiError && failure.status > 0 && failure.status < 500) setFatal(failure);
          else setMessage("Connection interrupted. Keep this page open; interview status will retry.");
        }
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
    <main className="hiresense-meeting-workspace min-h-screen min-w-0 bg-slate-50 px-3 py-5 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-6xl">
        <div className="flex flex-wrap items-center justify-between gap-3"><p className="text-xl font-bold tracking-tight text-blue-600">HireSense · Interview</p><p className="flex items-center gap-1.5 text-xs text-slate-500"><MeetingIcon name="lock" className="h-4 w-4"/>Private room · No recording</p></div>
        {linkState ? <section className="mt-6 rounded-2xl bg-white p-6 shadow-sm"><h1 className="text-2xl font-bold">{linkState.title}</h1><p className="mt-3 text-slate-600">{linkState.message}</p></section> : !info ? <p role="status" className="mt-6">Checking your interview invitation…</p> : <>
          <header className="mt-6 border-b border-slate-200 pb-5"><h1 className="text-2xl font-bold tracking-tight">{info.job_title} interview</h1>
          <p className="mt-2 text-sm text-slate-500">{formatRoomTime(info.scheduled_start, info.timezone)}</p>
          <ol aria-label="Joining progress" className="mt-4 flex flex-wrap gap-2 text-xs font-semibold">{["Check devices", "Wait for admission", "Join interview"].map((step, index) => {
            const current = view === "prejoin" || view === "left" ? 0 : view === "waiting" ? 1 : 2;
            return <li key={step} aria-current={index === current ? "step" : undefined} className={`flex items-center gap-2 rounded-full px-3 py-2 ${index === current ? "bg-blue-600 text-white" : index < current ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-400"}`}><span>{index + 1}.</span>{step}</li>;
          })}</ol></header>
          {info.media_notice ? <p role="alert" className="mt-4 rounded-xl bg-amber-50 p-4 text-amber-900">{info.media_notice}</p> : null}
          <TranscriptionProvider>
          <div className="mt-5 min-w-0 space-y-5">
            {view === "prejoin" ? <DeviceCheck role="candidate" onReady={(choices) => void ready(choices)} /> : null}
            {view === "waiting" ? <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"><div className="hiresense-prejoin-stage"><div className="flex max-w-md flex-col items-center gap-4"><span className="rounded-3xl bg-slate-800 p-5"><MeetingIcon name="person" className="h-10 w-10 text-blue-300"/></span><h2 className="text-xl font-semibold">{info.admitted && info.media_notice ? "Admitted — audio/video unavailable" : "Waiting for interviewer"}</h2><p role="status" className="text-sm leading-6 text-slate-400">{info.admitted && info.media_notice ? "The interviewer admitted you. Audio/video will connect once the media service is configured." : message || "You’re ready. Your interviewer will let you in shortly. You are not connected to the meeting yet."}</p></div></div><div className="flex flex-wrap items-center justify-between gap-3 p-5"><p className="text-sm text-slate-500">Microphone: {devices?.audioEnabled ? "ready" : "off"} · Camera: {devices?.videoEnabled ? "ready" : "off"}</p><button className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-600 hover:bg-slate-50" onClick={() => void leave()}>Leave waiting room</button></div></section> : null}
            {view === "room" && access && devices ? <InterviewMediaRoom access={access} devices={devices}
              onConnected={() => { void roomApi.candidateConnected().then(setInfo).catch(() => setMessage("Media connected; interview status could not be updated yet.")); }}
              onLeave={() => void leave()} onEnded={() => setFatal(new RoomApiError("ended", 410))} /> : null}
            {view === "room" && message ? <p role="status" className="mt-3 text-sm text-slate-600">{message}</p> : null}
            <TranscriptionPanel />
            {view === "left" ? <section className="rounded-2xl border border-slate-200 bg-white p-6 text-center shadow-sm"><h2 className="text-xl font-semibold">You left the interview room</h2><p className="mt-2 text-sm leading-6 text-slate-500">The interview is still open. You can check your devices and join again.</p><button className="mt-5 rounded-xl bg-blue-600 px-5 py-3 text-sm font-semibold text-white hover:bg-blue-700" onClick={() => { setMessage(undefined); setView("prejoin"); }}>Check devices and rejoin</button></section> : null}
          </div>
          </TranscriptionProvider>
        </>}
        {info?.admitted ? <div className="mt-5"><CandidateWorkSample closed={Boolean(fatal && fatal.status > 0 && fatal.status < 500)} /></div> : null}
      </div>
    </main>
  );
}
