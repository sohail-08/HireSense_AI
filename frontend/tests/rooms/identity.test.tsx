import React from "react";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { CandidateIdentity, CandidateCameraIdentity } from "../../src/components/interviews/CandidateIdentity";
import { IdentityOverview } from "../../src/components/interviews/IdentityOverview";
import { getSdk } from "./setup";
const api = vi.hoisted(() => ({ candidate: vi.fn(), consent: vi.fn(), verify: vi.fn(), withdraw: vi.fn(), read: vi.fn(), manual: vi.fn(), capture: vi.fn() }));
const transcription = vi.hoisted(() => ({ status: vi.fn(), consent: vi.fn() }));
vi.mock("../../src/components/interviews/identityApi", () => ({ identityApi: api }));
vi.mock("../../src/components/interviews/transcriptionApi", () => ({ transcriptionApi: transcription }));
const state = { enabled: true, reference_available: true, reference_ready: false, status: "pending_consent", message: "Awaiting consent", version: 1,
  consented: false, capture_available: false, checked_at: null, notice_version: "hiresense-face-v1", notice: "Optional local matching. You may decline.", reference_expires_at: null };
const text = { enabled: true, consented: false, notice: "Audio is transcribed for your interviewer, not recorded.", retention_days: 30 };
beforeEach(() => {
  vi.resetAllMocks(); api.candidate.mockResolvedValue(state); api.read.mockResolvedValue(state);
  transcription.status.mockResolvedValue(text);
  api.consent.mockResolvedValue({ ...state, consented: true, reference_ready: true });
  transcription.consent.mockResolvedValue({ ...text, consented: true });
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

test("one unchecked checkbox explicitly saves both permissions without starting capture", async () => {
  const user = userEvent.setup(); render(<CandidateIdentity />);
  const checkbox = await screen.findByRole("checkbox", { name: "I agree to live interview transcription and photo verification." });
  expect((checkbox as HTMLInputElement).checked).toBe(false);
  expect(api.consent).not.toHaveBeenCalled(); expect(transcription.consent).not.toHaveBeenCalled();
  expect(screen.queryByRole("button")).toBeNull();
  expect(screen.getByText("Privacy details").closest("details")?.open).toBe(false);
  await user.click(checkbox);
  await screen.findByText("Consent saved. Your interviewer handles verification.");
  expect(api.consent).toHaveBeenCalledWith(true, "hiresense-face-v1");
  expect(transcription.consent).toHaveBeenCalledWith(true);
  expect(api.verify).not.toHaveBeenCalled();
});

test("missing photos allow transcription consent without blocking the interview", async () => {
  api.candidate.mockResolvedValue({ ...state, reference_available: false, status: "unavailable" });
  const user = userEvent.setup(); render(<CandidateIdentity />);
  await user.click(await screen.findByRole("checkbox", { name: "I agree to live interview transcription." }));
  expect(api.consent).not.toHaveBeenCalled(); expect(transcription.consent).toHaveBeenCalledWith(true);
  expect(api.verify).not.toHaveBeenCalled();
});

test("unchecking consent stops both features without separate withdrawal or decline buttons", async () => {
  api.candidate.mockResolvedValue({ ...state, consented: true, reference_ready: true });
  transcription.status.mockResolvedValue({ ...text, consented: true });
  api.withdraw.mockResolvedValue({ ...state, reference_available: false, status: "withdrawn" });
  transcription.consent.mockResolvedValue(text);
  const user = userEvent.setup(); render(<CandidateIdentity />);
  const checkbox = await screen.findByRole("checkbox");
  expect((checkbox as HTMLInputElement).checked).toBe(true);
  await user.click(checkbox);
  expect(api.withdraw).toHaveBeenCalledOnce(); expect(transcription.consent).toHaveBeenCalledWith(false);
  expect(screen.queryByRole("button", { name: /withdraw|continue without|capture|retake/i })).toBeNull();
  expect(api.verify).not.toHaveBeenCalled();
});

test("partial permission failures are visible and do not report complete consent", async () => {
  api.consent.mockRejectedValue(new Error("private provider details"));
  const user = userEvent.setup(); render(<CandidateIdentity />);
  await user.click(await screen.findByRole("checkbox"));
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Not all permissions were saved. Review the checkbox and try again.");
  expect((screen.getByRole("checkbox") as HTMLInputElement).indeterminate).toBe(true);
  expect(screen.getByText("Some permissions are saved. Uncheck to stop these features.")).toBeTruthy();
  expect(screen.queryByText(/private provider/)).toBeNull();
});

test.each(["matched", "low_similarity", "manual"])("candidate never sees a %s outcome or capture controls", async status => {
  api.candidate.mockResolvedValue({ ...state, consented: true, reference_ready: true, status, message: "PRIVATE result", similarity: .99, manual_note: "PRIVATE note" });
  transcription.status.mockResolvedValue({ ...text, consented: true });
  render(<CandidateIdentity />);
  await screen.findByText("Consent saved. Your interviewer handles verification.");
  expect(screen.queryByText(/PRIVATE/)).toBeNull(); expect(screen.queryByRole("button")).toBeNull();
});

test("interviewer requests capture and cannot repeat it while pending", async () => {
  const ready = { ...state, reference_ready: true, consented: true, capture_allowed: true, version: 4 };
  api.read.mockResolvedValue(ready);
  api.capture.mockResolvedValue({ ...ready, capture_pending: true, version: 5, status: "capture_requested", message: "Camera samples requested." });
  const user = userEvent.setup(); render(<IdentityOverview interviewId={44} />);
  await user.click(await screen.findByRole("button", { name: "Capture face" }));
  expect(api.capture).toHaveBeenCalledWith(44, 4);
  expect((await screen.findByRole("button", { name: "Waiting for camera…" }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText("Interviewer only")).toBeTruthy();
});

test("capture remains disabled before a consented candidate joins", async () => {
  render(<IdentityOverview interviewId={44} />);
  expect((await screen.findByRole("button", { name: "Capture face" }) as HTMLButtonElement).disabled).toBe(true);
  expect(api.capture).not.toHaveBeenCalled();
});

test("matched card shows a clear photo-only result, readable check time and compact recapture action", async () => {
  api.read.mockResolvedValue({ ...state, status: "matched", message: "Reference photo matched", checked_at: "2026-10-26T08:51:10Z",
    capture_allowed: true, similarity: .97, threshold: .5 });
  render(<IdentityOverview interviewId={44} />);
  await screen.findByText("Reference photo matched");
  expect(screen.getByRole("region", { name: "Candidate identity status" }).getAttribute("data-state")).toBe("matched");
  expect(screen.getByText("Checked 26 Oct 2026 at 2:51 PM (Dhaka time)")).toBeTruthy();
  expect(screen.getByText("Compared with application photo")).toBeTruthy();
  expect(screen.getByText("No effect on assessment scores")).toBeTruthy();
  expect(screen.getByText("Not legal-ID verification or continuous monitoring.")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Capture face again" }).querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
  expect(screen.queryByRole("button", { name: "Confirm identity manually" })).toBeNull();
  expect(api.capture).not.toHaveBeenCalled();
});

test("manual confirmation stays visually and textually separate from a biometric match", async () => {
  api.read.mockResolvedValue({ ...state, status: "manual", message: "Manually confirmed by interviewer", checked_at: "2026-10-26T08:51:10Z" });
  render(<IdentityOverview interviewId={44} />);
  await screen.findByText("Manually confirmed by interviewer");
  expect(screen.getByRole("region", { name: "Candidate identity status" }).getAttribute("data-state")).toBe("manual");
  expect(screen.getByText("Human confirmation · not a photo match")).toBeTruthy();
  expect(screen.queryByText("Reference photo matched")).toBeNull();
});

test("an inconclusive result keeps retry and explicit manual confirmation available", async () => {
  const user = userEvent.setup();
  api.read.mockResolvedValue({ ...state, status: "low_similarity", message: "Unable to verify a match. Retry or ask for manual verification.",
    checked_at: "2026-10-26T08:51:10Z", capture_allowed: true });
  api.manual.mockResolvedValue({ ...state, status: "manual", message: "Manually confirmed by interviewer", checked_at: "2026-10-26T08:55:00Z" });
  render(<IdentityOverview interviewId={44} />);
  await screen.findByText(/Unable to verify a match/);
  expect(screen.getByRole("region", { name: "Candidate identity status" }).getAttribute("data-state")).toBe("low_similarity");
  expect((screen.getByRole("button", { name: "Capture face again" }) as HTMLButtonElement).disabled).toBe(false);
  const toggle = screen.getByRole("button", { name: "Confirm identity manually" });
  expect(toggle.getAttribute("aria-expanded")).toBe("false");
  await user.click(toggle);
  expect(toggle.getAttribute("aria-expanded")).toBe("true");
  const save = screen.getByRole("button", { name: "Save manual confirmation" });
  expect((save as HTMLButtonElement).disabled).toBe(true);
  await user.type(screen.getByRole("textbox", { name: "How did you confirm the joining candidate?" }), "Confirmed during the live interview.");
  await user.click(save);
  expect(api.manual).toHaveBeenCalledWith(44, "Confirmed during the live interview.");
  await screen.findByText("Human confirmation · not a photo match");
});

test("unavailable status never displays a successful-match presentation", async () => {
  api.read.mockRejectedValue(new Error("private service details"));
  render(<IdentityOverview interviewId={44} />);
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Identity check unavailable. Do not assume a match.");
  expect(screen.getByRole("region", { name: "Candidate identity status" }).getAttribute("data-state")).toBe("unavailable");
  expect(screen.queryByText("Reference photo matched")).toBeNull();
  expect(screen.queryByText(/private service details/)).toBeNull();
});

function camera() {
  vi.stubGlobal("MediaStream", class { constructor(public tracks: unknown[]) {} });
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(async function (this: HTMLVideoElement) {
    Object.defineProperty(this, "videoWidth", { value: 640, configurable: true });
    Object.defineProperty(this, "videoHeight", { value: 480, configurable: true });
  });
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ drawImage: vi.fn() } as any);
  vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockReturnValue("data:image/jpeg;base64,dGVzdA==");
  getSdk().camera = true;
  getSdk().cameraTrack = { track: { mediaStreamTrack: { readyState: "live" } } };
}

test("a headless collector waits for the interviewer and samples once per requested version", async () => {
  camera(); vi.useFakeTimers();
  const ready = { ...state, reference_ready: true, consented: true, status: "not_checked", version: 2 };
  api.candidate.mockResolvedValue(ready); api.verify.mockResolvedValue({ ...ready, status: "submitted", version: 4 });
  const view = render(<CandidateCameraIdentity />);
  await act(async () => { await vi.advanceTimersByTimeAsync(1600); });
  expect(api.verify).not.toHaveBeenCalled();
  api.candidate.mockResolvedValue({ ...ready, capture_available: true, version: 3 });
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(api.verify).toHaveBeenCalledExactlyOnceWith(["dGVzdA==", "dGVzdA==", "dGVzdA=="], 3);
  expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled();
  expect(view.container.textContent).toBe("");
});

test.each(["unmount", "consent revoked", "camera off"])("%s cancels a pending capture", async action => {
  camera(); vi.useFakeTimers();
  api.candidate.mockResolvedValue({ ...state, reference_ready: true, consented: true, capture_available: true, version: 2 });
  const view = render(<CandidateCameraIdentity />);
  await act(async () => { await Promise.resolve(); });
  if (action === "unmount") view.unmount();
  else if (action === "consent revoked") window.dispatchEvent(new Event("hiresense:candidate-consent-changed"));
  else { getSdk().camera = false; view.rerender(<CandidateCameraIdentity />); }
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(api.verify).not.toHaveBeenCalled();
});

test("an unexpected capture flag cannot bypass absent consent", async () => {
  camera(); vi.useFakeTimers();
  api.candidate.mockResolvedValue({ ...state, reference_ready: true, capture_available: true });
  render(<CandidateCameraIdentity />);
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(api.verify).not.toHaveBeenCalled();
});
