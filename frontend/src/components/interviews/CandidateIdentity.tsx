import { useEffect, useRef, useState } from "react";
import { useLocalParticipant } from "@livekit/components-react";
import { type Track } from "livekit-client";
import { identityApi, type CandidateIdentityState } from "./identityApi";
import { transcriptionApi, type TranscriptionStatus } from "./transcriptionApi";

const CONSENT_CHANGED = "hiresense:candidate-consent-changed";

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

export function CandidateIdentity() {
  const [state, setState] = useState<CandidateIdentityState>();
  const [transcription, setTranscription] = useState<TranscriptionStatus>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const live = useRef(true), epoch = useRef(0), locked = useRef(false);
  useEffect(() => {
    live.current = true;
    let polling = false;
    const refresh = async () => {
      if (polling || locked.current) return;
      polling = true; const expected = epoch.current;
      try {
        const [photo, text] = await Promise.all([identityApi.candidate(), transcriptionApi.status()]);
        if (live.current && expected === epoch.current) { setState(photo); setTranscription(text); setError(""); }
      }
      catch { if (live.current) setError("Permissions could not be loaded. Your interview can still continue."); }
      finally { polling = false; }
    };
    void refresh(); const timer = window.setInterval(() => void refresh(), 2500);
    return () => { live.current = false; epoch.current += 1; window.clearInterval(timer); };
  }, []);
  const photoAvailable = Boolean(state?.enabled && (state.reference_available || state.consented));
  const textAvailable = Boolean(transcription?.enabled);
  const agreed = Boolean((photoAvailable || textAvailable) && (!photoAvailable || state?.consented) && (!textAvailable || transcription?.consented));
  const anyAgreed = Boolean((photoAvailable && state?.consented) || (textAvailable && transcription?.consented));
  async function consent(allow: boolean) {
    if (!state || !transcription || locked.current) return;
    locked.current = true; epoch.current += 1; setBusy(true); setError("");
    if (!allow) window.dispatchEvent(new Event(CONSENT_CHANGED));
    try {
      const actions: Promise<unknown>[] = [];
      if (photoAvailable && state.consented !== allow) actions.push(
        (allow ? identityApi.consent(true, state.notice_version) : identityApi.withdraw()).then(value => { if (live.current) setState(value); }));
      if (textAvailable && transcription.consented !== allow) actions.push(
        transcriptionApi.consent(allow).then(value => { if (live.current) setTranscription(value); }));
      const results = await Promise.allSettled(actions);
      if (live.current && results.some(result => result.status === "rejected")) setError("Not all permissions were saved. Review the checkbox and try again.");
    }
    finally { locked.current = false; if (live.current) setBusy(false); }
  }
  return <section aria-label="Interview consent" className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
    <h2 className="text-sm font-semibold text-slate-900">Interview permissions</h2>
    {state && transcription ? photoAvailable || textAvailable ? <>
      <label className="mt-3 flex cursor-pointer items-start gap-2.5 text-sm leading-5 text-slate-700"><input type="checkbox" checked={anyAgreed} ref={element => { if (element) element.indeterminate = anyAgreed && !agreed; }} disabled={busy} onChange={event => void consent(event.target.checked)} className="mt-0.5 h-4 w-4 shrink-0 accent-indigo-600"/>
        I agree to {textAvailable ? "live interview transcription" : "photo verification"}{textAvailable && photoAvailable ? " and photo verification" : ""}.</label>
      <p role="status" className="mt-2 text-xs leading-5 text-slate-500">{busy ? "Saving permissions…" : agreed ? "Consent saved. Your interviewer handles verification." : anyAgreed ? "Some permissions are saved. Uncheck to stop these features." : "Optional. You can still join without checking this box."}</p>
      <details className="mt-2 text-xs text-slate-500"><summary className="cursor-pointer font-medium">Privacy details</summary><div className="mt-2 space-y-2 leading-5">
        {textAvailable ? <p>{transcription.notice} Text is retained for {transcription.retention_days} days.</p> : null}
        {photoAvailable ? <p>{state.notice}</p> : null}
        <p>Uncheck the box to stop these features and remove HireSense’s face template. This does not change your interview scores or delete the original application upload.</p>
      </div></details>
    </> : <p className="mt-2 text-xs leading-5 text-slate-500">No additional permissions are needed. You can continue with your interview.</p>
      : !error ? <p role="status" className="mt-2 text-xs text-slate-500">Checking permissions…</p> : null}
    {error ? <p role="alert" className="mt-2 text-xs leading-5 text-amber-800">{error}</p> : null}
  </section>;
}

export function CandidateCameraIdentity() {
  const { cameraTrack, isCameraEnabled } = useLocalParticipant();
  const track = isCameraEnabled ? cameraTrack?.track : undefined;
  const epoch = useRef(0);
  useEffect(() => {
    let active = true, polling = false, suspended = false;
    let attempted: number | undefined;
    const cancel = () => { epoch.current += 1; suspended = true; };
    window.addEventListener(CONSENT_CHANGED, cancel);
    const refresh = async () => {
      if (polling || !track || suspended) return;
      polling = true;
      const readEpoch = epoch.current;
      try {
        const value = await identityApi.candidate();
        if (!active || suspended || readEpoch !== epoch.current || !value.consented || !value.reference_ready || !value.capture_available || attempted === value.version) return;
        attempted = value.version;
        const attempt = ++epoch.current;
        const current = () => active && epoch.current === attempt;
        const frames = await sample(track, current);
        if (current()) await identityApi.verify(frames, value.version);
      } catch { /* The interviewer can request fresh samples; never reveal outcomes here. */ }
      finally { polling = false; }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2500);
    return () => { active = false; cancel(); window.clearInterval(timer); window.removeEventListener(CONSENT_CHANGED, cancel); };
  }, [track]);
  return null;
}
