import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { InterviewerDashboard } from "../../src/pages/InterviewerDashboard";
import { dashboardSummary, type DashboardInterview, type DashboardData } from "../../src/components/dashboard/dashboardData";
import { apiRequest } from "../../src/api/apiClient";

vi.mock("../../src/api/apiClient", () => ({ apiRequest: vi.fn() }));
vi.mock("../../src/auth/AuthProvider", () => ({ useAuth: () => ({ user: { name: "Synthetic Interviewer" } }) }));
const supervisor = vi.hoisted(() => ({ refreshVersion: 0, addTaskMessage: vi.fn(), sendMessage: vi.fn() }));
vi.mock("../../src/components/assistant/SupervisorProvider", () => ({ useSupervisor: () => supervisor }));
const now = Date.parse("2026-10-21T20:00:00Z"); // 22 October, 2 AM in Dhaka.
const interview = (id: number, extra: Partial<DashboardInterview> = {}): DashboardInterview => ({
  id, candidate_name: `Candidate ${id}`, job_title: "Frontend Engineer", status: "scheduled", room_status: "scheduled",
  start_utc: "2026-10-22T02:00:00Z", end_utc: "2026-10-22T02:30:00Z", duration_minutes: 30, ...extra,
});
const sample: DashboardData = {
  jobs: [{ id: 1, status: "draft" }, { id: 2, status: "approved" }, { id: 3, status: "archived" }] as DashboardData["jobs"],
  screening: [
    { id: 1, title: "Frontend Engineer", posting_status: "published", application_count: 4, pending_count: 2 },
    { id: 2, title: "Backend Engineer", posting_status: "closed", application_count: 3, pending_count: 0 },
    { id: 3, title: "New Role", posting_status: "draft", application_count: 0, pending_count: 0 },
  ],
  interviews: [interview(1), interview(2, { status: "completed", room_status: "ended" }), interview(3, { status: "cancelled", room_status: "cancelled" }),
    interview(4, { start_utc: "2026-10-20T02:00:00Z", end_utc: "2026-10-20T02:30:00Z" }),
    interview(5, { room_status: "waiting", start_utc: "2026-10-21T19:00:00Z", end_utc: "2026-10-21T19:30:00Z" }),
    interview(6, { room_status: "ending" })],
};
beforeEach(() => {
  vi.clearAllMocks(); supervisor.refreshVersion = 0;
  vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(now);
  vi.mocked(apiRequest).mockImplementation(async path => {
    if (path === "/job-descriptions") return sample.jobs;
    if (path === "/screening/jobs") return sample.screening;
    if (path === "/interviews/schedules") return sample.interviews;
    throw new Error(`Unexpected synthetic request: ${path}`);
  });
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });
function open() { return render(<MemoryRouter><InterviewerDashboard /></MemoryRouter>); }
async function loaded() { await waitFor(() => expect((screen.getByRole("button", { name: "Refresh overview" }) as HTMLButtonElement).disabled).toBe(false)); }
function total(name: string) { return within(screen.getByRole("region", { name: "Hiring totals" })).getByRole("link", { name: new RegExp(name) }).querySelector("dd")?.textContent; }

it("computes real totals and prioritizes open rooms without counting cancelled or completed interviews", () => {
  const summary = dashboardSummary(sample, now);
  expect(summary).toMatchObject({ published: 1, applications: 7, pending: 2, drafts: 1, approved: 1, completed: 1, overdue: 1, today: 2 });
  expect(summary.upcoming?.map(item => item.id)).toEqual([5, 1]);
  expect(sample.interviews?.map(item => item.id)).toEqual([1, 2, 3, 4, 5, 6]);
  expect(summary.roles?.map(role => role.id)).toEqual([1, 2]);
});

it("uses Dhaka calendar days across UTC midnight and treats offset-free UTC timestamps consistently", () => {
  const summary = dashboardSummary({ interviews: [interview(7, { start_utc: "2026-10-21T21:00:00", end_utc: "2026-10-21T21:30:00" }),
    interview(8, { start_utc: "2026-10-22T18:00:00Z", end_utc: "2026-10-22T18:30:00Z" }),
    interview(9, { start_utc: "invalid", end_utc: "invalid" })] }, now);
  expect(summary.today).toBe(1);
  expect(summary.upcoming?.map(item => item.id)).toEqual([7, 8]);
});

it("keeps an ongoing time slot visible even if its scheduled start is in the past", () => {
  const summary = dashboardSummary({ interviews: [interview(10, { start_utc: "2026-10-21T19:50:00Z", end_utc: "2026-10-21T20:20:00Z" })] }, now);
  expect(summary.upcoming).toHaveLength(1); expect(summary.overdue).toBe(0);
});

it("does not turn missing sources into zero totals", () => {
  expect(dashboardSummary({}, now)).toMatchObject({ published: undefined, applications: undefined, upcoming: undefined, drafts: undefined });
});

