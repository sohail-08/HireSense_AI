import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { ScheduleInterviewsPage } from "../../src/pages/ScheduleInterviewsPage";
import { apiRequest } from "../../src/api/apiClient";
import { selectOption } from "./selectHelpers";

vi.mock("../../src/api/apiClient", () => ({ apiRequest: vi.fn() }));
const supervisor = vi.hoisted(() => ({ refreshVersion: 0, setSelectedJobPostingId: vi.fn(), setSelectedApplicationIds: vi.fn() }));
vi.mock("../../src/components/assistant/SupervisorProvider", () => ({ useSupervisor: () => supervisor }));
vi.mock("../../src/components/interviews/InterviewSchedulingPanel", () => ({ InterviewSchedulingPanel: ({ jobId, rankingRunId, selectedIds, onBusyChange, onUpdated }: any) => <section aria-label="Invitation form">
  <p>Job {jobId} · Ranking {rankingRunId} · Selected {selectedIds.join(",")}</p><button onClick={() => onBusyChange(true)}>Begin invitation action</button><button onClick={onUpdated}>Invitation confirmed</button>
</section> }));

const candidates = Array.from({ length: 12 }, (_, index) => ({ id: index + 100, application_id: index + 1, rank: index + 1, display_score: String(100 - index), candidate_name: `Candidate ${index + 1}` }));
const jobs = [1, 2].map(id => ({ id, title: `Job ${id}`, application_count: 12, pending_count: 0 }));
const scheduled = { id: 40, application_id: 1, job_posting_id: 1, stage: "technical", status: "scheduled", room_status: "scheduled", start_utc: "2026-10-28T04:00:00+00:00", timezone: "Asia/Dhaka", delivery_status: "sent", delivery_in_flight: false };
function response(path: string): any {
  if (path === "/screening/jobs") return jobs;
  if (path.startsWith("/interviews/schedules?job_posting_id=")) return [];
  if (path === "/scoring/jobs/1/runs") return [{ id: 10, status: "completed" }, { id: 9, status: "completed" }];
  if (path === "/scoring/jobs/2/runs") return [{ id: 20, status: "completed" }];
  if (path === "/scoring/runs/10") return { id: 10, job_posting_id: 1, status: "completed", results: candidates };
  if (path === "/scoring/runs/20") return { id: 20, job_posting_id: 2, status: "completed", results: [{ ...candidates[0], application_id: 99, candidate_name: "Second job candidate" }] };
  throw new Error("Unexpected request: " + path);
}
function open() { return render(<MemoryRouter><ScheduleInterviewsPage /></MemoryRouter>); }

beforeEach(() => {
  vi.clearAllMocks(); supervisor.refreshVersion = 0;
  vi.mocked(apiRequest).mockImplementation(async path => response(path));
});

it("loads only the latest ranking and never sends invitations on entry", async () => {
  open();
  expect(await screen.findByText("Candidate 1")).toBeTruthy();
  expect(screen.getByRole("region", { name: "Invitation form" }).textContent).toContain("Job 1 · Ranking 10");
  expect(screen.queryByText("Scoring weights")).toBeNull();
  expect(apiRequest).not.toHaveBeenCalledWith("/scoring/runs/9");
  expect(vi.mocked(apiRequest).mock.calls.some(([, options]) => options?.method === "POST")).toBe(false);
});

it("keeps candidate selections across pages and passes them to scheduling and the chatbot", async () => {
  open();
  fireEvent.click(await screen.findByRole("checkbox", { name: "Select Candidate 1 for interview" }));
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Select Candidate 11 for interview" }));
  expect(screen.getByRole("region", { name: "Invitation form" }).textContent).toContain("Selected 1,11");
  expect(screen.getByText("11–12 of 12 candidates · 2 selected")).toBeTruthy();
  await waitFor(() => expect(supervisor.setSelectedApplicationIds).toHaveBeenLastCalledWith([1, 11]));
  selectOption("Candidates per page", "20");
  expect((screen.getByRole("checkbox", { name: "Select Candidate 1 for interview" }) as HTMLInputElement).checked).toBe(true);
});

