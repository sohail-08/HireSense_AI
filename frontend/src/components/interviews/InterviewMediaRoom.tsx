import { useMemo, useState } from "react";
import { LiveKitRoom, ParticipantTile, RoomAudioRenderer, TrackToggle, DisconnectButton,
  useConnectionState, useTracks, useLocalParticipant, StartAudio } from "@livekit/components-react";
import { Track, LogLevel, setLogLevel, DisconnectReason } from "livekit-client";
import "@livekit/components-styles";
import type { MediaAccess, DeviceChoices } from "./roomApi";
import { deviceMessage } from "./roomState";
import { TranscriptReceiver } from "./TranscriptionPanel";
import { MeetingIcon } from "./MeetingIcon";

// Never let browser diagnostics accidentally print a media JWT or signaling URL.
setLogLevel(LogLevel.silent);

function Controls({ role, onEnd, onDeviceError, onShareError }: {
  role: MediaAccess["role"]; onEnd?: () => void; onDeviceError: (error: Error) => void; onShareError: (error: Error) => void;
}) {
  const connection = useConnectionState();
  const tracks = useTracks([{ source: Track.Source.Camera, withPlaceholder: true }, { source: Track.Source.ScreenShare, withPlaceholder: false }], { onlySubscribed: false });
  const { isMicrophoneEnabled, isCameraEnabled, isScreenShareEnabled } = useLocalParticipant();
  const screen = tracks.find(item => item.source === Track.Source.ScreenShare && item.publication?.track);
  const canShare = typeof navigator.mediaDevices?.getDisplayMedia === "function";
  const reconnecting = String(connection).toLowerCase().includes("reconnect");
  const button = "hiresense-meeting-control";
  const cameras = <div className="hiresense-camera-grid">
    {["Interviewer", "Candidate"].map(name => {
      const ref = tracks.find(item => item.source === Track.Source.Camera && item.participant.name === name);
      const self = name.toLowerCase() === role;
      return <div key={name} className="hiresense-camera-tile" aria-label={`${name} video tile`}>
        {ref ? <ParticipantTile trackRef={ref} /> : <div className="hiresense-camera-placeholder"><MeetingIcon name="person" className="h-12 w-12 text-slate-500"/><p>{self ? "Your camera is off" : `Waiting for ${name.toLowerCase()}…`}</p></div>}
        <span className="hiresense-video-label">{self ? `You (${name})` : name}</span>
      </div>;
    })}
  </div>;
  return <>
    <div className="hiresense-connection-bar flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-xs">
      <p role="status" className="flex items-center gap-2 text-slate-300"><span className={`h-2 w-2 rounded-full ${connection === "connected" ? "bg-emerald-400" : "bg-amber-400"}`} />{reconnecting ? "Reconnecting… Please keep this page open." : connection === "connected" ? "Connected" : "Connecting to your interview…"}</p>
      <span className="flex items-center gap-1.5 text-slate-400"><MeetingIcon name="lock" className="h-3.5 w-3.5"/>Private interview · No recording</span>
    </div>
    <div className="hiresense-video-stage" data-sharing={Boolean(screen)} aria-label="Interview video area">
      {screen ? <div className="hiresense-screen-tile" aria-label="Candidate shared screen"><ParticipantTile trackRef={screen} /><span className="hiresense-video-label">{role === "candidate" ? "You are sharing your screen" : "Candidate’s screen"}</span></div> : null}
      {cameras}
    </div>
    <RoomAudioRenderer /><StartAudio className="hiresense-start-audio" label="Enable interview audio" />
    <div className="hiresense-meeting-controls" aria-label="Meeting controls">
      <TrackToggle className={button} source={Track.Source.Microphone} showIcon={false} aria-pressed={isMicrophoneEnabled} onDeviceError={onDeviceError}><MeetingIcon name="microphone"/>{isMicrophoneEnabled ? "Mute microphone" : "Unmute microphone"}</TrackToggle>
      <TrackToggle className={button} source={Track.Source.Camera} showIcon={false} aria-pressed={isCameraEnabled} onDeviceError={onDeviceError}><MeetingIcon name="camera"/>{isCameraEnabled ? "Turn camera off" : "Turn camera on"}</TrackToggle>
      {role === "candidate" ? canShare || isScreenShareEnabled ? <TrackToggle className={button + " hiresense-share-control"} source={Track.Source.ScreenShare} showIcon={false}
        aria-pressed={isScreenShareEnabled} captureOptions={{ audio: false, contentHint: "detail", selfBrowserSurface: "exclude", systemAudio: "exclude" }} onDeviceError={onShareError}>
        <MeetingIcon name="screen"/>{isScreenShareEnabled ? "Stop sharing screen" : "Share screen"}</TrackToggle>
        : <button type="button" className={button} disabled aria-describedby="screen-share-unavailable"><MeetingIcon name="screen"/>Share screen</button> : null}
      <DisconnectButton className={button + " hiresense-leave-control"}><MeetingIcon name="leave"/>Leave room</DisconnectButton>
      {onEnd ? <button type="button" className={button + " hiresense-end-control"} onClick={onEnd}><MeetingIcon name="leave"/>End interview for everyone</button> : null}
    </div>
    {role === "candidate" && !canShare && !isScreenShareEnabled ? <p id="screen-share-unavailable" className="px-4 pb-4 text-center text-xs leading-5 text-slate-400">This browser cannot share your screen. Use a supported desktop browser to present; you can still join the interview here.</p> : null}
    {isScreenShareEnabled ? <p role="status" className="px-4 pb-4 text-center text-xs text-blue-200">Your screen is visible to the interviewer. Select Stop sharing screen when you’re done.</p> : null}
  </>;
}

