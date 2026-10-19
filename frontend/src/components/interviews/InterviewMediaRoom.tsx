import { useMemo, useState } from "react";
import { LiveKitRoom, ParticipantTile, RoomAudioRenderer, TrackToggle, DisconnectButton,
  useConnectionState, useTracks, useLocalParticipant, StartAudio } from "@livekit/components-react";
import { Track, LogLevel, setLogLevel, DisconnectReason } from "livekit-client";
import "@livekit/components-styles";
import type { MediaAccess, DeviceChoices } from "./roomApi";
import { deviceMessage } from "./roomState";
import { TranscriptReceiver } from "./TranscriptionPanel";

// Never let browser diagnostics accidentally print a media JWT or signaling URL.
setLogLevel(LogLevel.silent);

function Controls({ onEnd, onDeviceError }: { onEnd?: () => void; onDeviceError: (error: Error) => void }) {
  const connection = useConnectionState();
  const tracks = useTracks([{ source: Track.Source.Camera, withPlaceholder: true }], { onlySubscribed: false });
  const { isMicrophoneEnabled, isCameraEnabled } = useLocalParticipant();
  const roles = ["Interviewer", "Candidate"];
  return (
    <>
      <p role="status" className="mb-3 text-sm text-slate-200">{String(connection).toLowerCase().includes("reconnect") ? "Reconnecting… Please keep this page open." : `Connection: ${connection}`}</p>
      <div className="grid gap-4 md:grid-cols-2">
        {roles.map((role) => {
          const ref = tracks.find((item) => item.participant.name === role);
          return <div key={role} className="min-h-56 overflow-hidden rounded-xl bg-slate-800">
            {ref ? <ParticipantTile trackRef={ref} /> : <div className="flex min-h-56 items-center justify-center p-5 text-slate-300">Waiting for {role.toLowerCase()}…</div>}
          </div>;
        })}
      </div>
      <RoomAudioRenderer />
      <StartAudio label="Enable interview audio" />
      <div className="mt-5 flex flex-wrap justify-center gap-3">
        <TrackToggle source={Track.Source.Microphone} aria-pressed={isMicrophoneEnabled} onDeviceError={onDeviceError}>{isMicrophoneEnabled ? "Mute microphone" : "Unmute microphone"}</TrackToggle>
        <TrackToggle source={Track.Source.Camera} aria-pressed={isCameraEnabled} onDeviceError={onDeviceError}>{isCameraEnabled ? "Turn camera off" : "Turn camera on"}</TrackToggle>
        <DisconnectButton>Leave room</DisconnectButton>
        {onEnd ? <button className="rounded-lg bg-red-600 px-4 py-2 font-semibold text-white" onClick={onEnd}>End interview for everyone</button> : null}
      </div>
    </>
  );
}

export function InterviewMediaRoom({ access, devices, onConnected, onLeave, onEnded, onEnd }:
  { access: MediaAccess; devices: DeviceChoices; onConnected: () => void; onLeave: () => void; onEnded: () => void; onEnd?: () => void }) {
  const [error, setError] = useState<string>();
  const showError = (failure: Error) => setError(deviceMessage(failure));
  const audio = useMemo(() => devices.audioEnabled ? { deviceId: devices.audioDeviceId || undefined } : false,
    [devices.audioEnabled, devices.audioDeviceId]);
  const video = useMemo(() => devices.videoEnabled ? { deviceId: devices.videoDeviceId || undefined } : false,
    [devices.videoEnabled, devices.videoDeviceId]);
  const options = useMemo(() => ({ adaptiveStream: true, dynacast: true,
    audioCaptureDefaults: { deviceId: devices.audioDeviceId || undefined },
    videoCaptureDefaults: { deviceId: devices.videoDeviceId || undefined } }), [devices.audioDeviceId, devices.videoDeviceId]);
  return (
    <section className="overflow-hidden rounded-2xl bg-slate-950 p-5 text-white" data-lk-theme="default">
      {error ? <p role="alert" className="mb-4 rounded-lg bg-amber-100 p-3 text-sm text-amber-900">{error} Leave and rejoin to request fresh access if needed.</p> : null}
      <LiveKitRoom token={access.participant_token} serverUrl={access.server_url} connect
        audio={audio} video={video} screen={false} options={options}
        onConnected={onConnected} onError={showError}
        onMediaDeviceFailure={() => setError("A camera or microphone failed. Check permissions or choose another input when you rejoin.")}
        onDisconnected={(reason) => reason === DisconnectReason.ROOM_DELETED ? onEnded() : onLeave()}>
        <Controls onEnd={onEnd} onDeviceError={showError} />
        <TranscriptReceiver />
      </LiveKitRoom>
    </section>
  );
}
