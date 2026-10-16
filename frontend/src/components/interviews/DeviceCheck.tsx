import { useState } from "react";
import { PreJoin } from "@livekit/components-react";
import { isBrowserSupported } from "livekit-client";
import "@livekit/components-styles";
import type { DeviceChoices } from "./roomApi";
import { deviceMessage } from "./roomState";

export function DeviceCheck({ role, onReady }: { role: "candidate" | "interviewer"; onReady: (choices: DeviceChoices) => void }) {
  const [enabled, setEnabled] = useState(false);
  const [error, setError] = useState<string>();
  if (!enabled) return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-lg font-semibold">Check your camera and microphone</h2>
      <p className="mt-2 text-sm text-slate-600">Nothing is recorded. Your browser will ask for device permission only after you click below.</p>
      {error ? <p role="alert" className="mt-3 text-sm text-red-700">{error}</p> : null}
      <button className="mt-4 rounded-lg bg-blue-600 px-4 py-2 font-semibold text-white" onClick={() => {
        if (!isBrowserSupported() || !navigator.mediaDevices?.getUserMedia) {
          setError("This browser cannot start an interview. Use a current Chrome, Edge, Firefox or Safari browser on HTTPS (or localhost for testing).");
          return;
        }
        setEnabled(true);
      }}>Check devices</button>
    </section>
  );
  return (
    <section className="hiresense-device-check overflow-hidden rounded-2xl bg-slate-950 p-4" data-lk-theme="default">
      <p className="mb-3 text-sm text-slate-200">Select your devices and check the microphone level. You may continue with the camera or microphone off.</p>
      {error ? <p role="alert" className="mb-3 rounded-lg bg-amber-100 p-3 text-sm text-amber-900">{error}</p> : null}
      <PreJoin defaults={{ username: role === "candidate" ? "Candidate" : "Interviewer", audioEnabled: true, videoEnabled: true }}
        persistUserChoices={false} onValidate={() => true} joinLabel={role === "candidate" ? "Continue to waiting room" : "Devices ready"}
        onError={(failure) => setError(deviceMessage(failure))} onSubmit={onReady} />
    </section>
  );
}