it("loads only read APIs and shows useful totals, attention items, interview links and progress", async () => {
  open(); await loaded();
  expect(total("Published posts")).toBe("1"); expect(total("Applications")).toBe("7");
  expect(total("Need CV screening")).toBe("2"); expect(total("Upcoming interviews")).toBe("2");
  expect(screen.getByText("Welcome back, Synthetic Interviewer. Here’s where your hiring stands.")).toBeTruthy();
  expect(screen.getByText("22 Oct 2026 · Dhaka time")).toBeTruthy();
  expect(screen.getByText("2 interviews today")).toBeTruthy();
  const next = screen.getByRole("region", { name: "Next interviews" });
  expect(within(next).getAllByRole("listitem")[0].textContent).toContain("Candidate 5");
  expect(within(next).getByRole("link", { name: "Open interview with Candidate 1" }).getAttribute("href")).toBe("/interviews/1/console");
  expect(next.textContent).toContain("8:00 AM");
  expect(within(next).queryByText("Candidate 2")).toBeNull();
  const attention = screen.getByRole("region", { name: "Needs attention" });
  expect(within(attention).getByText("Review CV screening")).toBeTruthy();
  expect(within(attention).getByText("Review job drafts")).toBeTruthy();
  expect(within(attention).getByText("Check past interview slots")).toBeTruthy();
  const progress = screen.getByRole("progressbar", { name: "CV screening for Frontend Engineer" });
  expect(progress.getAttribute("aria-valuenow")).toBe("2"); expect(progress.getAttribute("aria-valuemax")).toBe("4");
  expect(vi.mocked(apiRequest).mock.calls.map(([path]) => path).sort()).toEqual(["/interviews/schedules", "/job-descriptions", "/screening/jobs"]);
  expect(vi.mocked(apiRequest).mock.calls.some(([, options]) => options?.method && options.method !== "GET")).toBe(false);
  expect(supervisor.addTaskMessage).not.toHaveBeenCalled(); expect(supervisor.sendMessage).not.toHaveBeenCalled();
  expect(screen.queryByText(/Recruitment features will follow/)).toBeNull();
});

it("shows helpful first-use empty states with true zero counts", async () => {
  vi.mocked(apiRequest).mockResolvedValue([]); open(); await loaded();
  expect(total("Applications")).toBe("0"); expect(total("Upcoming interviews")).toBe("0");
  expect(screen.getByText("Start with your first role")).toBeTruthy();
  expect(screen.getByText("No upcoming interviews")).toBeTruthy();
  expect(screen.getByText("Your roles will appear here")).toBeTruthy();
  expect(screen.getByRole("link", { name: "Create a job description" }).getAttribute("href")).toBe("/interviewer/jobs");
  expect(screen.queryByRole("progressbar")).toBeNull();
});

it("preserves successful sections when one source fails and recovers on explicit refresh", async () => {
  const original = vi.mocked(apiRequest).getMockImplementation()!;
  let fail = true;
  vi.mocked(apiRequest).mockImplementation(async (path, options) => {
    if (path === "/screening/jobs" && fail) throw new Error("Synthetic unavailable");
    return original(path, options);
  });
  open(); await loaded();
  expect(screen.getByRole("alert").textContent).toContain("applications and screening");
  expect(total("Applications")).toBe("—"); expect(total("Upcoming interviews")).toBe("2");
  expect(screen.queryByText("You’re up to date")).toBeNull();
  fail = false; fireEvent.click(screen.getByRole("button", { name: "Refresh overview" })); await loaded();
  expect(screen.queryByRole("alert")).toBeNull(); expect(total("Applications")).toBe("7");
});

it("shows unavailable rather than an empty workspace when every API fails", async () => {
  vi.mocked(apiRequest).mockRejectedValue(new Error("Synthetic unavailable")); open(); await loaded();
  expect(total("Published posts")).toBe("—"); expect(total("Applications")).toBe("—");
  expect(screen.queryByText("Start with your first role")).toBeNull(); expect(screen.queryByText("No upcoming interviews")).toBeNull();
  expect(screen.getByText("Refresh the missing information to see your next steps.")).toBeTruthy();
});

it("updates when a chatbot workflow requests a refresh without sending a chat message", async () => {
  const view = open(); await loaded(); const before = vi.mocked(apiRequest).mock.calls.length;
  supervisor.refreshVersion++;
  view.rerender(<MemoryRouter><InterviewerDashboard /></MemoryRouter>); await loaded();
  expect(vi.mocked(apiRequest).mock.calls).toHaveLength(before + 3);
  expect(supervisor.sendMessage).not.toHaveBeenCalled();
});

it("does not invent screening progress for a published role without applications", async () => {
  const original = vi.mocked(apiRequest).getMockImplementation()!;
  vi.mocked(apiRequest).mockImplementation(async (path, options) => path === "/screening/jobs" ? [{ id: 1, title: "Empty role", posting_status: "published", application_count: 0, pending_count: 0 }] : original(path, options));
  open(); await loaded();
  expect(screen.getByText("No applications yet")).toBeTruthy(); expect(screen.queryByRole("progressbar")).toBeNull();
});
