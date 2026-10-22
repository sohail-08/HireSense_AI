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
    <main className={`hiresense-meeting-workspace hiresense-console bg-slate-50 ${closed ? "hiresense-console-review" : ""}`}>
      <div className="hiresense-console-shell">
        {fatal || !info ? <Link className="text-sm font-semibold text-blue-700" to="/interviewer/interviews">← Back to interviews</Link> : null}
        {fatal ? <p role="alert" className="mt-6 rounded-xl bg-red-50 p-5 text-red-800">{fatal}</p> : !info ? <p role="status" className="mt-6">Loading interview console…</p> : <>
          <header className="hiresense-console-header border-b border-slate-200 pb-2">
            <div className="hiresense-console-heading">
              <Link className="hiresense-console-back" aria-label="Back to interviews" title="Back to interviews" to="/interviewer/interviews">←</Link>
              <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h1 className="text-lg font-bold tracking-tight sm:text-xl">Interview console</h1><span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${closed ? "bg-slate-200 text-slate-600" : access ? "bg-emerald-100 text-emerald-800" : "bg-blue-50 text-blue-700"}`}>{closed ? info.room_status === "ending" ? "Closing" : "Closed" : access ? "In the meeting" : "Getting ready"}</span></div>
              <div className="hiresense-console-meta"><p title={`${info.candidate_name} · ${info.job_title}`} className="truncate text-sm font-medium text-slate-700">{info.candidate_name} · {info.job_title}</p><p className="text-xs text-slate-500">{formatRoomTime(info.scheduled_start, info.timezone)}</p></div></div>
            </div>
            <div className="hiresense-console-toolbar">
            {!closed ? <section aria-label="Candidate admission" className="hiresense-console-admission">
              <p role="status" className={`hiresense-admission-status ${info.waiting ? "text-amber-700" : "text-slate-500"}`}><span aria-hidden="true" className={`h-1.5 w-1.5 shrink-0 rounded-full ${info.waiting ? "bg-amber-500" : info.admitted ? "bg-emerald-500" : "bg-slate-300"}`}/>{info.waiting ? "Candidate is waiting" : info.admitted ? "Candidate admitted" : "Waiting for the candidate to arrive"}</p>
              <div className="hiresense-admission-actions">
              <button className="rounded-xl bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:bg-slate-100 disabled:text-slate-400" disabled={busy || !info.waiting || info.admitted} onClick={() => void action(async () => setInfo(await roomApi.admit(id)))}>Admit candidate</button>
              <details className="relative"><summary aria-label="Candidate link options" className="hiresense-console-link-options"><span>Candidate link</span><svg aria-hidden="true" className="hiresense-console-link-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6" /></svg></summary><div className="absolute right-0 z-10 mt-2 flex w-52 flex-col gap-1 rounded-xl border border-slate-200 bg-white p-2 shadow-xl">
                <button className="rounded-lg px-3 py-2 text-left text-sm text-blue-700 hover:bg-blue-50 disabled:opacity-40" disabled={busy} onClick={() => info.link_origin_outdated ? setConfirmLink("rotate") : void copyLink()}>{info.link_origin_outdated ? "Update candidate link" : info.has_join_link && !info.link_revoked ? "Copy candidate link" : "Generate candidate link"}</button>
                <button className="rounded-lg px-3 py-2 text-left text-sm text-blue-700 hover:bg-blue-50" disabled={busy} onClick={() => setConfirmLink("rotate")}>Replace link</button>
                <button className="rounded-lg px-3 py-2 text-left text-sm text-red-700 hover:bg-red-50" disabled={busy || !info.has_join_link || info.link_revoked} onClick={() => setConfirmLink("revoke")}>Revoke link</button>
              </div></details>
              </div>
            </section> : null}
            <button type="button" aria-label={info.room_status === "ending" ? "Retry ending interview" : "End interview for everyone"} className="inline-flex min-h-10 items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm font-semibold text-red-700 hover:bg-red-100 disabled:border-slate-200 disabled:bg-slate-100 disabled:text-slate-400" disabled={busy || ["ended", "cancelled"].includes(info.room_status)} onClick={() => setConfirmEnd(true)}><MeetingIcon name="leave"/><span className="hiresense-console-end-label">{info.room_status === "ending" ? "Retry ending" : "End interview"}</span></button>
            </div>
          </header>
          {info.media_notice ? <p role="alert" className="shrink-0 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-900">{info.media_notice}</p> : null}
          {info.link_origin_outdated ? <p className="shrink-0 text-xs text-amber-900">This invitation uses a different website address. Update the candidate link before sharing it for this demo.</p> : null}
          {message ? <div role="alert" className="flex shrink-0 items-start justify-between gap-3 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-900"><p>{message}</p><button type="button" className="shrink-0 underline" onClick={() => setMessage(undefined)}>Dismiss</button></div> : null}
          {closed ? <section className="shrink-0 rounded-xl bg-white px-3 py-2"><h2 className="text-sm font-semibold">{info.room_status === "ending" ? "Room access is closed; finishing room shutdown" : info.room_status === "cancelled" ? "Interview cancelled" : "Interview ended"}</h2><p className="mt-1 text-xs text-slate-500">No new participant access can be issued.</p></section> : null}
          <TranscriptionProvider key={id} interviewId={id} closed={Boolean(closed)}>
          <div className="hiresense-console-grid" data-closed={Boolean(closed)}>
          {!closed ? <div className="hiresense-console-media-slot">
          {!access ? <div className="hiresense-console-device-setup"><DeviceCheck role="interviewer" onReady={setDevices} />{devices ? <button className="hiresense-console-join flex w-full shrink-0 items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:bg-slate-300" disabled={busy || Boolean(info.media_notice)} onClick={() => void connect()}><MeetingIcon name="camera"/>Join interview room</button> : null}</div> : null}
          {!closed && access && devices ? <InterviewMediaRoom access={access} devices={devices}
            onConnected={() => { void roomApi.interviewerConnected(id).then(setInfo).catch(() => setMessage("Media connected; room status could not be updated yet.")); }}
            onLeave={() => { setAccess(undefined); void roomApi.interviewerLeave(id).then(setInfo).catch(() => setMessage("You left media, but the application could not update your leave status.")); }}
            onEnded={() => { setAccess(undefined); void roomApi.status(id).then(setInfo).catch(() => setFatal("This interview is no longer available.")); }}
             /> : null}
          </div> : null}
          <aside className="hiresense-console-tools" aria-label="Interviewer workspace">
          <MeetingTabs fill={!closed} pageScroll={Boolean(closed)} variant="segmented" label="Workspace panel" tabs={[
            { id: "workspace-transcript", label: "Transcript & analysis", content: <div className="hiresense-console-transcript">
              <MeetingTabs fill={!closed} pageScroll={Boolean(closed)} label="Interview workspace" tabs={[
            { id: "transcript", label: "Live transcript", content: <TranscriptionPanel closed={Boolean(closed)} panelScroll={!closed} pageScroll={Boolean(closed)} /> },
            { id: "analysis", label: "Answer analysis", content: <InterviewAnalysisPanel key={id} interviewId={id} /> },
              ]} />
            </div> },
            { id: "workspace-private", label: "Candidate & assistant", content: <div className="hiresense-console-side"><InterviewCopilotPanel fill={!closed} pageScroll={Boolean(closed)} key={id} interviewId={id} /></div> },
          ]} />
          </aside>
          </div>
          </TranscriptionProvider>
          {confirmEnd ? <PreviewModal title="End this interview?" onClose={() => setConfirmEnd(false)} busy={busy}><p className="text-slate-600">Everyone will be disconnected and the candidate will no longer be able to rejoin.</p><div className="mt-5 flex flex-wrap justify-end gap-3"><button className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm" disabled={busy} onClick={() => setConfirmEnd(false)}>Keep interview open</button><button className="rounded-xl bg-red-600 px-4 py-2.5 text-sm font-semibold text-white" disabled={busy} onClick={() => void end()}>Confirm end interview</button></div></PreviewModal> : null}
          {confirmLink ? <PreviewModal title={confirmLink === "rotate" ? "Replace candidate link?" : "Revoke candidate access?"} onClose={() => setConfirmLink(undefined)} busy={busy}><p className="text-slate-600">Old candidate access and sessions will stop working. No replacement email is sent automatically.</p><div className="mt-5 flex justify-end gap-3"><button className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm" disabled={busy} onClick={() => setConfirmLink(undefined)}>Cancel</button><button className="rounded-xl bg-red-600 px-4 py-2.5 text-sm font-semibold text-white" disabled={busy} onClick={() => { const operation = confirmLink; setConfirmLink(undefined); if (operation === "rotate") void copyLink("/rotate"); else void action(async () => setInfo(await roomApi.revoke(id))); }}>Confirm</button></div></PreviewModal> : null}
        </>}
      </div>
    </main>
  );
}