it("clears selection and page when switching jobs and restores context on unmount", async () => {
  const view = open();
  fireEvent.click(await screen.findByRole("checkbox", { name: "Select Candidate 1 for interview" }));
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  fireEvent.click(screen.getByRole("combobox", { name: "Job posting" }));
  fireEvent.click(screen.getByRole("option", { name: /Job 2/ }));
  await screen.findByText("Second job candidate");
  expect(screen.queryByText("Candidate 11")).toBeNull();
  expect(screen.getByText("Page 1 of 1")).toBeTruthy();
  expect(screen.getByRole("region", { name: "Invitation form" }).textContent).toContain("Job 2 · Ranking 20 · Selected");
  expect(supervisor.setSelectedJobPostingId).toHaveBeenLastCalledWith(2);
  view.unmount();
  expect(supervisor.setSelectedJobPostingId).toHaveBeenLastCalledWith(undefined);
  expect(supervisor.setSelectedApplicationIds).toHaveBeenLastCalledWith([]);
});

it("shows CV Screening guidance when no current ranking exists", async () => {
  vi.mocked(apiRequest).mockImplementation(async path => path.endsWith("/runs") ? [] : response(path));
  open();
  expect(await screen.findByText(/No ranked candidates are available/)).toBeTruthy();
  expect(screen.getByRole("link", { name: "CV Screening" }).getAttribute("href")).toBe("/interviewer/assessments");
  expect(screen.queryByRole("region", { name: "Invitation form" })).toBeNull();
});

it("does not fall back to old rankings when the latest is incomplete", async () => {
  vi.mocked(apiRequest).mockImplementation(async path => path.endsWith("/runs") ? [{ id: 11, status: "failed" }, { id: 10, status: "completed" }] : response(path));
  open();
  await screen.findByText(/No ranked candidates are available/);
  expect(apiRequest).not.toHaveBeenCalledWith("/scoring/runs/10");
});

it("rejects late responses for a previously selected job", async () => {
  let finish!: (value: any) => void;
  vi.mocked(apiRequest).mockImplementation(async path => path === "/scoring/runs/10" ? new Promise(resolve => { finish = resolve; }) : response(path));
  open();
  const selector = await screen.findByRole("combobox", { name: "Job posting" });
  await waitFor(() => expect(apiRequest).toHaveBeenCalledWith("/scoring/runs/10"));
  fireEvent.click(selector); fireEvent.click(screen.getByRole("option", { name: /Job 2/ }));
  await screen.findByText("Second job candidate");
  await act(async () => finish(response("/scoring/runs/10")));
  expect(screen.queryByText("Candidate 1")).toBeNull();
  expect(screen.getByText("Second job candidate")).toBeTruthy();
});

