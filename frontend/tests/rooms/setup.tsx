import React from "react";
import { afterEach, beforeEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import { readFileSync } from "node:fs";

// Apply the real HireSense PreJoin overrides to the SDK-shaped mock. Previously
// a flat mock missed that hiding the username form also hides its submit button.
const deviceStyles = document.createElement("style");
deviceStyles.textContent = readFileSync("src/index.css", "utf8")
  .match(/^\.hiresense-device-check[^\{]*\{[^}]*\}/gm)?.join("\n") || "";
document.head.appendChild(deviceStyles);

vi.mock("livekit-client", async (original) => ({ ...await original<any>(), isBrowserSupported: () => true }));

const sdk = vi.hoisted(() => ({
  prejoins: 0, room: null as any, connection: "connected", microphone: true, camera: false, sharing: false,
  tracks: [] as any[], toggles: {} as Record<string, any>, cameraTrack: undefined as any,
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
        <form className="lk-username-container" onSubmit={(event) => {
          event.preventDefault();
          props.onSubmit({ username: props.defaults.username, audioEnabled: true, videoEnabled: false, audioDeviceId: "mic-1", videoDeviceId: "camera-1" });
        }}>
          <input className="lk-form-control" name="username" aria-label="Display name" defaultValue={props.defaults.username} />
          <button className="lk-button lk-join-button" type="submit">{props.joinLabel}</button>
        </form>
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
    TrackToggle: ({ source, onDeviceError, captureOptions, showIcon, ...props }: any) => { sdk.toggles[source] = { onDeviceError, captureOptions }; return <button {...props} data-source={source} />; },
    DisconnectButton: ({ children, ...props }: any) => <button {...props} onClick={() => sdk.room?.onDisconnected() }>{children}</button>,
    useConnectionState: () => sdk.connection,
    useTracks: () => sdk.tracks,
    useLocalParticipant: () => ({ isMicrophoneEnabled: sdk.microphone, isCameraEnabled: sdk.camera, isScreenShareEnabled: sdk.sharing, cameraTrack: sdk.cameraTrack }),
    useRoomContext: () => ({ registerTextStreamHandler: vi.fn(), unregisterTextStreamHandler: vi.fn(), on: vi.fn(), off: vi.fn() }),
  };
});

beforeEach(() => {
  // Keep the app override after SDK styles in JSDOM's simplified CSS cascade.
  document.head.appendChild(deviceStyles);
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn() } });
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value() { this.setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value() { this.removeAttribute("open"); } });
  sdk.prejoins = 0; sdk.room = null; sdk.connection = "connected"; sdk.microphone = true; sdk.camera = false; sdk.sharing = false; sdk.tracks = []; sdk.toggles = {}; sdk.cameraTrack = undefined;
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.clearAllMocks(); });
