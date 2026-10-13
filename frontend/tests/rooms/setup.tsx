import React from "react";
import { afterEach, beforeEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

vi.mock("livekit-client", async (original) => ({ ...await original<any>(), isBrowserSupported: () => true }));

const sdk = vi.hoisted(() => ({
  prejoins: 0, room: null as any, connection: "connected", microphone: true, camera: false,
  tracks: [] as any[],
}));

export function getSdk() { return sdk; }

vi.mock("@livekit/components-react", async () => {
  const React = await import("react");
  return {
    PreJoin: (props: any) => {
      sdk.prejoins += 1;
      return <div data-testid="prejoin">
        <label>Camera device<select defaultValue="camera-1"><option value="camera-1">Camera 1</option><option value="camera-2">Camera 2</option></select></label>
        <label>Microphone device<select defaultValue="mic-1"><option value="mic-1">Microphone 1</option></select></label>
        <span>Microphone level test</span>
        <button onClick={() => { const error = new Error("private-device-diagnostics"); error.name = "NotAllowedError"; props.onError(error); }}>Deny device permission</button>
        <button onClick={() => props.onSubmit({ username: "Candidate", audioEnabled: true, videoEnabled: false, audioDeviceId: "mic-1", videoDeviceId: "camera-1" })}>{props.joinLabel}</button>
      </div>;
    },
    LiveKitRoom: (props: any) => {
      sdk.room = props;
      React.useEffect(() => { props.onConnected?.(); return () => { sdk.room = null; }; }, []);
      return <div data-testid="media-room">{props.children}</div>;
    },
    ParticipantTile: ({ trackRef }: any) => <div>{trackRef.participant.name} video</div>,
    RoomAudioRenderer: () => <div data-testid="remote-audio" />,
    StartAudio: () => <button>Enable interview audio</button>,
    TrackToggle: ({ source, onDeviceError, ...props }: any) => <button {...props} data-source={source} />,
    DisconnectButton: ({ children }: any) => <button onClick={() => sdk.room?.onDisconnected() }>{children}</button>,
    useConnectionState: () => sdk.connection,
    useTracks: () => sdk.tracks,
    useLocalParticipant: () => ({ isMicrophoneEnabled: sdk.microphone, isCameraEnabled: sdk.camera }),
  };
});

beforeEach(() => {
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn() } });
  sdk.prejoins = 0; sdk.room = null; sdk.connection = "connected"; sdk.microphone = true; sdk.camera = false; sdk.tracks = [];
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.clearAllMocks(); });
