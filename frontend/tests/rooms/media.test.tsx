import React from "react";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { DisconnectReason } from "livekit-client";
import { InterviewMediaRoom } from "../../src/components/interviews/InterviewMediaRoom";
import { getSdk } from "./setup";
const sdk = getSdk();

const props = { access: { server_url: "wss://test-project.livekit.cloud", participant_token: "fake-media-only", expires_at: "2030-10-14T02:02:00Z", role: "candidate" as const }, devices: { username: "Candidate", audioEnabled: true, videoEnabled: false, audioDeviceId: "mic-1", videoDeviceId: "camera-1" }, onConnected: vi.fn(), onLeave: vi.fn(), onEnded: vi.fn() };
test("renders camera/microphone states and remote audio with no unsupported controls", () => {
  const view = render(<InterviewMediaRoom {...props} />);
  expect(screen.getByRole("button", { name: "Mute microphone" }).getAttribute("aria-pressed")).toBe("true");
  expect(screen.getByRole("button", { name: "Turn camera on" }).getAttribute("aria-pressed")).toBe("false");
  expect(screen.getByTestId("remote-audio")).toBeTruthy();
  expect(screen.queryByRole("button", { name: /screen shar|record|chat/i })).toBeNull();
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
