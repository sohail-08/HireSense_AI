import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/apiClient";
import { DeviceCheck } from "../components/interviews/DeviceCheck";
import { InterviewMediaRoom } from "../components/interviews/InterviewMediaRoom";
import { InterviewCopilotPanel } from "../components/interviews/InterviewCopilotPanel";
import { roomApi, type InterviewerRoomInfo, type DeviceChoices, type MediaAccess } from "../components/interviews/roomApi";
import { formatRoomTime } from "../components/interviews/roomState";
import { TranscriptionProvider, TranscriptionPanel } from "../components/interviews/TranscriptionPanel";
import { InterviewAnalysisPanel } from "../components/interviews/InterviewAnalysisPanel";
import { MeetingTabs } from "../components/interviews/MeetingTabs";
import { MeetingIcon } from "../components/interviews/MeetingIcon";
import { PreviewModal } from "../components/common/PreviewModal";

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
    <main className="hiresense-meeting-workspace min-h-screen min-w-0 bg-slate-50 px-3 py-5 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-[1600px]">
        <Link className="text-sm font-semibold text-blue-700" to="/interviewer/interviews">← Back to interviews</Link>
        {fatal ? <p role="alert" className="mt-6 rounded-xl bg-red-50 p-5 text-red-800">{fatal}</p> : !info ? <p role="status" className="mt-6">Loading interview console…</p> : <>
          <header className="mt-5 flex flex-wrap items-start justify-between gap-4 border-b border-slate-200 pb-5">
            <div className="min-w-0"><div className="flex flex-wrap items-center gap-3"><h1 className="text-2xl font-bold tracking-tight">Interview console</h1><span className={`rounded-full px-3 py-1 text-xs font-semibold ${closed ? "bg-slate-200 text-slate-600" : access ? "bg-emerald-100 text-emerald-800" : "bg-blue-50 text-blue-700"}`}>{closed ? info.room_status === "ending" ? "Closing" : "Closed" : access ? "In the meeting" : "Getting ready"}</span></div>
              <p className="mt-2 break-words text-sm font-medium text-slate-700">{info.candidate_name} · {info.job_title}</p>
              <p className="mt-1 text-xs text-slate-500">{formatRoomTime(info.scheduled_start, info.timezone)}</p></div>
            <button type="button" className="inline-flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700 hover:bg-red-100 disabled:border-slate-200 disabled:bg-slate-100 disabled:text-slate-400" disabled={busy || ["ended", "cancelled"].includes(info.room_status)} onClick={() => setConfirmEnd(true)}><MeetingIcon name="leave"/>{info.room_status === "ending" ? "Retry ending interview" : "End interview for everyone"}</button>
          </header>
          {info.media_notice ? <p role="alert" className="mt-4 rounded-xl bg-amber-50 p-4 text-amber-900">{info.media_notice}</p> : null}
          {info.link_origin_outdated ? <p className="mt-3 text-sm text-amber-900">This invitation uses a different website address. Update the candidate link before sharing it for this demo.</p> : null}
          {message ? <p role="alert" className="mt-4 rounded-xl bg-amber-50 p-4 text-amber-900">{message}</p> : null}
          {!closed ? <section aria-label="Candidate admission" className="mt-5 flex flex-wrap items-center gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
            <p role="status" className="mr-auto text-sm font-medium text-slate-700">{info.waiting ? "Candidate is waiting" : info.admitted ? "Candidate admitted" : "Waiting for the candidate to arrive"}</p>
            <button className="rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:bg-slate-100 disabled:text-slate-400" disabled={busy || !info.waiting || info.admitted} onClick={() => void action(async () => setInfo(await roomApi.admit(id)))}>Admit candidate</button>
            <button className="rounded-xl border border-slate-200 px-3 py-2.5 text-sm font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-40" disabled={busy} onClick={() => info.link_origin_outdated ? setConfirmLink("rotate") : void copyLink()}>{info.link_origin_outdated ? "Update candidate link" : info.has_join_link && !info.link_revoked ? "Copy candidate link" : "Generate candidate link"}</button>
            <details className="relative"><summary className="rounded-xl px-3 py-2.5 text-sm font-medium text-slate-500 hover:bg-slate-50">Link options</summary><div className="absolute right-0 z-10 mt-2 flex w-44 flex-col gap-1 rounded-xl border border-slate-200 bg-white p-2 shadow-xl">
              <button className="rounded-lg px-3 py-2 text-left text-sm text-blue-700 hover:bg-blue-50" disabled={busy} onClick={() => setConfirmLink("rotate")}>Replace link</button>
              <button className="rounded-lg px-3 py-2 text-left text-sm text-red-700 hover:bg-red-50" disabled={busy || !info.has_join_link || info.link_revoked} onClick={() => setConfirmLink("revoke")}>Revoke link</button>
            </div></details>
          </section> : <section className="mt-5 rounded-xl bg-white p-5"><h2 className="text-lg font-semibold">{info.room_status === "ending" ? "Room access is closed; finishing room shutdown" : info.room_status === "cancelled" ? "Interview cancelled" : "Interview ended"}</h2><p className="mt-2 text-slate-600">No new participant access can be issued.</p></section>}
          <TranscriptionProvider key={id} interviewId={id} closed={Boolean(closed)}>
          <div className="mt-5 grid min-w-0 items-start gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(19rem,23rem)]">
          <div className="min-w-0 space-y-5">
          {!closed && !access ? <div><DeviceCheck role="interviewer" onReady={setDevices} />{devices ? <button className="mt-3 flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 px-5 py-3 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:bg-slate-300" disabled={busy || Boolean(info.media_notice)} onClick={() => void connect()}><MeetingIcon name="camera"/>Join interview room</button> : null}</div> : null}
          {!closed && access && devices ? <InterviewMediaRoom access={access} devices={devices}
            onConnected={() => { void roomApi.interviewerConnected(id).then(setInfo).catch(() => setMessage("Media connected; room status could not be updated yet.")); }}
            onLeave={() => { setAccess(undefined); void roomApi.interviewerLeave(id).then(setInfo).catch(() => setMessage("You left media, but the application could not update your leave status.")); }}
            onEnded={() => { setAccess(undefined); void roomApi.status(id).then(setInfo).catch(() => setFatal("This interview is no longer available.")); }}
             /> : null}
          <MeetingTabs label="Interview workspace" tabs={[
            { id: "transcript", label: "Live transcript", content: <TranscriptionPanel closed={Boolean(closed)} /> },
            { id: "analysis", label: "Answer analysis", content: <InterviewAnalysisPanel key={id} interviewId={id} /> },
          ]} />
          </div>
          <InterviewCopilotPanel key={id} interviewId={id} />
          </div>
          </TranscriptionProvider>
          {confirmEnd ? <PreviewModal title="End this interview?" onClose={() => setConfirmEnd(false)} busy={busy}><p className="text-slate-600">Everyone will be disconnected and the candidate will no longer be able to rejoin.</p><div className="mt-5 flex flex-wrap justify-end gap-3"><button className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm" disabled={busy} onClick={() => setConfirmEnd(false)}>Keep interview open</button><button className="rounded-xl bg-red-600 px-4 py-2.5 text-sm font-semibold text-white" disabled={busy} onClick={() => void end()}>Confirm end interview</button></div></PreviewModal> : null}
          {confirmLink ? <PreviewModal title={confirmLink === "rotate" ? "Replace candidate link?" : "Revoke candidate access?"} onClose={() => setConfirmLink(undefined)} busy={busy}><p className="text-slate-600">Old candidate access and sessions will stop working. No replacement email is sent automatically.</p><div className="mt-5 flex justify-end gap-3"><button className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm" disabled={busy} onClick={() => setConfirmLink(undefined)}>Cancel</button><button className="rounded-xl bg-red-600 px-4 py-2.5 text-sm font-semibold text-white" disabled={busy} onClick={() => { const operation = confirmLink; setConfirmLink(undefined); if (operation === "rotate") void copyLink("/rotate"); else void action(async () => setInfo(await roomApi.revoke(id))); }}>Confirm</button></div></PreviewModal> : null}
        </>}
      </div>
    </main>
  );
}
