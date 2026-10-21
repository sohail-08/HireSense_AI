import { useState } from "react";
import { PreJoin } from "@livekit/components-react";
import { isBrowserSupported } from "livekit-client";
import "@livekit/components-styles";
import type { DeviceChoices } from "./roomApi";
import { deviceMessage } from "./roomState";
import { MeetingIcon } from "./MeetingIcon";

export function DeviceCheck({ role, onReady }: { role: "candidate" | "interviewer"; onReady: (choices: DeviceChoices) => void }) {
  const [enabled, setEnabled] = useState(false);
  const [error, setError] = useState<string>();
  if (!enabled) return (
    <section className="min-w-0 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="hiresense-prejoin-stage"><div className="flex max-w-sm flex-col items-center gap-4"><span className="rounded-3xl bg-slate-800 p-5"><MeetingIcon name="camera" className="h-10 w-10 text-blue-300"/></span><p className="text-xl font-semibold">Let’s get you ready</p><p className="text-sm leading-6 text-slate-400">Your camera preview will appear here. You are not connected to the meeting yet.</p></div></div>
      <div className="p-5 sm:flex sm:items-center sm:justify-between sm:gap-5"><div>
      <h2 className="font-semibold">Check your camera and microphone</h2>
      <p className="mt-1 text-sm text-slate-500">You can join with either device off. Nothing is recorded.</p>
      {error ? <p role="alert" className="mt-3 text-sm text-red-700">{error}</p> : null}
      </div><button className="mt-4 inline-flex shrink-0 items-center gap-2 rounded-xl bg-blue-600 px-5 py-3 text-sm font-semibold text-white hover:bg-blue-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 sm:mt-0" onClick={() => {
        if (!isBrowserSupported() || !navigator.mediaDevices?.getUserMedia) {
          setError("This browser cannot start an interview. Use a current Chrome, Edge, Firefox or Safari browser on HTTPS (or localhost for testing).");
          return;
        }
        setEnabled(true);
      }}><MeetingIcon name="camera"/>Check devices</button></div>
    </section>
  );
  return (
    <section className="hiresense-device-check min-w-0 overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 p-4" data-lk-theme="default">
      <p className="mb-3 text-sm leading-6 text-slate-300">Check your preview, choose your devices, then continue. Your microphone and camera can stay off.</p>
      {error ? <p role="alert" className="mb-3 rounded-lg bg-amber-100 p-3 text-sm text-amber-900">{error}</p> : null}
      <PreJoin defaults={{ username: role === "candidate" ? "Candidate" : "Interviewer", audioEnabled: true, videoEnabled: true }}
        persistUserChoices={false} onValidate={() => true} joinLabel={role === "candidate" ? "Continue to waiting room" : "Devices ready"}
        onError={(failure) => setError(deviceMessage(failure))} onSubmit={onReady} />
    </section>
  );
}
