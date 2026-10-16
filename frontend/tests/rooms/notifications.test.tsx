import React from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ApplicationNotifications } from "../../src/components/common/ApplicationNotifications";
import { APPLICATIONS_CHANGED_EVENT } from "../../src/components/common/applicationNotificationEvents";
import { Navbar } from "../../src/components/common/Navbar";
const api = vi.hoisted(() => vi.fn());
const auth = vi.hoisted(() => ({ role: "interviewer" }));
vi.mock("../../src/api/apiClient", () => ({ apiRequest: api }));
vi.mock("../../src/auth/AuthProvider", () => ({ useAuth: () => ({ user: { name: "Test user", role: auth.role }, logout: vi.fn() }) }));
const summary = { status: "ready", pending_count: 3, unmatched_count: 1,
  jobs: [{ job_posting_id: 1, job_title: "Frontend Engineer", count: 3 }], checked_at: "2026-10-14T04:00:00Z", message: null };
function open() { return render(<MemoryRouter><ApplicationNotifications /></MemoryRouter>); }
beforeEach(() => { api.mockReset(); api.mockResolvedValue(summary); auth.role = "interviewer"; });

test("shows unsynced counts and job routing issues without automatically syncing", async () => {
  const user = userEvent.setup(); open();
  await user.click(await screen.findByRole("button", { name: "Application notifications: 4 responses waiting" }));
  expect(screen.getByText("3 new applications are ready to sync.")).toBeTruthy();
  expect(screen.getByText("Frontend Engineer")).toBeTruthy();
  expect(screen.getByText(/1 response needs a valid/)).toBeTruthy();
  expect(screen.getByRole("link", { name: "Review and sync" }).getAttribute("href")).toBe("/interviewer/candidates");
  expect(api.mock.calls.every(([path]) => path === "/candidates/notifications")).toBe(true);
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("region", { name: "Application notifications" })).toBeNull();
});

test("refreshes the badge after sync events and clears it only when no responses remain", async () => {
  api.mockResolvedValueOnce(summary).mockResolvedValueOnce({ ...summary, pending_count: 0, unmatched_count: 0, jobs: [] });
  const user = userEvent.setup(); open();
  await screen.findByRole("button", { name: "Application notifications: 4 responses waiting" });
  act(() => { window.dispatchEvent(new Event(APPLICATIONS_CHANGED_EVENT)); });
  await user.click(await screen.findByRole("button", { name: "Application notifications: 0 responses waiting" }));
  expect(screen.getByText("No new applications waiting to sync.")).toBeTruthy();
});

test("reports unavailable checks instead of showing a misleading empty inbox", async () => {
  api.mockRejectedValueOnce(new Error("network"));
  const user = userEvent.setup(); open();
  await waitFor(() => expect(api).toHaveBeenCalledOnce());
  await user.click(screen.getByRole("button", { name: "Application notifications" }));
  expect(await screen.findByText(/Could not check new applications/)).toBeTruthy();
  expect(screen.queryByText("No new applications waiting to sync.")).toBeNull();
});

test("polls once a minute, pauses in hidden tabs and checks on returning", async () => {
  let poll: () => void = () => {};
  const originalInterval = window.setInterval.bind(window);
  const interval = vi.spyOn(window, "setInterval").mockImplementation((handler, timeout) => {
    if (timeout === 60000) { poll = handler as () => void; return 98765; }
    return originalInterval(handler, timeout);
  });
  const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
  try {
    open(); expect(api).not.toHaveBeenCalled();
    visibility.mockReturnValue("visible");
    act(() => { document.dispatchEvent(new Event("visibilitychange")); });
    await waitFor(() => expect(api).toHaveBeenCalledOnce());
    act(() => poll());
    await waitFor(() => expect(api).toHaveBeenCalledTimes(2));
    visibility.mockReturnValue("hidden"); act(() => poll());
    expect(api).toHaveBeenCalledTimes(2);
  } finally { interval.mockRestore(); visibility.mockRestore(); }
});

test("candidate navigation never mounts or requests application notifications", () => {
  auth.role = "candidate";
  render(<MemoryRouter><Navbar /></MemoryRouter>);
  expect(screen.queryByRole("button", { name: /Application notifications/ })).toBeNull();
  expect(api).not.toHaveBeenCalled();
});
