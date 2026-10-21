import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { ScheduleInterviewsPage } from "../../src/pages/ScheduleInterviewsPage";
import { apiRequest } from "../../src/api/apiClient";
import { selectOption } from "./selectHelpers";

vi.mock("../../src/api/apiClient", () => ({ apiRequest: vi.fn() }));
const supervisor = vi.hoisted(() => ({ refreshVersion: 0, setSelectedJobPostingId: vi.fn(), setSelectedApplicationIds: vi.fn() }));
vi.mock("../../src/components/assistant/SupervisorProvider", () => ({ useSupervisor: () => supervisor }));
vi.mock("../../src/components/interviews/InterviewSchedulingPanel", () => ({ InterviewSchedulingPanel: ({ jobId, rankingRunId, selectedIds, onBusyChange }: any) => <section aria-label="Invitation form">
  <p>Job {jobId} · Ranking {rankingRunId} · Selected {selectedIds.join(",")}</p><button onClick={() => onBusyChange(true)}>Begin invitation action</button>
</section> }));

const candidates = Array.from({ length: 12 }, (_, index) => ({ id: index + 100, application_id: index + 1, rank: index + 1, display_score: String(100 - index), candidate_name: `Candidate ${index + 1}` }));
const jobs = [1, 2].map(id => ({ id, title: `Job ${id}`, application_count: 12, pending_count: 0 }));
function response(path: string): any {
  if (path === "/screening/jobs") return jobs;
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
  fireEvent.click(screen.getByRole("option", { name: /Posting #2/ }));
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
  fireEvent.click(selector); fireEvent.click(screen.getByRole("option", { name: /Posting #2/ }));
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