export function InterviewMediaRoom({ access, devices, onConnected, onLeave, onEnded, onEnd }:
  { access: MediaAccess; devices: DeviceChoices; onConnected: () => void; onLeave: () => void; onEnded: () => void; onEnd?: () => void }) {
  const [error, setError] = useState<string>();
  const showError = (failure: Error) => setError(deviceMessage(failure));
  const shareError = (failure: Error) => setError(["NotAllowedError", "AbortError"].includes(failure.name)
    ? "Screen sharing was cancelled or blocked. Select Share screen to try again and choose a tab, window or screen."
    : "Screen sharing could not start. Check browser support and screen-capture permissions, then try again. Your camera and microphone are unaffected.");
  const audio = useMemo(() => devices.audioEnabled ? { deviceId: devices.audioDeviceId || undefined } : false,
    [devices.audioEnabled, devices.audioDeviceId]);
  const video = useMemo(() => devices.videoEnabled ? { deviceId: devices.videoDeviceId || undefined } : false,
    [devices.videoEnabled, devices.videoDeviceId]);
  const options = useMemo(() => ({ adaptiveStream: true, dynacast: true,
    audioCaptureDefaults: { deviceId: devices.audioDeviceId || undefined },
    videoCaptureDefaults: { deviceId: devices.videoDeviceId || undefined } }), [devices.audioDeviceId, devices.videoDeviceId]);
  return (
    <section className="hiresense-media-room min-w-0 overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 text-white shadow-sm" data-lk-theme="default" aria-label="Interview meeting">
      {error ? <div role="alert" className="flex items-start justify-between gap-3 bg-amber-100 p-3 text-sm text-amber-900"><p>{error}</p><button type="button" onClick={() => setError(undefined)} className="shrink-0 font-semibold underline">Dismiss</button></div> : null}
      <LiveKitRoom className="hiresense-livekit-room" token={access.participant_token} serverUrl={access.server_url} connect
        audio={audio} video={video} screen={false} options={options}
        onConnected={onConnected} onError={showError}
        onMediaDeviceFailure={() => setError("A camera or microphone failed. Check permissions or choose another input when you rejoin.")}
        onDisconnected={(reason) => reason === DisconnectReason.ROOM_DELETED ? onEnded() : onLeave()}>
        <Controls role={access.role} onEnd={onEnd} onDeviceError={showError} onShareError={shareError} />
        <TranscriptReceiver />
      </LiveKitRoom>
    </section>
  );
}
