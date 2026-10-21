import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import App from "../../src/App";
import { apiRequest } from "../../src/api/apiClient";
import { selectOption } from "./selectHelpers";

const auth = vi.hoisted(() => ({ role: "interviewer" }));
vi.mock("../../src/api/apiClient", () => ({ apiRequest: vi.fn(), API_URL: "/api", TOKEN_KEY: "hiresense_token", ApiError: class extends Error {} }));
vi.mock("../../src/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: 1, role: auth.role, name: "Synthetic User" }, loading: false, logout: vi.fn() }),
  dashboardPath: () => `/${auth.role}/dashboard`,
}));
vi.mock("../../src/components/common/ApplicationNotifications", () => ({ ApplicationNotifications: () => null }));

beforeEach(() => {
  auth.role = "interviewer"; sessionStorage.clear(); vi.clearAllMocks();
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value() { this.setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value() { this.removeAttribute("open"); } });
  Object.defineProperty(window, "matchMedia", { configurable: true, value: vi.fn(() => ({ matches: false })) });
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
  vi.mocked(apiRequest).mockImplementation(async (path) => {
    if (path === "/screening/jobs") return [{ id: 1, title: "Synthetic Engineer", application_count: 1, pending_count: 0 }];
    if (path === "/scoring/jobs/1/runs") return [{ id: 10, status: "completed" }];
    if (path === "/scoring/runs/10") return { id: 10, job_posting_id: 1, status: "completed", results: [{ id: 1, application_id: 7, rank: 1, display_score: "85.00", candidate_name: "Synthetic Candidate" }] };
    if (path === "/interviews/selection/preview") return { selection_token: "synthetic-selection", selected: [{ application_id: 7, name: "Synthetic Candidate", rank: 1, score: "85", email: "synthetic@example.test", masked_email: "s***@example.test" }], excluded: [], warnings: [], recipient_count: 1 };
    if (path === "/interviews/invitations/prepare") return { id: 22, confirmation_token: "synthetic-confirmation", recipient_count: 1, sender: { from_email: "sender@example.test", reply_to: "reply@example.test" }, recipients: [{ application_id: 7, name: "Synthetic Candidate", email: "synthetic@example.test", subject: "Interview invitation", body: "Synthetic invitation body", local_start: "2028-02-29T08:00:00", local_end: "2028-02-29T08:30:00", timezone: "Asia/Dhaka", duration_minutes: 30 }] };
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

it("preserves highest-ranked and score-based selection values with styled menus", async () => {
  render(<MemoryRouter initialEntries={["/interviewer/schedule-interviews"]}><App /></MemoryRouter>);
  await screen.findByText("Synthetic Candidate");
  selectOption("Which candidates?", "Highest-ranked candidates");
  fireEvent.change(screen.getByLabelText("Number of candidates"), { target: { value: "3" } });
  fireEvent.click(screen.getByRole("button", { name: "Preview candidate selection" }));
  await screen.findByText("1 eligible recipient(s)");
  let calls = vi.mocked(apiRequest).mock.calls.filter(([path]) => path === "/interviews/selection/preview");
  expect(JSON.parse(calls[0][1]!.body as string)).toMatchObject({ mode: "top_n", top_n: 3, application_ids: [] });
  fireEvent.click(screen.getByRole("button", { name: "Continue to schedule" }));
  selectOption("Which candidates?", "Candidates above a score");
  selectOption("Score comparison", "At least");
  fireEvent.change(screen.getByLabelText("Candidate score (%)"), { target: { value: "80" } });
  fireEvent.click(screen.getByRole("button", { name: "Preview candidate selection" }));
  await screen.findByText("1 eligible recipient(s)");
  calls = vi.mocked(apiRequest).mock.calls.filter(([path]) => path === "/interviews/selection/preview");
  expect(JSON.parse(calls[1][1]!.body as string)).toMatchObject({ mode: "threshold", threshold: "80", operator: "gte", application_ids: [] });
  expect(vi.mocked(apiRequest).mock.calls.some(([path]) => path.includes("/confirm"))).toBe(false);
});

it("uses modals for both previews, shows full emails and preserves the schedule contract without an email editor", async () => {
  render(<MemoryRouter initialEntries={["/interviewer/schedule-interviews"]}><App /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("checkbox", { name: "Select Synthetic Candidate for interview" }));
  fireEvent.click(screen.getByRole("button", { name: "Preview candidate selection" }));
  const selection = await screen.findByRole("dialog", { name: "Candidate selection" });
  expect(within(selection).getByText("synthetic@example.test")).toBeTruthy();
  expect(screen.queryByText("s***@example.test")).toBeNull();
  fireEvent.click(within(selection).getByRole("button", { name: "Continue to schedule" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.queryByText("Edit invitation email")).toBeNull();
  expect(screen.queryByLabelText("Subject template")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Date", exact: true }));
  fireEvent.change(screen.getByLabelText("Enter date (YYYY-MM-DD)"), { target: { value: "2028-02-29" } });
  fireEvent.click(screen.getByRole("button", { name: "Use date" }));
  fireEvent.click(screen.getByRole("button", { name: "Start time", exact: true }));
  fireEvent.click(screen.getByRole("button", { name: "Use time" }));
  fireEvent.click(screen.getByRole("button", { name: "Preview schedule & email" }));
  const preview = await screen.findByRole("dialog", { name: "Schedule & email preview" });
  expect(within(preview).getByText("synthetic@example.test")).toBeTruthy();
  expect(within(preview).getByText("Synthetic invitation body")).toBeTruthy();
  expect(within(preview).getByRole("button", { name: "Confirm & send 1 invitation(s)" })).toBeTruthy();
  const prepare = vi.mocked(apiRequest).mock.calls.find(([path]) => path === "/interviews/invitations/prepare");
  expect(JSON.parse(prepare![1]!.body as string)).toMatchObject({ date: "2028-02-29", start_time: "08:00", timezone: "Asia/Dhaka", mode: "sequential", duration_minutes: 30, buffer_minutes: 0, subject_template: "", body_template: "" });
  expect(vi.mocked(apiRequest).mock.calls.some(([path]) => path.includes("/confirm"))).toBe(false);
  fireEvent.click(within(preview).getByRole("button", { name: "Back to schedule" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Review schedule & email" }));
  const reopened = screen.getByRole("dialog", { name: "Schedule & email preview" });
  expect(reopened).toBeTruthy();
  fireEvent.click(within(reopened).getByRole("button", { name: "Confirm & send 1 invitation(s)" }));
  expect(await within(reopened).findByText("Synthetic request boundary")).toBeTruthy();
  expect(screen.getByRole("dialog", { name: "Schedule & email preview" })).toBeTruthy();
  expect(vi.mocked(apiRequest).mock.calls.filter(([path]) => path.includes("/confirm"))).toHaveLength(1);
});
