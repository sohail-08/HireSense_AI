import React from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { CandidateInterviewPage } from "../../src/pages/CandidateInterviewPage";
import { RoomApiError } from "../../src/components/interviews/roomApi";
import { accessMessage } from "../../src/components/interviews/roomState";
import { getSdk } from "./setup";
import { readFileSync } from "node:fs";
const sdk = getSdk();
vi.mock("../../src/components/interviews/CandidateIdentity", () => ({ CandidateIdentity: () => null, CandidateCameraIdentity: () => null }));

const api = vi.hoisted(() => ({ exchange: vi.fn(), candidateStatus: vi.fn(), waiting: vi.fn(), candidateMedia: vi.fn(), candidateConnected: vi.fn(), candidateLeave: vi.fn() }));
vi.mock("../../src/components/interviews/roomApi", async (original) => ({ ...await original<any>(), roomApi: api }));
vi.mock("../../src/components/interviews/workSampleApi", async (original) => ({ ...await original<any>(), workSampleApi: { candidateRead: vi.fn(async () => ({ exercise: null, server_now: "2030-10-14T02:00:00Z" })) } }));
const info = { job_title: "Frontend Engineer", scheduled_start: "2030-10-14T02:00:00Z", scheduled_end: "2030-10-14T02:30:00Z", timezone: "Asia/Dhaka", room_status: "scheduled", waiting: false, admitted: false, link_expires_at: "2030-11-13T02:00:00Z" };
function open() { return render(<MemoryRouter initialEntries={["/interview/join/" + "a".repeat(43)]}><Routes><Route path="/interview/join/:token" element={<CandidateInterviewPage />} /></Routes></MemoryRouter>); }
beforeEach(() => {
  api.exchange.mockResolvedValue(info); api.candidateStatus.mockResolvedValue(info);
  api.waiting.mockResolvedValue({ ...info, room_status: "waiting", waiting: true });
  api.candidateMedia.mockResolvedValue({ server_url: "wss://test-project.livekit.cloud", participant_token: "fake-media-only", expires_at: "2030-10-14T02:02:00Z", role: "candidate" });
  api.candidateConnected.mockResolvedValue({ ...info, admitted: true, room_status: "active" });
  api.candidateLeave.mockResolvedValue(info);
});

test.each(["invalid_link", "expired_link", "revoked_link", "cancelled", "ended", "invalid_session"])("renders safe candidate %s state", async (code) => {
  api.exchange.mockRejectedValue(new RoomApiError(code, 403));
  open();
  const expected = accessMessage(code);
  await screen.findByRole("heading", { name: expected.title });
  expect(sdk.prejoins).toBe(0); expect(api.candidateMedia).not.toHaveBeenCalled();
  expect(window.location.pathname).toBe("/interview/join");
});

test("devices and admission gate Cloud media", async () => {
  const user = userEvent.setup();
  open();
  await screen.findByRole("heading", { name: "Frontend Engineer interview" });
  expect(sdk.prejoins).toBe(0);
  await user.click(screen.getByRole("button", { name: "Check devices" }));
  expect(screen.getByLabelText("Camera device")).toBeTruthy();
  expect(screen.getByLabelText("Microphone device")).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "Deny device permission" }));
  expect(screen.getByRole("alert").textContent).toContain("permission was denied");
  expect(screen.queryByText("private-device-diagnostics")).toBeNull();
  await user.click(screen.getByRole("button", { name: "Continue to waiting room" }));
  await screen.findByRole("heading", { name: "Waiting for interviewer" });
  expect(sdk.room).toBeNull(); expect(api.candidateMedia).not.toHaveBeenCalled();
  api.candidateStatus.mockResolvedValue({ ...info, room_status: "ready", admitted: true });
  await waitFor(() => expect(api.candidateMedia).toHaveBeenCalledOnce(), { timeout: 3500 });
  expect(screen.getByTestId("media-room")).toBeTruthy();
  expect(screen.getByTestId("remote-audio")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "End interview for everyone" })).toBeNull();
  expect(screen.queryByRole("heading", { name: "Candidate information" })).toBeNull();
  expect(screen.queryByRole("region", { name: "Interview assistant" })).toBeNull();
  expect(screen.queryByLabelText("Ask the interview assistant")).toBeNull();
  expect(screen.queryByRole("tab", { name: "Candidate info" })).toBeNull();
  expect(screen.queryByRole("tab", { name: "Answer analysis" })).toBeNull();
  expect(screen.queryByText("Live transcript")).toBeNull();
  expect(screen.queryByLabelText("Transcript segments")).toBeNull();
  const call = screen.getByRole("region", { name: "Your interview room" });
  expect(call.contains(screen.getByTestId("media-room"))).toBe(true);
  expect(screen.getByRole("complementary", { name: "Your interview workspace" }).contains(screen.getByTestId("media-room"))).toBe(false);
  expect((screen.getByRole("button", { name: "Share screen", exact: true }) as HTMLButtonElement).disabled).toBe(true);
});

