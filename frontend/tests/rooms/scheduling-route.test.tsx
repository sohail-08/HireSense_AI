import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import App from "../../src/App";
import { apiRequest } from "../../src/api/apiClient";

const auth = vi.hoisted(() => ({ role: "interviewer" }));
vi.mock("../../src/api/apiClient", () => ({ apiRequest: vi.fn(), API_URL: "/api", TOKEN_KEY: "hiresense_token", ApiError: class extends Error {} }));
vi.mock("../../src/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: 1, role: auth.role, name: "Synthetic User" }, loading: false, logout: vi.fn() }),
  dashboardPath: () => `/${auth.role}/dashboard`,
}));
vi.mock("../../src/components/common/ApplicationNotifications", () => ({ ApplicationNotifications: () => null }));

beforeEach(() => {
  auth.role = "interviewer"; sessionStorage.clear(); vi.clearAllMocks();
  Object.defineProperty(window, "matchMedia", { configurable: true, value: vi.fn(() => ({ matches: false })) });
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
  vi.mocked(apiRequest).mockImplementation(async (path) => {
    if (path === "/screening/jobs") return [{ id: 1, title: "Synthetic Engineer", application_count: 1, pending_count: 0 }];
    if (path === "/scoring/jobs/1/runs") return [{ id: 10, status: "completed" }];
    if (path === "/scoring/runs/10") return { id: 10, job_posting_id: 1, status: "completed", results: [{ id: 1, application_id: 7, rank: 1, display_score: "85.00", candidate_name: "Synthetic Candidate" }] };
    if (path === "/interviews/selection/preview") return { selection_token: "synthetic-selection", selected: [{ application_id: 7, name: "Synthetic Candidate", rank: 1, score: "85", masked_email: "s***@example.test" }], excluded: [], warnings: [], recipient_count: 1 };
    throw new Error("Synthetic request boundary");
  });
});

it("opens the new protected page from the navbar and previews selection with the real form", async () => {
  render(<MemoryRouter initialEntries={["/interviewer/dashboard"]}><App /></MemoryRouter>);
  fireEvent.click(screen.getByRole("link", { name: "Schedule Interviews", exact: true }));
  expect(await screen.findByRole("heading", { level: 1, name: "Schedule interviews" })).toBeTruthy();
  const candidate = await screen.findByRole("checkbox", { name: "Select Synthetic Candidate for interview" });
  expect(vi.mocked(apiRequest).mock.calls.some(([, options]) => options?.method === "POST")).toBe(false);
  fireEvent.click(candidate);
  fireEvent.click(screen.getByRole("button", { name: "Preview candidate selection" }));
  await screen.findByText("1 eligible recipient(s)");
  const selection = vi.mocked(apiRequest).mock.calls.find(([path]) => path === "/interviews/selection/preview");
  expect(JSON.parse(selection![1]!.body as string)).toMatchObject({ job_posting_id: 1, ranking_run_id: 10, mode: "manual", application_ids: [7] });
  expect(vi.mocked(apiRequest).mock.calls.some(([path]) => path.includes("/confirm"))).toBe(false);
});

it("provides the new page's job and candidate selection to the central assistant", async () => {
  render(<MemoryRouter initialEntries={["/interviewer/schedule-interviews"]}><App /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("checkbox", { name: "Select Synthetic Candidate for interview" }));
  const input = screen.getByLabelText("Message HireSense assistant");
  fireEvent.change(input, { target: { value: "Schedule these candidates" } });
  fireEvent.submit(input.closest("form")!);
  await waitFor(() => expect(vi.mocked(apiRequest).mock.calls.some(([path]) => path === "/supervisor/chat")).toBe(true));
  const chat = vi.mocked(apiRequest).mock.calls.find(([path]) => path === "/supervisor/chat");
  expect(JSON.parse(chat![1]!.body as string)).toMatchObject({ page_context: "interviews", selected_job_posting_id: 1, selected_application_ids: [7] });
});

it("does not expose scheduling to candidate accounts", async () => {
  auth.role = "candidate";
  render(<MemoryRouter initialEntries={["/interviewer/schedule-interviews"]}><App /></MemoryRouter>);
  expect(await screen.findByRole("heading", { name: "Candidate dashboard" })).toBeTruthy();
  expect(screen.queryByRole("link", { name: "Schedule Interviews" })).toBeNull();
  expect(apiRequest).not.toHaveBeenCalled();
});
