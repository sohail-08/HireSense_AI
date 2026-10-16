import React from "react";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { InterviewsPage } from "../../src/pages/InterviewsPage";

const api = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("../../src/api/apiClient", () => ({ apiRequest: api.request }));
vi.mock("../../src/components/assistant/SupervisorProvider", () => ({ useSupervisor: () => ({ refreshVersion: 0 }) }));
vi.mock("../../src/components/interviews/InterviewSchedulingPanel", () => ({
  InterviewSchedulingPanel: ({ scheduleIds }: { scheduleIds: number[] }) => <section aria-label="Rescheduling form">Interview {scheduleIds.join(",")}</section>,
}));

const base = { id: 1, candidate_name: "Upcoming candidate", job_title: "Frontend Engineer", stage: "technical",
  local_start: "2020-01-01T10:00:00+06:00", timezone: "Asia/Dhaka", duration_minutes: 30,
  status: "scheduled", room_status: "scheduled", sequence: 0, delivery_status: "sent", batch_id: 1,
  delivery_id: 1, delivery_attempts: 1, delivery_in_flight: false, delivery_retryable: false, job_posting_id: 1, history: [] };
function open() { return render(<MemoryRouter><InterviewsPage /></MemoryRouter>); }
function row(name: string) { return within(screen.getByText(name).closest("tr")!); }
beforeEach(() => { api.request.mockResolvedValue([base]); });

test("removes selection checkboxes and marks only persisted completed or ended interviews", async () => {
  api.request.mockResolvedValue([base,
    { ...base, id: 2, candidate_name: "Completed candidate", status: "completed" },
    { ...base, id: 3, candidate_name: "Ended candidate", room_status: "ended" },
    { ...base, id: 4, candidate_name: "Cancelled candidate", status: "cancelled", room_status: "cancelled" }]);
  open();
  await screen.findByText("Completed candidate");
  expect(screen.queryByRole("checkbox")).toBeNull();
  expect(screen.queryByRole("columnheader", { name: "Select" })).toBeNull();
  expect(row("Completed candidate").getByText("Interview completed")).toBeTruthy();
  expect(row("Ended candidate").getByText("Interview completed")).toBeTruthy();
  expect(row("Upcoming candidate").queryByText("Interview completed")).toBeNull();
  expect(row("Cancelled candidate").queryByText("Interview completed")).toBeNull();
  expect(row("Completed candidate").getByRole("link", { name: "View interview details" }).getAttribute("href")).toBe("/interviews/2/console");
  expect(row("Upcoming candidate").getByRole("link", { name: "Open interview console" })).toBeTruthy();
});

test("per-candidate rescheduling remains available only for unadmitted open interviews", async () => {
  api.request.mockResolvedValue([base,
    { ...base, id: 2, candidate_name: "Completed candidate", status: "completed", room_status: "ended" },
    { ...base, id: 3, candidate_name: "Active candidate", room_status: "active" }]);
  const user = userEvent.setup(); open();
  await user.click(await screen.findByRole("button", { name: "Reschedule Upcoming candidate" }));
  expect(screen.getByRole("region", { name: "Rescheduling form" }).textContent).toBe("Interview 1");
  expect(row("Completed candidate").queryByRole("button", { name: /Reschedule/ })).toBeNull();
  expect(row("Active candidate").queryByRole("button", { name: /Reschedule/ })).toBeNull();
  await user.click(screen.getByRole("button", { name: "Close rescheduling" }));
  expect(screen.queryByRole("region", { name: "Rescheduling form" })).toBeNull();
});

test("completion refreshes while the list is open and closes an obsolete rescheduling form", async () => {
  let poll: () => void = () => { throw new Error("Polling was not started"); };
  const interval = vi.spyOn(window, "setInterval").mockImplementation((callback) => {
    poll = callback as () => void;
    return 99999;
  });
  try {
    const user = userEvent.setup(); open();
    await user.click(await screen.findByRole("button", { name: "Reschedule Upcoming candidate" }));
    api.request.mockResolvedValue([{ ...base, status: "completed", room_status: "ended" }]);
    await act(async () => { poll(); });
    await waitFor(() => expect(row("Upcoming candidate").getByText("Interview completed")).toBeTruthy());
    expect(screen.queryByRole("region", { name: "Rescheduling form" })).toBeNull();
  } finally { interval.mockRestore(); }
});

test("delivery retry and schedule history remain available", async () => {
  api.request.mockResolvedValue([{ ...base, delivery_status: "failed", delivery_retryable: true,
    history: [{ local_start: "2020-01-01T09:00:00+06:00", timezone: "Asia/Dhaka", reason: "New time" }] }]);
  const user = userEvent.setup(); open();
  await user.click(await screen.findByRole("button", { name: "Retry failed notification" }));
  expect(api.request).toHaveBeenCalledWith("/interviews/deliveries/1/retry", {
    method: "POST", body: JSON.stringify({ confirmed: true, expected_attempts: 1 }),
  });
  expect(screen.getByText("Previous schedules (1)")).toBeTruthy();
});
