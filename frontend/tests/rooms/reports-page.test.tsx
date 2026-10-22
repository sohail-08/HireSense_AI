import React from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "../../src/App";
import { apiRequest } from "../../src/api/apiClient";
import { selectOption } from "./selectHelpers";

vi.mock("../../src/api/apiClient", () => ({ apiRequest: vi.fn(), API_URL: "/api", TOKEN_KEY: "hiresense_token", ApiError: class extends Error {} }));
vi.mock("../../src/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: 1, role: "interviewer", name: "Synthetic Interviewer" }, loading: false, logout: vi.fn() }),
  dashboardPath: () => "/interviewer/dashboard",
}));
vi.mock("../../src/components/common/ApplicationNotifications", () => ({ ApplicationNotifications: () => null }));

const application = { application_id: 101, job_posting_id: 1,
  identification: { application_id: 101, job_posting_id: 1, candidate_name: "Synthetic Candidate", job_title: "Synthetic Engineer", requirement_version: "v1" },
  versions: [], interviews: [], missing: ["Completed interview"], selection_policy: "latest-completed" };

const ranking = { id: 1, status: "completed", stage: "completed", policy: "CV 40% + interview 60%", stale: false, incompatibilities: [], candidates: [
  { application_id: 101, candidate_name: "Synthetic Candidate", cv_score: "25.00000", interview_score: "0E-60", final_score: "10", final_rank: 1, assessment_id: 1, reason: "CV 40% + interview 60%" }
] };

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
    if (path === "/assessments/jobs/1/ranking") return ranking;
    throw new Error(`Unexpected test API request: ${path}`);
  });
});

it("loads the Assessment route through the navbar with the real supervisor provider", async () => {
  render(<MemoryRouter initialEntries={["/interviewer/dashboard"]}><App /></MemoryRouter>);
  fireEvent.click(screen.getByRole("link", { name: "Assessment", exact: true }));
  expect(await screen.findByRole("heading", { name: "Candidate ranking" })).toBeTruthy();
  expect(await screen.findByText("Synthetic Candidate")).toBeTruthy();
  expect(await screen.findByRole("button", { name: "Calculate final ranking" })).toBeTruthy();
  expect(vi.mocked(apiRequest).mock.calls.some(([, options]) => options?.method === "POST")).toBe(false);
});

it("calculates only on request and shows background progress in plain words", async () => {
  vi.mocked(apiRequest).mockImplementation(async (path, options) => {
    if (path === "/screening/jobs") return [{ id: 1, title: "Synthetic Engineer" }];
    if (path === "/assessments/jobs/1/ranking") return options?.method === "POST" ? { ...ranking, status: "processing", stage: "scoring_answers" } : ranking;
    throw new Error(`Unexpected test API request: ${path}`);
  });
  render(<MemoryRouter initialEntries={["/interviewer/reports"]}><App /></MemoryRouter>);
  await screen.findByText("Synthetic Candidate");
  fireEvent.click(await screen.findByRole("button", { name: "Calculate final ranking" }));
  expect(await screen.findByText(/Scoring interview answers/)).toBeTruthy();
  expect((screen.getByRole("button", { name: "Calculating…" }) as HTMLButtonElement).disabled).toBe(true);
  expect(apiRequest).toHaveBeenCalledWith("/assessments/jobs/1/ranking", { method: "POST", body: JSON.stringify({ confirmed: true }) });
});

it("shows a missing interview as a short reason, not a zero or needs-review gate", async () => {
  vi.mocked(apiRequest).mockImplementation(async path => {
    if (path === "/screening/jobs") return [{ id: 1, title: "Synthetic Engineer" }];
    if (path === "/assessments/jobs/1/ranking") return { ...ranking, candidates: [{ ...ranking.candidates[0], final_rank: null, interview_score: null, final_score: null, reason: "Interview not scored yet" }] };
    throw new Error(`Unexpected test API request: ${path}`);
  });
  render(<MemoryRouter initialEntries={["/interviewer/reports"]}><App /></MemoryRouter>);
  expect(await screen.findByText("Interview not scored yet")).toBeTruthy();
  expect(screen.queryByText("0.00%")).toBeNull();
  expect(screen.queryByText(/Needs review/i)).toBeNull();
});

