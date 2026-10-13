import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { InterviewerConsolePage } from "../../src/pages/InterviewerConsolePage";
import { ApiError } from "../../src/api/apiClient";

const api = vi.hoisted(() => ({ status: vi.fn(), admit: vi.fn(), end: vi.fn(), interviewerMedia: vi.fn(), interviewerConnected: vi.fn(), interviewerLeave: vi.fn(), link: vi.fn(), revoke: vi.fn() }));
vi.mock("../../src/components/interviews/roomApi", async (original) => ({ ...await original<any>(), roomApi: api }));
const info = { interview_id: 1, candidate_name: "Test Candidate", job_title: "Frontend Engineer", scheduled_start: "2030-10-14T02:00:00Z", scheduled_end: "2030-10-14T02:30:00Z", timezone: "Asia/Dhaka", room_status: "waiting", waiting: true, admitted: false, has_join_link: true, link_revoked: false, room_version: 1 };
function open() { render(<MemoryRouter initialEntries={["/interviews/1/console"]}><Routes><Route path="/interviews/:interviewId/console" element={<InterviewerConsolePage />} /></Routes></MemoryRouter>); }
beforeEach(() => {
  api.status.mockResolvedValue(info); api.admit.mockResolvedValue({ ...info, admitted: true, waiting: false, room_status: "ready" });
  api.end.mockResolvedValue({ ...info, admitted: true, waiting: false, room_status: "ended" });
});
test("console authorization failure does not expose candidate or room controls", async () => {
  api.status.mockRejectedValue(new ApiError("Forbidden", 403)); open();
  expect((await screen.findByRole("alert")).textContent).toContain("not authorized");
  expect(screen.queryByText("Test Candidate")).toBeNull(); expect(screen.queryByRole("button", { name: "Admit candidate" })).toBeNull();
});
test("shows a waiting candidate and admits them without joining media automatically", async () => {
  const user = userEvent.setup(); open();
  await user.click(await screen.findByRole("button", { name: "Admit candidate" }));
  await screen.findByText("Candidate admitted");
  expect(api.admit).toHaveBeenCalledWith(1); expect(api.interviewerMedia).not.toHaveBeenCalled();
});

test("device submission is visible and reveals the interviewer join button", async () => {
  const user = userEvent.setup(); open();
  await user.click(await screen.findByRole("button", { name: "Check devices" }));
  const ready = screen.getByRole("button", { name: "Devices ready" });
  for (let node: HTMLElement | null = ready; node; node = node.parentElement) {
    expect(getComputedStyle(node).display).not.toBe("none");
  }
  expect(getComputedStyle(document.querySelector('input[name="username"]')!).display).toBe("none");
  expect(screen.queryByRole("button", { name: "Join interview room" })).toBeNull();
  await user.click(ready);
  expect(await screen.findByRole("button", { name: "Join interview room" })).toBeTruthy();
  expect(api.interviewerMedia).not.toHaveBeenCalled();
});

test("website-only demo explains unavailable media and disables remote joining", async () => {
  api.status.mockResolvedValue({ ...info, media_notice: "Website-only demo: LiveKit is still on localhost." });
  const user = userEvent.setup(); open();
  await screen.findByText(/Website-only demo/);
  await user.click(screen.getByRole("button", { name: "Check devices" }));
  await user.click(screen.getByRole("button", { name: "Devices ready" }));
  expect(screen.getByRole("button", { name: "Join interview room" }).hasAttribute("disabled")).toBe(true);
  expect(api.interviewerMedia).not.toHaveBeenCalled();
});

test("updating an old-origin link requires explicit confirmation", async () => {
  api.status.mockResolvedValue({ ...info, link_origin_outdated: true });
  api.link.mockResolvedValue({ join_url: "https://demo.trycloudflare.com/interview/join/fake-test-only" });
  const user = userEvent.setup(); open();
  await user.click(await screen.findByRole("button", { name: "Update candidate link" }));
  expect(screen.getByRole("dialog")).toBeTruthy(); expect(api.link).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Confirm" }));
  expect(api.link).toHaveBeenCalledWith(1, "/rotate");
});
test("ending requires a confirmation dialog and renders ended state", async () => {
  const user = userEvent.setup(); open();
  await user.click(await screen.findByRole("button", { name: "End interview for everyone" }));
  expect(screen.getByRole("dialog")).toBeTruthy(); expect(api.end).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Keep interview open" }));
  expect(api.end).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "End interview for everyone" }));
  await user.click(screen.getByRole("button", { name: "Confirm end interview" }));
  await screen.findByRole("heading", { name: "Interview ended" });
  expect(api.end).toHaveBeenCalledWith(1); expect(screen.queryByRole("button", { name: "Admit candidate" })).toBeNull();
});