it("locks job and candidate changes during an invitation action", async () => {
  open(); await screen.findByText("Candidate 1");
  fireEvent.click(screen.getByRole("button", { name: "Begin invitation action" }));
  expect((screen.getByRole("combobox", { name: "Job posting" }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole("checkbox", { name: "Select Candidate 1 for interview" }) as HTMLInputElement).disabled).toBe(true);
});

it("shows a retryable loading error without an invitation form", async () => {
  vi.mocked(apiRequest).mockRejectedValue(new Error("Could not load jobs"));
  open(); await screen.findByText("Could not load jobs");
  expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
  expect(screen.queryByRole("region", { name: "Invitation form" })).toBeNull();
});

it("shows persisted interview states and times, blocking duplicate invitations even after delivery failure", async () => {
  vi.mocked(apiRequest).mockImplementation(async path => path.startsWith("/interviews/schedules?") ? [
    { ...scheduled, delivery_status: "failed" },
    { ...scheduled, id: 41, application_id: 2, status: "completed", room_status: "ended" },
    { ...scheduled, id: 42, application_id: 3, status: "cancelled", room_status: "cancelled" },
    { ...scheduled, id: 43, application_id: 4, status: "rescheduled" },
    { ...scheduled, id: 44, application_id: 5, room_status: "active" },
  ] : response(path));
  open(); await screen.findByText("Candidate 1");
  const row = (name: string) => within(screen.getByText(name).closest("tr")!);
  expect(row("Candidate 1").getByText("Scheduled")).toBeTruthy();
  expect(row("Candidate 1").getByText("28 Oct 2026 at 10:00 AM (Dhaka time)")).toBeTruthy();
  expect(row("Candidate 1").getByText("Invitation delivery failed")).toBeTruthy();
  expect(row("Candidate 1").getByRole("link", { name: "View interview" }).getAttribute("href")).toBe("/interviews/40/console");
  expect((row("Candidate 1").getByRole("checkbox") as HTMLInputElement).disabled).toBe(true);
  expect(row("Candidate 2").getByText("Completed")).toBeTruthy();
  expect(row("Candidate 3").getByText("Cancelled · can schedule again")).toBeTruthy();
  expect((row("Candidate 3").getByRole("checkbox") as HTMLInputElement).disabled).toBe(false);
  expect(row("Candidate 4").getByText("Rescheduled")).toBeTruthy();
  expect(row("Candidate 5").getByText("In progress")).toBeTruthy();
  expect(row("Candidate 6").getByText("Not scheduled")).toBeTruthy();
  expect(screen.getByText("8 not scheduled · 3 scheduled · 1 completed")).toBeTruthy();
  selectOption("Interview status", "Not scheduled");
  expect(screen.queryByText("Candidate 1")).toBeNull();
  expect(screen.queryByText("Candidate 2")).toBeNull();
  expect(screen.getByText("Candidate 3")).toBeTruthy();
  expect(screen.getByText("1–8 of 8 candidates")).toBeTruthy();
  selectOption("Interview status", "Completed");
  expect(screen.getByText("Candidate 2")).toBeTruthy();
  expect(screen.queryByText("Candidate 3")).toBeNull();
});

it("prefers an active booking over cancelled history and never guesses completion from an old time", async () => {
  vi.mocked(apiRequest).mockImplementation(async path => path.startsWith("/interviews/schedules?") ? [
    { ...scheduled, start_utc: "2020-01-01T04:00:00Z" },
    { ...scheduled, id: 100, status: "cancelled", room_status: "cancelled" },
    { ...scheduled, id: 101, application_id: 2, job_posting_id: 2 },
    { ...scheduled, id: 102, application_id: 3, stage: "hr" },
  ] : response(path));
  open(); await screen.findByText("Candidate 1");
  expect(within(screen.getByText("Candidate 1").closest("tr")!).getByText("Scheduled")).toBeTruthy();
  expect(screen.getByText("11 not scheduled · 1 scheduled · 0 completed")).toBeTruthy();
});

it("does not label unknown statuses as not scheduled or allow selection when their request fails", async () => {
  vi.mocked(apiRequest).mockImplementation(async path => {
    if (path.startsWith("/interviews/schedules?")) throw new Error("Could not load interview statuses.");
    return response(path);
  });
  open(); await screen.findByText("Candidate 1");
  await screen.findByText("Could not load interview statuses.");
  expect(screen.queryByText(/not scheduled ·/)).toBeNull();
  expect((screen.getByRole("checkbox", { name: "Select Candidate 1 for interview" }) as HTMLInputElement).disabled).toBe(true);
  expect(screen.queryByRole("region", { name: "Invitation form" })).toBeNull();
  expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
});

it("refreshes statuses and clears newly scheduled selections after invitation confirmation", async () => {
  let confirmed = false;
  vi.mocked(apiRequest).mockImplementation(async path => path.startsWith("/interviews/schedules?") ? confirmed ? [scheduled] : [] : response(path));
  open(); fireEvent.click(await screen.findByRole("checkbox", { name: "Select Candidate 1 for interview" }));
  expect(screen.getByRole("region", { name: "Invitation form" }).textContent).toContain("Selected 1");
  confirmed = true;
  fireEvent.click(screen.getByRole("button", { name: "Invitation confirmed" }));
  await screen.findByText("Scheduled");
  const checkbox = screen.getByRole("checkbox", { name: "Select Candidate 1 for interview" }) as HTMLInputElement;
  expect(checkbox.disabled).toBe(true); expect(checkbox.checked).toBe(false);
  await waitFor(() => expect(supervisor.setSelectedApplicationIds).toHaveBeenLastCalledWith([]));
  expect(screen.getByRole("region", { name: "Invitation form" })).toBeTruthy();
});

it("ignores late interview statuses from a previously selected job", async () => {
  let finish!: (value: any) => void;
  vi.mocked(apiRequest).mockImplementation(async path => path === "/interviews/schedules?job_posting_id=1" ? new Promise(resolve => { finish = resolve; }) : response(path));
  open(); await screen.findByText("Candidate 1");
  expect((screen.getByRole("checkbox", { name: "Select Candidate 1 for interview" }) as HTMLInputElement).disabled).toBe(true);
  selectOption("Job posting", /Job 2/);
  await screen.findByText("Second job candidate");
  await act(async () => finish([{ ...scheduled, application_id: 99 }]));
  expect(screen.getByText("1 not scheduled · 0 scheduled · 0 completed")).toBeTruthy();
  expect((screen.getByRole("checkbox", { name: "Select Second job candidate for interview" }) as HTMLInputElement).disabled).toBe(false);
});
