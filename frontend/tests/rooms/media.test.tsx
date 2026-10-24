import React from "react";
import { act, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { DisconnectReason, Track } from "livekit-client";
import { InterviewMediaRoom } from "../../src/components/interviews/InterviewMediaRoom";
import { getSdk } from "./setup";
const sdk = getSdk();
vi.mock("../../src/components/interviews/CandidateIdentity", () => ({ CandidateIdentity: () => null, CandidateCameraIdentity: () => null }));

const props = { access: { server_url: "wss://test-project.livekit.cloud", participant_token: "fake-media-only", expires_at: "2030-10-14T02:02:00Z", role: "candidate" as const }, devices: { username: "Candidate", audioEnabled: true, videoEnabled: false, audioDeviceId: "mic-1", videoDeviceId: "camera-1" }, onConnected: vi.fn(), onLeave: vi.fn(), onEnded: vi.fn() };
test("renders camera/microphone states, remote audio and a graceful mobile sharing fallback", () => {
  const view = render(<InterviewMediaRoom {...props} />);
  expect(screen.getByRole("button", { name: "Mute microphone" }).getAttribute("aria-pressed")).toBe("true");
  expect(screen.getByRole("button", { name: "Turn camera on" }).getAttribute("aria-pressed")).toBe("false");
  expect(screen.getByTestId("remote-audio")).toBeTruthy();
  expect(screen.queryByRole("button", { name: /screen shar|record|chat/i })).toBeNull();
  expect((screen.getByRole("button", { name: "Share screen", exact: true }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText(/This browser cannot share your screen/)).toBeTruthy();
  sdk.camera = true; sdk.microphone = false; view.rerender(<InterviewMediaRoom {...props} />);
  expect(screen.getByRole("button", { name: "Turn camera off" }).getAttribute("aria-pressed")).toBe("true");
  expect(screen.getByRole("button", { name: "Unmute microphone" }).getAttribute("aria-pressed")).toBe("false");
});
test("reconnection and device failure have safe visible messages", () => {
  sdk.connection = "reconnecting"; render(<InterviewMediaRoom {...props} />);
  expect(screen.getByRole("status").textContent).toContain("Reconnecting");
  act(() => { const error = new Error("private-token-diagnostic"); error.name = "NotAllowedError"; sdk.room.onError(error); });
  expect(screen.getByRole("alert").textContent).toContain("permission was denied");
  expect(screen.queryByText(/private-token-diagnostic/)).toBeNull();
});
test("room deletion ends the UI while manual leave is separate", async () => {
  const user = userEvent.setup(); render(<InterviewMediaRoom {...props} />);
  await user.click(screen.getByRole("button", { name: "Leave room" }));
  expect(props.onLeave).toHaveBeenCalledOnce(); expect(props.onEnded).not.toHaveBeenCalled();
  act(() => sdk.room.onDisconnected(DisconnectReason.ROOM_DELETED));
  expect(props.onEnded).toHaveBeenCalledOnce();
});

test("offers candidate screen sharing only through a user control, without starting capture on join", () => {
  const capture = vi.fn();
  Object.defineProperty(navigator.mediaDevices, "getDisplayMedia", { configurable: true, value: capture });
  const view = render(<InterviewMediaRoom {...props} />);
  expect((screen.getByRole("button", { name: "Share screen", exact: true }) as HTMLButtonElement).disabled).toBe(false);
  expect(sdk.room.screen).toBe(false);
  expect(capture).not.toHaveBeenCalled();
  expect(sdk.toggles[Track.Source.ScreenShare].captureOptions).toMatchObject({ audio: false, systemAudio: "exclude" });
  sdk.sharing = true;
  view.rerender(<InterviewMediaRoom {...props} />);
  expect(screen.getByRole("button", { name: "Stop sharing screen" }).getAttribute("aria-pressed")).toBe("true");
  sdk.sharing = false;
  view.rerender(<InterviewMediaRoom {...props} />);
  expect(screen.getByRole("button", { name: "Share screen", exact: true }).getAttribute("aria-pressed")).toBe("false");
});

test("shows the candidate's shared screen to the interviewer while preserving both camera frames", () => {
  const view = render(<InterviewMediaRoom {...props} access={{ ...props.access, role: "interviewer" }} />);
  const stage = screen.getByLabelText("Interview video area");
  expect(stage.getAttribute("data-sharing")).toBe("false");
  sdk.tracks = [
    { source: Track.Source.Camera, participant: { name: "Candidate" }, publication: { track: { dimensions: { width: 720, height: 1280 } } } },
    { source: Track.Source.ScreenShare, participant: { name: "Candidate" }, publication: { track: {} } },
  ];
  view.rerender(<InterviewMediaRoom {...props} access={{ ...props.access, role: "interviewer" }} />);
  expect(screen.getByLabelText("Interview video area")).toBe(stage);
  expect(stage.getAttribute("data-sharing")).toBe("true");
  expect(screen.getByLabelText("Candidate shared screen")).toBeTruthy();
  expect(screen.getByLabelText("Interviewer video tile")).toBeTruthy();
  expect(screen.getByLabelText("Candidate video tile")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Share screen", exact: true })).toBeNull();
  sdk.tracks = [];
  view.rerender(<InterviewMediaRoom {...props} access={{ ...props.access, role: "interviewer" }} />);
  expect(stage.getAttribute("data-sharing")).toBe("false");
  expect(screen.queryByLabelText("Candidate shared screen")).toBeNull();
});

test("screen-capture denial gives safe guidance without exposing SDK diagnostics", () => {
  Object.defineProperty(navigator.mediaDevices, "getDisplayMedia", { configurable: true, value: vi.fn() });
  render(<InterviewMediaRoom {...props} />);
  act(() => { const error = new Error("private-screen-capture-diagnostics"); error.name = "NotAllowedError"; sdk.toggles[Track.Source.ScreenShare].onDeviceError(error); });
  expect(screen.getByRole("alert").textContent).toContain("Screen sharing was cancelled or blocked");
  expect(screen.queryByText(/private-screen-capture-diagnostics/)).toBeNull();
  expect(screen.getByTestId("remote-audio")).toBeTruthy();
});

test("layout CSS bounds portrait videos and shared screens independently of their intrinsic sizes", () => {
  const css = readFileSync("src/index.css", "utf8");
  expect(css).toMatch(/\.hiresense-video-stage \{[^}]*height: var\(--meeting-stage-height/);
  expect(css).toMatch(/\.hiresense-media-room \.lk-participant-tile video \{[^}]*object-fit: contain/);
  expect(css).toContain("grid-template-columns: repeat(2, minmax(0, 1fr))");
  expect(css).toContain("@media (max-width: 639px)");
  expect(css).toContain("54svh");
});
