import React from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { ScreeningPage } from "../../src/pages/ScreeningPage";
import { apiRequest } from "../../src/api/apiClient";

vi.mock("../../src/api/apiClient", () => ({ apiRequest: vi.fn(), ApiError: class extends Error {} }));
const supervisor = vi.hoisted(() => ({ setSelectedJobPostingId: vi.fn(), setSelectedApplicationIds: vi.fn(), refreshVersion: 0, batch: undefined }));
vi.mock("../../src/components/assistant/SupervisorProvider", () => ({ useSupervisor: () => supervisor }));
vi.mock("../../src/components/candidates/CandidateScoringPanel", () => ({ CandidateScoringPanel: ({ jobSelector, jobId }: any) => <section aria-label="Ranking controls">{jobSelector}<p>Scoring controls</p><p>Selected job {jobId}</p></section> }));

beforeEach(() => { vi.clearAllMocks(); });

it("explains processing failures without assigning a zero or creating a review gate", async () => {
  vi.mocked(apiRequest).mockImplementation(async path => {
    if (path === "/screening/jobs") return [{ id: 1, title: "Synthetic Engineer", application_count: 1, pending_count: 1 }];
    if (path === "/screening/jobs/1") return { job_posting_id: 1, applications: [{ id: 1, candidate_name: "Synthetic Candidate", screening_status: "failed", error_message: "CV evidence checking could not finish. Retry screening." }] };
    throw new Error("Unexpected test request");
  });
  render(<MemoryRouter><ScreeningPage /></MemoryRouter>);
  expect(await screen.findByText(/They have not been assigned a zero score/)).toBeTruthy();
  expect(screen.getByText("Synthetic Candidate:")).toBeTruthy();
  expect(screen.getByText(/See affected candidates/).closest("details")?.open).toBe(false);
  expect(screen.queryByText(/Needs review/)).toBeNull();
  expect(vi.mocked(apiRequest).mock.calls.some(([,options]) => options?.method === "POST")).toBe(false);
});

it("keeps the ordinary screening screen uncluttered when no CV failed", async () => {
  vi.mocked(apiRequest).mockImplementation(async path => path === "/screening/jobs" ?
    [{ id: 1, title: "Synthetic Engineer", application_count: 1, pending_count: 0 }] :
    { job_posting_id: 1, applications: [{ id: 1, candidate_name: "Synthetic Candidate", screening_status: "completed" }] });
  render(<MemoryRouter><ScreeningPage /></MemoryRouter>);
  expect(await screen.findByText("Scoring controls")).toBeTruthy();
  expect(screen.queryByText(/See affected candidates/)).toBeNull();
});

it("places the job selector inside the ranking section and switches the selected job", async () => {
  vi.mocked(apiRequest).mockImplementation(async path => path === "/screening/jobs" ?
    [1, 2].map(id => ({ id, title: id === 1 ? "Backend Engineer" : "Frontend Engineer", application_count: 1, pending_count: 0 })) :
    { job_posting_id: Number(path.split("/").pop()), applications: [] });
  render(<MemoryRouter><ScreeningPage /></MemoryRouter>);
  const controls = await screen.findByRole("region", { name: "Ranking controls" });
  expect(within(controls).getByLabelText("Job posting")).toBeTruthy();
  expect(within(controls).getByText(/1 candidate/)).toBeTruthy();
  fireEvent.click(within(controls).getByLabelText("Job posting"));
  fireEvent.click(screen.getByRole("option", { name: /Frontend Engineer/ }));
  expect(await screen.findByText("Selected job 2")).toBeTruthy();
  expect(screen.getAllByLabelText("Job posting")).toHaveLength(1);
});

it("opens the specific job requested by an assistant destination", async () => {
  vi.mocked(apiRequest).mockImplementation(async path => path === "/screening/jobs" ?
    [1, 2].map(id => ({ id, title: `Role ${id}`, application_count: 1, pending_count: 0 })) :
    { job_posting_id: Number(path.split("/").pop()), applications: [] });
  render(<MemoryRouter initialEntries={["/interviewer/assessments?job=2"]}><ScreeningPage /></MemoryRouter>);
  expect(await screen.findByText("Selected job 2")).toBeTruthy();
});
