import React from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { CandidateIdentity } from "../../src/components/interviews/CandidateIdentity";
import { IdentityOverview } from "../../src/components/interviews/IdentityOverview";
const api = vi.hoisted(() => ({ candidate: vi.fn(), consent: vi.fn(), verify: vi.fn(), withdraw: vi.fn(), read: vi.fn(), manual: vi.fn() }));
vi.mock("../../src/components/interviews/identityApi", () => ({ identityApi: api }));
const state = { enabled: true, reference_available: true, reference_ready: false, status: "pending_consent", message: "Awaiting consent", version: 0,
  consented: false, capture_available: false, checked_at: null, notice_version: "hiresense-face-v1", notice: "Optional local matching. You may decline.", reference_expires_at: null };
beforeEach(() => { vi.clearAllMocks(); api.candidate.mockResolvedValue(state); api.read.mockResolvedValue(state); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

test("requires an unchecked explicit checkbox and does not sample on prejoin", async () => {
  const user = userEvent.setup();
  api.consent.mockResolvedValue({ ...state, reference_ready: true, consented: true, status: "not_checked", version: 1 });
  render(<CandidateIdentity />);
  const allow = await screen.findByRole("button", { name: "Allow photo verification" });
  expect((allow as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(false);
  expect(api.verify).not.toHaveBeenCalled();
  await user.click(screen.getByRole("checkbox")); await user.click(allow);
  expect(api.consent).toHaveBeenCalledWith(true, "hiresense-face-v1");
  await screen.findByText(/Matching starts after you join/);
  expect(api.verify).not.toHaveBeenCalled();
});

test("declining is a separate action that never starts matching", async () => {
  const user = userEvent.setup();
  api.consent.mockResolvedValue({ ...state, reference_available: false, status: "declined", message: "Face matching declined" });
  render(<CandidateIdentity />);
  await user.click(await screen.findByRole("button", { name: "Continue without face matching" }));
  expect(api.consent).toHaveBeenCalledWith(false, "hiresense-face-v1");
  await screen.findByText("Photo verification skipped. You can continue with your interview."); expect(api.verify).not.toHaveBeenCalled();
});

test("withdrawal confirms deletion and clears consent", async () => {
  api.candidate.mockResolvedValue({ ...state, consented: true, reference_ready: true, status: "matched", message: "Reference photo matched" });
  api.withdraw.mockResolvedValue({ ...state, reference_available: false, status: "withdrawn", message: "Consent withdrawn" });
  const user = userEvent.setup(); render(<CandidateIdentity />);
  await user.click(await screen.findByRole("button", { name: /Withdraw consent and delete/ }));
  expect(api.withdraw).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Confirm withdrawal" }));
  await screen.findByText("Consent withdrawn. Your HireSense face data has been deleted.");
  expect(screen.queryByText("Reference photo matched")).toBeNull(); expect(api.verify).not.toHaveBeenCalled();
});

test("missing photos offer manual verification without requesting a camera", async () => {
  api.candidate.mockResolvedValue({ ...state, reference_available: false, status: "unavailable", message: "No application photo" });
  render(<CandidateIdentity inRoom />);
  await screen.findByText("Photo verification is unavailable. You can continue with your interview."); expect(screen.queryByRole("checkbox")).toBeNull();
  expect(api.verify).not.toHaveBeenCalled(); expect(screen.getByText(/interviewer can verify you manually/)).toBeTruthy();
});

test("interviewer status distinguishes photo match from manual confirmation", async () => {
  api.read.mockResolvedValue({ ...state, reference_ready: true, status: "matched", message: "Reference photo matched", checked_at: "2026-10-24T04:00:00Z" });
  render(<IdentityOverview interviewId={44} />);
  await waitFor(() => expect(api.read).toHaveBeenCalledWith(44));
  expect(await screen.findByText(/Reference photo matched/)).toBeTruthy();
  expect(screen.getByText("Interviewer only")).toBeTruthy();
});

test.each(["matched", "low_similarity", "manual"])("candidate view never renders a %s outcome, even from an old API response", async status => {
  api.candidate.mockResolvedValue({ ...state, reference_ready: true, consented: true, status,
    message: "PRIVATE comparison result", similarity: 0.99, threshold: 0.5, manual_note: "PRIVATE reviewer note" });
  render(<CandidateIdentity inRoom />);
  expect(await screen.findByText("Verification submitted. Your interviewer will review it.")).toBeTruthy();
  expect(screen.queryByText(/PRIVATE/)).toBeNull();
  expect(screen.queryByText("Reference photo matched")).toBeNull();
  expect(screen.getByText(/Only your interviewer sees the photo-match result/)).toBeTruthy();
  expect(screen.getByRole("button", { name: /Withdraw consent and delete/ })).toBeTruthy();
  expect(api.verify).not.toHaveBeenCalled();
});

test("submitted samples do not auto-repeat and can be retaken without revealing a result", async () => {
  api.candidate.mockResolvedValue({ ...state, reference_ready: true, consented: true, status: "submitted", capture_available: true });
  render(<CandidateIdentity inRoom track={{ mediaStreamTrack: { readyState: "live" } } as any} />);
  expect(await screen.findByRole("button", { name: "Retake camera samples" })).toBeTruthy();
  expect(api.verify).not.toHaveBeenCalled();
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
  return { mediaStreamTrack: { readyState: "live" } } as any;
}

test("an already-published camera is sampled only after consent and room entry", async () => {
  const track = camera(); vi.useFakeTimers();
  const ready = { ...state, reference_ready: true, consented: true, capture_available: true, status: "not_checked", version: 2 };
  api.candidate.mockResolvedValue(ready); api.verify.mockResolvedValue({ ...ready, status: "matched", message: "Reference photo matched", version: 3 });
  const view = render(<CandidateIdentity track={track} />);
  await act(async () => { await Promise.resolve(); });
  expect(api.verify).not.toHaveBeenCalled();
  view.rerender(<CandidateIdentity inRoom track={track} />);
  await act(async () => { await vi.advanceTimersByTimeAsync(1600); });
  expect(api.verify).toHaveBeenCalledWith(["dGVzdA==", "dGVzdA==", "dGVzdA=="], 2);
  expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled();
});

test("leaving while sampling prevents a late image submission", async () => {
  const track = camera(); vi.useFakeTimers();
  api.candidate.mockResolvedValue({ ...state, reference_ready: true, consented: true, capture_available: true, status: "not_checked", version: 2 });
  const view = render(<CandidateIdentity inRoom track={track} />);
  await act(async () => { await Promise.resolve(); });
  view.unmount();
  await act(async () => { await vi.advanceTimersByTimeAsync(1600); });
  expect(api.verify).not.toHaveBeenCalled();
});