it("keeps saved scores visible and lets the user retry when calculation fails", async () => {
  vi.mocked(apiRequest).mockImplementation(async (path, options) => {
    if (path === "/screening/jobs") return [{ id: 1, title: "Synthetic Engineer" }];
    if (path === "/assessments/jobs/1/ranking") {
      if (options?.method === "POST") throw new Error("Please try again.");
      return ranking;
    }
    throw new Error(`Unexpected test API request: ${path}`);
  });
  render(<MemoryRouter initialEntries={["/interviewer/reports"]}><App /></MemoryRouter>);
  await screen.findByText("Synthetic Candidate");
  fireEvent.click(await screen.findByRole("button", { name: "Calculate final ranking" }));
  expect(await screen.findByRole("alert")).toBeTruthy();
  await waitFor(() => expect((screen.getByRole("button", { name: "Calculate final ranking" }) as HTMLButtonElement).disabled).toBe(false));
  expect(screen.getByText("10.00%")).toBeTruthy();
  expect(screen.getByText("CV 40%")).toBeTruthy();
  expect(screen.getByText("Interview 60%")).toBeTruthy();
});

it("opens an existing report containing PostgreSQL scientific-notation zero scores", async () => {
  vi.mocked(apiRequest).mockImplementation(async path => {
    if (path === "/screening/jobs") return [{ id: 1, title: "Synthetic Engineer" }];
    if (path === "/assessments/jobs/1/ranking") return ranking;
    if (path === "/assessments/applications/101") return application;
    if (path === "/assessments/runs/1") return savedReport;
    throw new Error(`Unexpected test API request: ${path}`);
  });
  render(<MemoryRouter initialEntries={["/interviewer/dashboard"]}><App /></MemoryRouter>);
  fireEvent.click(screen.getByRole("link", { name: "Assessment", exact: true }));
  fireEvent.click(await screen.findByRole("button", { name: "View details for Synthetic Candidate" }));
  expect(await screen.findByRole("dialog", { name: "Candidate assessment" })).toBeTruthy();
  expect(await screen.findByRole("article", { name: "Consolidated candidate assessment" })).toBeTruthy();
  expect(screen.getByText("0.00%")).toBeTruthy();
  expect(screen.getAllByText("25.00%")).toHaveLength(2);
});

