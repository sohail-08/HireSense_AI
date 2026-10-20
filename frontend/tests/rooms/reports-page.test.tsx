import React from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "../../src/App";
import { apiRequest } from "../../src/api/apiClient";

vi.mock("../../src/api/apiClient", () => ({ apiRequest: vi.fn(), API_URL: "/api", TOKEN_KEY: "hiresense_token", ApiError: class extends Error {} }));
vi.mock("../../src/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: 1, role: "interviewer", name: "Synthetic Interviewer" }, loading: false, logout: vi.fn() }),
  dashboardPath: () => "/interviewer/dashboard",
}));
vi.mock("../../src/components/common/ApplicationNotifications", () => ({ ApplicationNotifications: () => null }));

const application = { application_id: 101, job_posting_id: 1,
  identification: { application_id: 101, job_posting_id: 1, candidate_name: "Synthetic Candidate", job_title: "Synthetic Engineer", requirement_version: "v1" },
  versions: [], interviews: [], missing: ["Completed interview"], selection_policy: "latest-completed" };

const savedReport = {
  id: 1, version: 1, application_id: 101, job_posting_id: 1, status: "completed", stage: "completed",
  completeness: "partial", review_status: "not_reviewed", stale: false, created_at: "2026-10-20T04:00:00Z", notes: [],
  result: { identification: application.identification, completeness: "partial", missing: [], flags: [], matrix: [], evidence: {}, interviews: [],
    summary: { position: [], strengths: [], limitations: [], verification: [], basis: "Synthetic saved results" }, policy: "CV score order only",
    cv: { final_score: "25.000000000000000000000000000000000000000000000000000000000000", categories: { technical: "50.000000000000000000000000000000000000000000000000000000000000", experience: "0E-60", qualification: "0E-60" },
      scoring_run_id: 1, screening_run_id: 1, document_id: 1, configuration_id: 1, original_cv_rank: 1, original_cohort: [101],
      configuration: { category_weights: { technical: "50", experience: "30", qualification: "20" } }, breakdown: { counts: { met: 1, unmet: 2 } },
      written_justification: "Synthetic saved justification", formula_version: "v1" } },
};

beforeEach(() => {
  sessionStorage.clear();
  Object.defineProperty(window, "matchMedia", { configurable: true, value: vi.fn(() => ({ matches: false })) });
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
  vi.mocked(apiRequest).mockImplementation(async (path) => {
    if (path === "/screening/jobs") return [{ id: 1, title: "Synthetic Engineer", posting_status: "published", application_count: 1, pending_count: 0 }];
    if (path === "/assessments/applications?job_posting_id=1") return [application];
    throw new Error(`Unexpected test API request: ${path}`);
  });
});

it("loads the full Reports route through the navbar with the real supervisor provider", async () => {
  render(<MemoryRouter initialEntries={["/interviewer/dashboard"]}><App /></MemoryRouter>);
  fireEvent.click(screen.getByRole("link", { name: "Reports" }));
  expect(await screen.findByRole("heading", { name: "Candidate assessment reports" })).toBeTruthy();
  expect(await screen.findByText("Synthetic Candidate")).toBeTruthy();
  expect(await screen.findByRole("button", { name: "Generate assessment" })).toBeTruthy();
});

it("opens an existing report containing PostgreSQL scientific-notation zero scores", async () => {
  vi.mocked(apiRequest).mockImplementation(async path => {
    if (path === "/screening/jobs") return [{ id: 1, title: "Synthetic Engineer" }];
    if (path === "/assessments/applications?job_posting_id=1") return [{ ...application, versions: [{ id: 1, version: 1, status: "completed", completeness: "partial" }] }];
    if (path === "/assessments/runs/1") return savedReport;
    throw new Error(`Unexpected test API request: ${path}`);
  });
  render(<MemoryRouter initialEntries={["/interviewer/dashboard"]}><App /></MemoryRouter>);
  fireEvent.click(screen.getByRole("link", { name: "Reports" }));
  expect(await screen.findByRole("article", { name: "Consolidated candidate assessment" })).toBeTruthy();
  expect(screen.getAllByText("0.00%")).toHaveLength(2);
  expect(screen.getByText("25.00%")).toBeTruthy();
});

it("keeps navigation visible and offers recovery after an unexpected report render error", async () => {
  const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
  try {
    vi.mocked(apiRequest).mockImplementation(async path => {
      if (path === "/screening/jobs") return [{ id: 1, title: "Synthetic Engineer" }];
      if (path === "/assessments/applications?job_posting_id=1") return [{ ...application, versions: [{ id: 1, version: 1, status: "completed" }] }];
      if (path === "/assessments/runs/1") return { ...savedReport, result: null };
      throw new Error(`Unexpected test API request: ${path}`);
    });
    render(<MemoryRouter initialEntries={["/interviewer/reports"]}><App /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "Reports could not be displayed" })).toBeTruthy();
    expect(screen.getByRole("navigation", { name: "Main navigation" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reload Reports" })).toBeTruthy();
    fireEvent.click(screen.getByRole("link", { name: "Back to candidate ranking" }));
    expect(await screen.findByRole("heading", { name: "Candidate ranking" })).toBeTruthy();
  } finally { consoleError.mockRestore(); }
});
