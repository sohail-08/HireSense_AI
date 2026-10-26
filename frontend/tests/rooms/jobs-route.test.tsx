import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "../../src/App";
import { apiRequest } from "../../src/api/apiClient";
import type { JobDescriptionResponse, SupervisorChatResponse } from "../../src/types";

vi.mock("../../src/api/apiClient", () => ({ apiRequest: vi.fn(), API_URL: "/api", TOKEN_KEY: "hiresense_token", ApiError: class extends Error {} }));
vi.mock("../../src/auth/AuthProvider", () => ({ useAuth: () => ({ user: { id: 1, role: "interviewer", name: "Synthetic User" }, loading: false, logout: vi.fn() }), dashboardPath: () => "/interviewer/dashboard" }));
vi.mock("../../src/components/common/ApplicationNotifications", () => ({ ApplicationNotifications: () => null }));
vi.mock("../../src/components/jobs/DiscordJobPostPanel", () => ({ DiscordJobPostPanel: () => <p>Publication tools</p> }));

const draft: JobDescriptionResponse = { id: 7, title: "Synthetic frontend engineer", content: "Build accessible interfaces.", version: 1, status: "draft", requirement_profile_id: 2,
  source_references: [], created_by_user_id: 1, created_at: "2026-10-22T01:00:00Z", updated_at: "2026-10-22T01:00:00Z",
  structured_content: { title: "Engineer", summary: "Build products", responsibilities: [], required_skills: [], preferred_skills: [], qualifications: [], selection_criteria: [], experience_requirement: "2 years" } };
const result: SupervisorChatResponse = { session_id: "synthetic-session", phase: "job_description_approved", route: "job_description", assistant_message: "Approved.", outcome: "success", messages: [{ role: "assistant", content: "Approved.", outcome: "success" }],
  requirement_profile_id: 2, requirement_state: { profile: { title: "Engineer", summary: null, required_skills: [], preferred_skills: [], qualifications: [], min_years_experience: 2, selection_criteria: [] },
    missing_fields: [], knowledge_status: "empty", proposal_ready: true, source_references: [] }, job_description: { ...draft, status: "approved" }, job_posting: null, refresh_required: false, sync_result: null, screening_batch: null };
beforeEach(() => {
  vi.clearAllMocks(); sessionStorage.clear();
  Object.defineProperty(window, "matchMedia", { configurable: true, value: vi.fn(() => ({ matches: false })) });
  Object.defineProperty(HTMLElement.prototype, "scrollTo", { configurable: true, value: vi.fn() });
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: vi.fn() });
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
  vi.mocked(apiRequest).mockImplementation(async (path, options) => {
    if (path === "/job-descriptions") return [draft];
    if (path === "/job-descriptions/7/approve" && options?.method === "POST") return result.job_description;
    throw new Error(`Unexpected synthetic request: ${path}`);
  });
});
afterEach(() => vi.restoreAllMocks());

it("keeps the chat unchanged when jobs are manually deleted, including failed deletes", async () => {
  let jobs = [draft, { ...draft, id: 8, title: "Another frontend role" }];
  let fail = true;
  vi.mocked(apiRequest).mockImplementation(async (path, options) => {
    if (path === "/job-descriptions") return jobs;
    if (path === "/job-descriptions/7" && options?.method === "DELETE") {
      if (fail) { fail = false; throw new Error("Synthetic delete unavailable."); }
      jobs = jobs.filter(job => job.id !== 7); return undefined;
    }
    if (path === "/job-descriptions/8" && options?.method === "DELETE") { jobs = []; return undefined; }
    throw new Error(`Unexpected synthetic request: ${path}`);
  });
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<MemoryRouter initialEntries={["/interviewer/jobs"]}><App /></MemoryRouter>);
  await screen.findByRole("list", { name: "Saved job cards" });
  fireEvent.click(screen.getByRole("button", { name: "Assistant", exact: true }));
  const chat = screen.getByRole("dialog", { name: "HireSense supervisor" });
  const before = chat.textContent;
  fireEvent.click(screen.getByRole("button", { name: `Delete job: ${draft.title}` }));
  expect((await screen.findByRole("alert")).textContent).toContain("Synthetic delete unavailable.");
  expect(chat.textContent).toBe(before);
  fireEvent.click(screen.getByRole("button", { name: `Delete job: ${draft.title}` }));
  await screen.findByText(`Deleted “${draft.title}”.`);
  expect(chat.textContent).toBe(before);
  expect(screen.queryByRole("button", { name: `Delete job: ${draft.title}` })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Delete job: Another frontend role" }));
  await screen.findByText("Deleted “Another frontend role”.");
  expect(chat.textContent).toBe(before);
  expect(vi.mocked(apiRequest).mock.calls.some(([path]) => path === "/supervisor/chat")).toBe(false);
});

