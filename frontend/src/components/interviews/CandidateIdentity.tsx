import { useEffect, useRef, useState } from "react";
import { useLocalParticipant } from "@livekit/components-react";
import { type Track } from "livekit-client";
import { identityApi, type CandidateIdentityState } from "./identityApi";
import { exerciseButton, exercisePrimary } from "./WorkSampleShared";

async function sample(track: Track, current: () => boolean): Promise<string[]> {
  const video = document.createElement("video");
  video.muted = true; video.playsInline = true;
  // Reuse the already-published local camera; never request a new device or record video.
  video.srcObject = new MediaStream([track.mediaStreamTrack]);
  try {
    await video.play();
    const frames: string[] = [];
    for (let i = 0; i < 3; i++) {
      await new Promise(resolve => window.setTimeout(resolve, 500));
      if (!current() || track.mediaStreamTrack.readyState !== "live" || !video.videoWidth || !video.videoHeight) throw new Error("Camera sample cancelled. No result was saved.");
      const canvas = document.createElement("canvas");
      const scale = Math.min(640 / video.videoWidth, 640 / video.videoHeight);
      canvas.width = Math.round(video.videoWidth * scale); canvas.height = Math.round(video.videoHeight * scale);
      const context = canvas.getContext("2d");
      if (!context) throw new Error("Camera sampling is unavailable.");
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      frames.push(canvas.toDataURL("image/jpeg", .85).split(",")[1]);
      canvas.width = canvas.height = 0;
    }
    return frames;
  } finally { video.pause(); video.srcObject = null; }
}

