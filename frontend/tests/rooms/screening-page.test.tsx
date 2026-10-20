import React from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ScreeningPage } from "../../src/pages/ScreeningPage";
import { apiRequest } from "../../src/api/apiClient";

vi.mock("../../src/api/apiClient", () => ({ apiRequest: vi.fn(), ApiError: class extends Error {} }));
const supervisor = vi.hoisted(() => ({ setSelectedJobPostingId: vi.fn(), setSelectedApplicationIds: vi.fn(), refreshVersion: 0, batch: undefined }));
vi.mock("../../src/components/assistant/SupervisorProvider", () => ({ useSupervisor: () => supervisor }));
vi.mock("../../src/components/candidates/CandidateScoringPanel", () => ({ CandidateScoringPanel: () => <p>Scoring controls</p> }));

beforeEach(() => { vi.clearAllMocks(); });

it("explains processing failures without assigning a zero or creating a review gate", async () => {
  vi.mocked(apiRequest).mockImplementation(async path => {
    if (path === "/screening/jobs") return [{ id: 1, title: "Synthetic Engineer", application_count: 1, pending_count: 1 }];
    if (path === "/screening/jobs/1") return { job_posting_id: 1, applications: [{ id: 1, candidate_name: "Synthetic Candidate", screening_status: "failed", error_message: "CV evidence checking could not finish. Retry screening." }] };
    throw new Error("Unexpected test request");
  });
  render(<ScreeningPage />);
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
  render(<ScreeningPage />);
  expect(await screen.findByText("Scoring controls")).toBeTruthy();
  expect(screen.queryByText(/See affected candidates/)).toBeNull();
});
