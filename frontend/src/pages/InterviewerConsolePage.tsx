import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/apiClient";
import { DeviceCheck } from "../components/interviews/DeviceCheck";
import { InterviewMediaRoom } from "../components/interviews/InterviewMediaRoom";
import { InterviewCopilotPanel } from "../components/interviews/InterviewCopilotPanel";
import { roomApi, type InterviewerRoomInfo, type DeviceChoices, type MediaAccess } from "../components/interviews/roomApi";
import { formatRoomTime } from "../components/interviews/roomState";
import { TranscriptionProvider, TranscriptionPanel } from "../components/interviews/TranscriptionPanel";

export function InterviewerConsolePage() {
  const id = Number(useParams().interviewId);
  const [info, setInfo] = useState<InterviewerRoomInfo>();
  const [devices, setDevices] = useState<DeviceChoices>();
  const [access, setAccess] = useState<MediaAccess>();
  const [fatal, setFatal] = useState<string>();
  const [message, setMessage] = useState<string>();
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const [confirmEnd, setConfirmEnd] = useState(false);
  const [confirmLink, setConfirmLink] = useState<"rotate" | "revoke">();
  useEffect(() => {
    let active = true;
    let polling = false;
    async function refresh() {
      if (polling) return;
      polling = true;
      try {
        const result = await roomApi.status(id);
        if (active) { setInfo(result); if (["ending", "ended", "cancelled"].includes(result.room_status)) setAccess(undefined); }
      } catch (failure) {
        if (active) setFatal(failure instanceof ApiError && [401, 403, 404].includes(failure.status) ? "You are not authorized to open this interview, or it no longer exists." : "Could not load this interview. Check your connection and reload.");
      } finally { polling = false; }
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2500);
    return () => { active = false; window.clearInterval(timer); };
  }, [id]);
  async function action(work: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setMessage(undefined);
    try { await work(); } catch (failure) { setMessage(failure instanceof Error ? failure.message : "Interview action failed. Please retry."); }
    finally { lock.current = false; setBusy(false); }
  }
  async function connect() {
    await action(async () => { setAccess(await roomApi.interviewerMedia(id)); });
  }
  async function end() {
    setConfirmEnd(false);
    await action(async () => { const result = await roomApi.end(id); setInfo(result); setAccess(undefined); });
  }
  async function copyLink(operation = "") {
    await action(async () => {
      const result = await roomApi.link(id, operation);
      try { await navigator.clipboard.writeText(result.join_url); setMessage("Candidate link copied. Share it privately; no email was sent."); }
      catch { setMessage("Clipboard unavailable. Use a browser with clipboard permission, or share the link through a reviewed invitation."); }
      setInfo(await roomApi.status(id));
    });
  }
  const closed = info && ["ending", "ended", "cancelled"].includes(info.room_status);
  return (
    <main className="min-h-screen bg-slate-100 px-4 py-8">
      <div className="mx-auto max-w-[1600px]">
        <Link className="text-sm font-semibold text-blue-700" to="/interviewer/interviews">← Back to interviews</Link>
        {fatal ? <p role="alert" className="mt-6 rounded-xl bg-red-50 p-5 text-red-800">{fatal}</p> : !info ? <p role="status" className="mt-6">Loading interview console…</p> : <>
          <h1 className="mt-5 text-2xl font-bold">Interview console</h1>
          <p className="mt-2 font-medium">{info.candidate_name} · {info.job_title}</p>
          <p className="mt-1 text-sm text-slate-600">{formatRoomTime(info.scheduled_start, info.timezone)} ({info.timezone}) · {info.room_status}</p>
          {info.media_notice ? <p role="alert" className="mt-4 rounded-xl bg-amber-50 p-4 text-amber-900">{info.media_notice}</p> : null}
          {info.link_origin_outdated ? <p className="mt-3 text-sm text-amber-900">This invitation uses a different website address. Update the candidate link before sharing it for this demo.</p> : null}
          {message ? <p role="alert" className="mt-4 rounded-xl bg-amber-50 p-4 text-amber-900">{message}</p> : null}
          {!closed ? <section className="mt-5 flex flex-wrap items-center gap-3 rounded-2xl bg-white p-4 shadow-sm">
            <p role="status" className="mr-auto font-medium">{info.waiting ? "Candidate is waiting" : info.admitted ? "Candidate admitted" : "Candidate has not entered the waiting room"}</p>
            <button className="rounded-lg bg-emerald-600 px-4 py-2 font-semibold text-white disabled:bg-slate-300" disabled={busy || !info.waiting || info.admitted} onClick={() => void action(async () => setInfo(await roomApi.admit(id)))}>Admit candidate</button>
            <button className="rounded-lg border px-3 py-2 text-sm" disabled={busy} onClick={() => info.link_origin_outdated ? setConfirmLink("rotate") : void copyLink()}>{info.link_origin_outdated ? "Update candidate link" : info.has_join_link && !info.link_revoked ? "Copy candidate link" : "Generate candidate link"}</button>
            <button className="text-sm text-blue-700" disabled={busy} onClick={() => setConfirmLink("rotate")}>Replace link</button>
            <button className="text-sm text-red-700" disabled={busy || !info.has_join_link || info.link_revoked} onClick={() => setConfirmLink("revoke")}>Revoke link</button>
          </section> : <section className="mt-5 rounded-xl bg-white p-5"><h2 className="text-lg font-semibold">{info.room_status === "ending" ? "Room access is closed; finishing room shutdown" : info.room_status === "cancelled" ? "Interview cancelled" : "Interview ended"}</h2><p className="mt-2 text-slate-600">No new participant access can be issued.</p></section>}
          <TranscriptionProvider key={id} interviewId={id} closed={Boolean(closed)}>
          <div className="mt-6 grid min-w-0 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(340px,400px)]">
          <div className="min-w-0">
          {!closed && !access ? <div><DeviceCheck role="interviewer" onReady={setDevices} />{devices ? <button className="mt-4 rounded-lg bg-blue-600 px-4 py-2 font-semibold text-white" disabled={busy || Boolean(info.media_notice)} onClick={() => void connect()}>Join interview room</button> : null}</div> : null}
          {!closed && access && devices ? <div className="mt-6"><InterviewMediaRoom access={access} devices={devices}
            onConnected={() => { void roomApi.interviewerConnected(id).then(setInfo).catch(() => setMessage("Media connected; room status could not be updated yet.")); }}
            onLeave={() => { setAccess(undefined); void roomApi.interviewerLeave(id).then(setInfo).catch(() => setMessage("You left media, but the application could not update your leave status.")); }}
            onEnded={() => { setAccess(undefined); void roomApi.status(id).then(setInfo).catch(() => setFatal("This interview is no longer available.")); }}
            onEnd={() => setConfirmEnd(true)} /></div> : null}
          {info.room_status !== "ended" && info.room_status !== "cancelled" && !access ? <button className="mt-6 rounded-lg bg-red-600 px-4 py-2 font-semibold text-white" disabled={busy} onClick={() => setConfirmEnd(true)}>{info.room_status === "ending" ? "Retry ending interview" : "End interview for everyone"}</button> : null}
          <TranscriptionPanel closed={Boolean(closed)} />
          </div>
          <InterviewCopilotPanel key={id} interviewId={id} />
          </div>
          </TranscriptionProvider>
          {confirmEnd ? <div role="dialog" aria-modal="true" aria-labelledby="end-room-title" className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"><section className="w-full max-w-md rounded-2xl bg-white p-6"><h2 id="end-room-title" className="text-xl font-bold">End this interview?</h2><p className="mt-3 text-slate-600">Everyone will be disconnected and the candidate will no longer be able to rejoin.</p><div className="mt-5 flex justify-end gap-3"><button className="rounded-lg border px-4 py-2" onClick={() => setConfirmEnd(false)}>Keep interview open</button><button className="rounded-lg bg-red-600 px-4 py-2 text-white" disabled={busy} onClick={() => void end()}>Confirm end interview</button></div></section></div> : null}
          {confirmLink ? <div role="dialog" aria-modal="true" aria-label="Change candidate link" className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"><section className="max-w-md rounded-2xl bg-white p-6"><h2 className="text-xl font-bold">{confirmLink === "rotate" ? "Replace candidate link?" : "Revoke candidate access?"}</h2><p className="mt-3 text-slate-600">Old candidate access and sessions will stop working. No replacement email is sent automatically.</p><div className="mt-5 flex justify-end gap-3"><button onClick={() => setConfirmLink(undefined)}>Cancel</button><button className="rounded-lg bg-red-600 px-4 py-2 text-white" onClick={() => { const operation = confirmLink; setConfirmLink(undefined); if (operation === "rotate") void copyLink("/rotate"); else void action(async () => setInfo(await roomApi.revoke(id))); }}>Confirm</button></div></section></div> : null}
        </>}
      </div>
    </main>
  );
}