export function CandidateIdentity({ track, inRoom = false }: { track?: Track; inRoom?: boolean }) {
  const [state, setState] = useState<CandidateIdentityState>();
  const [error, setError] = useState("");
  const [agree, setAgree] = useState(false), [busy, setBusy] = useState(false), [confirmWithdraw, setConfirmWithdraw] = useState(false);
  const live = useRef(true), epoch = useRef(0), locked = useRef(false), automatic = useRef("");
  const capture = async (value: CandidateIdentityState) => {
    if (!track || locked.current || !value.consented || !value.reference_ready || !value.capture_available) return;
    locked.current = true; setBusy(true); setError("");
    const attempt = ++epoch.current;
    const current = () => live.current && epoch.current === attempt;
    try { const frames = await sample(track, current); if (current()) { const result = await identityApi.verify(frames, value.version); if (current()) setState(result); } }
    catch { if (current()) setError("Camera samples could not be sent. Check your camera and retry; you can still continue with the interview."); }
    finally { locked.current = false; if (live.current) setBusy(false); }
  };
  useEffect(() => {
    live.current = true;
    let polling = false;
    const refresh = async () => {
      if (polling || locked.current) return;
      polling = true; const expected = epoch.current;
      try { const value = await identityApi.candidate(); if (live.current && expected === epoch.current) { setState(value); setError(""); } }
      catch { if (live.current) setError("Photo verification status is unavailable. You can still join the interview."); }
      finally { polling = false; }
    };
    void refresh(); const timer = window.setInterval(() => void refresh(), 2500);
    return () => { live.current = false; epoch.current += 1; window.clearInterval(timer); };
  }, []);
  useEffect(() => () => { epoch.current += 1; }, [track]);
  useEffect(() => {
    if (inRoom && track && state?.consented && state.reference_ready && state.capture_available && state.status === "not_checked") {
      const key = `${state.version}`;
      if (!locked.current && automatic.current !== key) { automatic.current = key; void capture(state); }
    }
  }, [inRoom, track, state?.consented, state?.reference_ready, state?.capture_available, state?.status, state?.version, busy]);
  async function consent(allow: boolean) {
    if (!state || locked.current) return;
    locked.current = true; epoch.current += 1; setBusy(true); setError("");
    try { const value = await identityApi.consent(allow, state.notice_version); if (live.current) setState(value); }
    catch (e) { if (live.current) setError(e instanceof Error ? e.message : "Could not save your choice."); }
    finally { locked.current = false; if (live.current) setBusy(false); }
  }
  async function withdraw() {
    if (locked.current) return;
    locked.current = true;
    epoch.current += 1; setBusy(true); setError("");
    try { const value = await identityApi.withdraw(); if (live.current) { setState(value); setConfirmWithdraw(false); setAgree(false); } }
    catch { if (live.current) setError("Withdrawal could not be confirmed. Keep the camera off and retry."); }
    finally { locked.current = false; if (live.current) setBusy(false); }
  }
  // Do not render arbitrary API messages: even an older server response must
  // not put comparison outcomes or manual decisions into the candidate view.
  const candidateMessage = state?.status === "withdrawn" ? "Consent withdrawn. Your HireSense face data has been deleted."
    : state?.status === "declined" ? "Photo verification skipped. You can continue with your interview."
    : state?.status === "pending_consent" ? "Choose whether to allow optional photo verification."
    : state?.status === "preparing" ? "Preparing photo verification."
    : state?.status === "unavailable" ? "Photo verification is unavailable. You can continue with your interview."
    : state?.status === "not_checked" ? "Consent saved. Camera samples can be captured after you join."
    : "Verification submitted. Your interviewer will review it.";
  return <section aria-label="Optional photo verification" className="rounded-2xl border border-indigo-100 bg-white p-5 text-slate-800 shadow-sm">
    <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-sm font-semibold">Optional photo verification</h2><span className="rounded-full bg-indigo-50 px-2.5 py-1 text-xs font-medium text-indigo-700">Does not affect scores</span></div>
    {error ? <p role="alert" className="mt-3 text-sm text-amber-800">{error}</p> : null}
    {state ? <><p role="status" className="mt-3 text-sm font-medium">{busy ? "Working…" : error ? "Camera sampling is not complete" : candidateMessage}</p>
      <p className="mt-2 text-xs leading-5 text-slate-500">Only your interviewer sees the photo-match result. This does not prove legal identity or provide an anti-spoofing guarantee. Your interviewer can verify you manually.</p>
      <details className="mt-3 text-xs text-slate-500"><summary className="cursor-pointer">How your photo is used</summary><p className="mt-2 leading-6">{state.notice}</p></details>
      {state.reference_available && !state.consented && !["submitted", "matched", "manual", "withdrawn"].includes(state.status) ? <>
        <label className="mt-4 flex items-start gap-2 text-sm"><input type="checkbox" checked={agree} disabled={busy} onChange={e => setAgree(e.target.checked)} className="mt-1"/>I consent to creating a face template from my application photo and matching camera samples during this interview.</label>
        <div className="mt-3 flex flex-wrap gap-2"><button className={exercisePrimary} disabled={!agree || busy} onClick={() => void consent(true)}>Allow photo verification</button><button className={exerciseButton} disabled={busy} onClick={() => void consent(false)}>Continue without face matching</button></div>
      </> : null}
      {state.consented && state.reference_ready && state.status !== "submitted" && !inRoom ? <p className="mt-3 text-sm text-indigo-700">Consent saved. Matching starts after you join with your camera on.</p> : null}
      {state.capture_available && inRoom ? <button className={`${exercisePrimary} mt-3`} disabled={busy || !track} onClick={() => void capture(state)}>{track ? state.status === "not_checked" ? "Capture camera samples" : "Retake camera samples" : "Turn on camera to capture"}</button> : null}
      {state.consented || state.reference_available ? <button className="mt-3 block text-xs font-medium text-slate-500 underline" disabled={busy} onClick={() => setConfirmWithdraw(true)}>Withdraw consent and delete my face data</button> : null}
      {confirmWithdraw ? <div className="mt-3 rounded-xl bg-amber-50 p-3 text-sm"><p>Delete HireSense’s photo copy and face template for this application? This does not delete the original Google Drive upload or affect your interview.</p><div className="mt-3 flex gap-2"><button className={exerciseButton} disabled={busy} onClick={() => setConfirmWithdraw(false)}>Cancel</button><button className={exercisePrimary} disabled={busy} onClick={() => void withdraw()}>Confirm withdrawal</button></div></div> : null}
    </> : <p role="status" className="mt-3 text-sm text-slate-500">Checking application-photo availability…</p>}
  </section>;
}

export function CandidateCameraIdentity() {
  const { cameraTrack, isCameraEnabled } = useLocalParticipant();
  return <CandidateIdentity inRoom track={isCameraEnabled ? cameraTrack?.track : undefined} />;
}