it("closes candidate details without losing the ranking search or keyboard focus", async () => {
  vi.mocked(apiRequest).mockImplementation(async path => {
    if (path === "/screening/jobs") return [{ id: 1, title: "Synthetic Engineer" }];
    if (path === "/assessments/jobs/1/ranking") return ranking;
    if (path === "/assessments/runs/1") return savedReport;
    throw new Error(`Unexpected test API request: ${path}`);
  });
  render(<MemoryRouter initialEntries={["/interviewer/reports"]}><App /></MemoryRouter>);
  const search = await screen.findByRole("searchbox", { name: "Search candidates" });
  fireEvent.change(search, { target: { value: "Synthetic" } });
  const open = screen.getByRole("button", { name: "View details for Synthetic Candidate" }); open.focus(); fireEvent.click(open);
  const modal = await screen.findByRole("dialog", { name: "Candidate assessment" });
  await screen.findByRole("article", { name: "Consolidated candidate assessment" });
  fireEvent.click(within(modal).getByRole("button", { name: "Close preview" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect((screen.getByRole("searchbox") as HTMLInputElement).value).toBe("Synthetic");
  expect(document.activeElement).toBe(open);
});

it("offers an in-modal retry if candidate details fail to load", async () => {
  let attempts = 0;
  vi.mocked(apiRequest).mockImplementation(async path => {
    if (path === "/screening/jobs") return [{ id: 1, title: "Synthetic Engineer" }];
    if (path === "/assessments/jobs/1/ranking") return ranking;
    if (path === "/assessments/runs/1") { if (++attempts === 1) throw new Error("Details unavailable."); return savedReport; }
    throw new Error(`Unexpected test API request: ${path}`);
  });
  render(<MemoryRouter initialEntries={["/interviewer/reports"]}><App /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: "View details for Synthetic Candidate" }));
  const modal = await screen.findByRole("dialog", { name: "Candidate assessment" });
  expect((await within(modal).findByRole("alert")).textContent).toContain("Details unavailable.");
  fireEvent.click(within(modal).getByRole("button", { name: "Try again" }));
  expect(await screen.findByRole("article", { name: "Consolidated candidate assessment" })).toBeTruthy();
  expect(attempts).toBe(2);
});

it("handles no job postings without leaving a permanent loading state", async () => {
  vi.mocked(apiRequest).mockImplementation(async path => { if (path === "/screening/jobs") return []; throw new Error(`Unexpected test API request: ${path}`); });
  render(<MemoryRouter initialEntries={["/interviewer/reports"]}><App /></MemoryRouter>);
  expect(await screen.findByRole("heading", { name: "No job postings yet" })).toBeTruthy();
  expect(screen.getByRole("link", { name: "Go to jobs" }).getAttribute("href")).toBe("/interviewer/jobs");
  expect(screen.queryByText("Loading candidates…")).toBeNull();
  expect((screen.getByRole("button", { name: "Calculate final ranking" }) as HTMLButtonElement).disabled).toBe(true);
});

it("resets candidate search when changing jobs without calculating either ranking", async () => {
  vi.mocked(apiRequest).mockImplementation(async path => {
    if (path === "/screening/jobs") return [{ id: 1, title: "Synthetic Engineer" }, { id: 2, title: "Second job" }];
    if (path === "/assessments/jobs/1/ranking") return ranking;
    if (path === "/assessments/jobs/2/ranking") return { ...ranking, candidates: [{ ...ranking.candidates[0], candidate_name: "Second Candidate" }] };
    throw new Error(`Unexpected test API request: ${path}`);
  });
  render(<MemoryRouter initialEntries={["/interviewer/reports"]}><App /></MemoryRouter>);
  const search = await screen.findByRole("searchbox", { name: "Search candidates" });
  fireEvent.change(search, { target: { value: "Synthetic" } });
  selectOption("Job posting", /Second job/);
  expect(await screen.findByText("Second Candidate")).toBeTruthy();
  expect((screen.getByRole("searchbox") as HTMLInputElement).value).toBe("");
  expect(vi.mocked(apiRequest).mock.calls.some(([, options]) => options?.method === "POST")).toBe(false);
});

it("keeps navigation visible and offers recovery after an unexpected report render error", async () => {
  const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
  try {
    vi.mocked(apiRequest).mockImplementation(async path => {
      if (path === "/screening/jobs") return [{ id: 1, title: "Synthetic Engineer" }];
      if (path === "/assessments/jobs/1/ranking") return ranking;
      if (path === "/assessments/applications/101") return application;
      if (path === "/assessments/runs/1") return { ...savedReport, result: null };
      throw new Error(`Unexpected test API request: ${path}`);
    });
    render(<MemoryRouter initialEntries={["/interviewer/reports?application=101&run=1"]}><App /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "Reports could not be displayed" })).toBeTruthy();
    expect(screen.getByRole("navigation", { name: "Main navigation" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reload Reports" })).toBeTruthy();
    fireEvent.click(screen.getByRole("link", { name: "Back to candidate ranking" }));
    expect(await screen.findByRole("heading", { name: "Candidate ranking" })).toBeTruthy();
  } finally { consoleError.mockRestore(); }
});
