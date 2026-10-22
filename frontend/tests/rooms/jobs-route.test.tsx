import React from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
  vi.mocked(apiRequest).mockImplementation(async (path, options) => {
    if (path === "/job-descriptions") return [draft];
    if (path === "/job-descriptions/7/approve" && options?.method === "POST") return result.job_description;
    throw new Error(`Unexpected synthetic request: ${path}`);
  });
});

it("opens job creation through the real shared assistant without sending an automatic request", async () => {
  render(<MemoryRouter initialEntries={["/interviewer/jobs"]}><App /></MemoryRouter>);
  await screen.findByRole("list", { name: "Saved job cards" });
  fireEvent.click(screen.getByRole("button", { name: "Create with assistant", exact: true }));
  const chat = await screen.findByRole("dialog", { name: "HireSense supervisor" });
  expect(within(chat).getByRole("textbox", { name: "Message HireSense assistant" })).toBeTruthy();
  expect(screen.getByRole("region", { name: "Current job workspace" })).toBeTruthy();
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