test("candidate layout fixes the left call to the viewport while only the workspace scrolls", () => {
  const css = readFileSync("src/index.css", "utf8");
  expect(css).toMatch(/\.hiresense-candidate-grid \{[^}]*grid-template-columns: minmax\(0, 1.7fr\) minmax\(20rem, 1fr\);[^}]*min-height: 0/);
  expect(css).toContain(".hiresense-candidate-grid > .hiresense-console-media-slot { overflow: hidden; }");
  expect(css).toMatch(/\.hiresense-candidate-workspace \{[^}]*overflow-y: auto/);
  const page = readFileSync("src/pages/CandidateInterviewPage.tsx", "utf8");
  expect(page).not.toContain("TranscriptionPanel");
  expect(page).not.toContain("TranscriptionProvider");
});

test("leaving the waiting room does not complete the interview", async () => {
  const user = userEvent.setup(); open();
  await user.click(await screen.findByRole("button", { name: "Check devices" }));
  await user.click(screen.getByRole("button", { name: "Continue to waiting room" }));
  await user.click(await screen.findByRole("button", { name: "Leave waiting room" }));
  await screen.findByRole("heading", { name: "You left the interview room" });
  expect(api.candidateLeave).toHaveBeenCalledOnce(); expect(api.candidateMedia).not.toHaveBeenCalled();
});

test("missing Cloud settings show admission without requesting unavailable media", async () => {
  const user = userEvent.setup();
  const demo = { ...info, media_notice: "Configure LIVEKIT_CLOUD_URL in the root .env." };
  api.exchange.mockResolvedValue(demo);
  api.waiting.mockResolvedValue({ ...demo, waiting: true, room_status: "waiting" });
  api.candidateStatus.mockResolvedValue({ ...demo, admitted: true, room_status: "ready" });
  open();
  await user.click(await screen.findByRole("button", { name: "Check devices" }));
  await user.click(screen.getByRole("button", { name: "Continue to waiting room" }));
  await screen.findByRole("heading", { name: "Admitted — audio/video unavailable" }, { timeout: 3500 });
  expect(screen.getByRole("alert").textContent).toContain("LIVEKIT_CLOUD_URL");
  expect(api.candidateMedia).not.toHaveBeenCalled();
  expect(sdk.room).toBeNull();
});

test("unsupported browsers get guidance without mounting media devices", async () => {
  const user = userEvent.setup(); open();
  await screen.findByRole("heading", { name: "Frontend Engineer interview" });
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: undefined });
  await user.click(screen.getByRole("button", { name: "Check devices" }));
  expect(screen.getByRole("alert").textContent).toContain("This browser cannot start an interview");
  expect(sdk.prejoins).toBe(0);
});

test("leaving during admission cannot connect a late media-token response", async () => {
  const user = userEvent.setup(); open();
  await user.click(await screen.findByRole("button", { name: "Check devices" }));
  await user.click(screen.getByRole("button", { name: "Continue to waiting room" }));
  let resolve: (value: any) => void = () => {};
  api.candidateMedia.mockImplementation(() => new Promise((done) => { resolve = done; }));
  api.candidateStatus.mockResolvedValue({ ...info, room_status: "ready", admitted: true });
  await waitFor(() => expect(api.candidateMedia).toHaveBeenCalledOnce(), { timeout: 3500 });
  await user.click(screen.getByRole("button", { name: "Leave waiting room" }));
  await act(async () => resolve({ server_url: "wss://test-project.livekit.cloud", participant_token: "fake-only", role: "candidate" }));
  await screen.findByRole("heading", { name: "You left the interview room" });
  expect(sdk.room).toBeNull();
});