it("keeps the shared assistant available without a dedicated creation button or automatic request", async () => {
  render(<MemoryRouter initialEntries={["/interviewer/jobs"]}><App /></MemoryRouter>);
  await screen.findByRole("list", { name: "Saved job cards" });
  fireEvent.click(screen.getByRole("button", { name: "Assistant", exact: true }));
  const chat = await screen.findByRole("dialog", { name: "HireSense supervisor" });
  expect(within(chat).getByRole("textbox", { name: "Message HireSense assistant" })).toBeTruthy();
  expect(screen.queryByRole("region", { name: "Current job workspace" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Create with assistant" })).toBeNull();
  expect(vi.mocked(apiRequest).mock.calls.some(([, options]) => options?.method === "POST")).toBe(false);
});

it("approves the specifically selected saved draft without requiring a chatbot request", async () => {
  render(<MemoryRouter initialEntries={["/interviewer/jobs"]}><App /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: `Edit draft: ${draft.title}` }));
  const modal = screen.getByRole("dialog", { name: "Edit job draft" });
  fireEvent.click(within(modal).getByRole("button", { name: "Approve job description" }));
  await waitFor(() => expect(apiRequest).toHaveBeenCalledWith("/job-descriptions/7/approve", { method: "POST" }));
  expect(vi.mocked(apiRequest).mock.calls.some(([path]) => path === "/supervisor/chat")).toBe(false);
  expect(await screen.findByRole("dialog", { name: "Job details" })).toBeTruthy();
  expect(within(screen.getByRole("dialog", { name: "Job details" })).getByText("Approved")).toBeTruthy();
  expect(vi.mocked(apiRequest).mock.calls.some(([path]) => path.includes("publish"))).toBe(false);
});

it("shows the generated JD after one hiring request without requirements confirmation or a generate button", async () => {
  let loads = 0;
  let finishLayout!: (value: JobDescriptionResponse[]) => void;
  vi.mocked(apiRequest).mockImplementation(async (path, options) => {
    if (path === "/job-descriptions") return ++loads === 1 ? [draft] : new Promise(resolve => { finishLayout = resolve as typeof finishLayout; });
    if (path === "/supervisor/chat" && options?.method === "POST") return { ...result,
      phase: "job_description_draft", route: "generate_job_description", job_description: draft, refresh_required: true,
      messages: [{ role: "user", content: "I want to hire a frontend engineer", outcome: "info" },
        { role: "assistant", content: "I drafted your job description. Review it when you are ready.", outcome: "success" }] };
    throw new Error(`Unexpected synthetic request: ${path}`);
  });
  render(<MemoryRouter initialEntries={["/interviewer/jobs"]}><App /></MemoryRouter>);
  await screen.findByRole("list", { name: "Saved job cards" });
  fireEvent.click(screen.getByRole("button", { name: "Assistant", exact: true }));
  const chat = screen.getByRole("dialog", { name: "HireSense supervisor" });
  fireEvent.change(within(chat).getByRole("textbox", { name: "Message HireSense assistant" }), { target: { value: "I want to hire a frontend engineer" } });
  fireEvent.click(within(chat).getByRole("button", { name: "Send message" }));
  const workspace = await screen.findByRole("region", { name: "Current job workspace" });
  await within(workspace).findByRole("heading", { name: "Review your job description" });
  expect(within(workspace).getByRole("article", { name: "Job description preview" }).textContent).toContain(draft.content);
  expect(within(workspace).queryByRole("textbox")).toBeNull();
  expect(within(workspace).getByRole("button", { name: "Edit", exact: true })).toBeTruthy();
  expect(within(workspace).getByRole("button", { name: "Approve job description" })).toBeTruthy();
  expect(within(workspace).queryByRole("button", { name: /Open assistant|Continue with assistant/ })).toBeNull();
  expect(chat.getAttribute("aria-hidden")).toBe("true");
  expect(workspace.getAttribute("data-workflow-ready")).toBe("false");
  expect(HTMLElement.prototype.scrollIntoView).not.toHaveBeenCalled();
  await act(async () => finishLayout([draft]));
  await waitFor(() => expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalled());
  expect((vi.mocked(HTMLElement.prototype.scrollIntoView).mock.contexts.at(-1) as HTMLElement).id).toBe("job-description-review");
  expect(screen.queryByRole("button", { name: /Confirm requirements|Generate job description/ })).toBeNull();
  expect(vi.mocked(apiRequest).mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(1);
});

it("asks for missing role details and drafts on the reply without separate requirements or generation steps", async () => {
  let turns = 0;
  vi.mocked(apiRequest).mockImplementation(async (path, options) => {
    if (path === "/job-descriptions") return [];
    if (path === "/supervisor/chat" && options?.method === "POST") {
      turns++;
      return { ...result, route: "generate_job_description", phase: turns === 1 ? "job_details" : "job_description_draft",
        job_description: turns === 1 ? null : draft,
        messages: [{ role: "assistant", content: turns === 1 ? "No suitable reference found. What skills and duties should this job include?" : "Your draft is ready.", outcome: "info" }] };
    }
    throw new Error(`Unexpected synthetic request: ${path}`);
  });
  render(<MemoryRouter initialEntries={["/interviewer/jobs"]}><App /></MemoryRouter>);
  await screen.findByRole("heading", { name: "Create your first job" });
  fireEvent.click(screen.getByRole("button", { name: "Assistant", exact: true }));
  const chat = screen.getByRole("dialog", { name: "HireSense supervisor" });
  const input = within(chat).getByRole("textbox", { name: "Message HireSense assistant" });
  fireEvent.change(input, { target: { value: "I want to hire a frontend engineer" } });
  fireEvent.click(within(chat).getByRole("button", { name: "Send message" }));
  await within(chat).findByText(/What skills and duties/);
  expect(screen.queryByLabelText("Job description")).toBeNull();
  fireEvent.change(input, { target: { value: "Use React to build accessible interfaces." } });
  fireEvent.click(within(chat).getByRole("button", { name: "Send message" }));
  await screen.findByRole("heading", { name: "Review your job description" });
  expect(turns).toBe(2);
  expect(screen.queryByRole("button", { name: /Confirm requirements|Generate job description/ })).toBeNull();
  const sent = vi.mocked(apiRequest).mock.calls.filter(([path]) => path === "/supervisor/chat");
  expect(JSON.parse(sent[1][1]?.body as string).session_id).toBe("synthetic-session");
});
