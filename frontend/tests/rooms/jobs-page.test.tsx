import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { JobDescriptionPage } from "../../src/pages/JobDescriptionPage";
import { apiRequest } from "../../src/api/apiClient";
import type { JobDescriptionResponse, SupervisorChatResponse } from "../../src/types";
import { selectOption } from "./selectHelpers";

const supervisor = vi.hoisted(() => ({ response: undefined as SupervisorChatResponse | undefined, loading: false, open: false,
  setOpen: vi.fn(), startNewWorkflow: vi.fn(), sendMessage: vi.fn(), addTaskMessage: vi.fn(), setSelectedJobDescriptionId: vi.fn(), refreshVersion: 0 }));
vi.mock("../../src/components/assistant/SupervisorProvider", () => ({ useSupervisor: () => supervisor }));
vi.mock("../../src/api/apiClient", () => ({ apiRequest: vi.fn() }));
vi.mock("../../src/components/jobs/DiscordJobPostPanel", () => ({ DiscordJobPostPanel: ({ jobDescription }: { jobDescription: JobDescriptionResponse }) => <section aria-label="Discord publication controls">Publishing for {jobDescription.title}</section> }));

function job(id = 1, status: JobDescriptionResponse["status"] = "approved"): JobDescriptionResponse {
  return { id, title: id === 1 ? "Senior Machine Learning Engineer for Document Intelligence" : `Engineer ${id}`, status, version: 1, content: `Saved description ${id}.\nResponsibilities and requirements.`,
    requirement_profile_id: 7, created_by_user_id: 1, created_at: "2026-10-19T07:00:00Z", updated_at: "2026-10-19T07:00:00Z", source_references: [],
    structured_content: { title: "Engineer", summary: "Summary", responsibilities: ["Build products"], required_skills: [], preferred_skills: [], qualifications: [], selection_criteria: [], experience_requirement: "3 years" } };
}
function response(): SupervisorChatResponse {
  return { session_id: "synthetic", phase: "requirement_confirmation", route: "requirements", assistant_message: "Confirm the role", outcome: "info", messages: [], requirement_profile_id: null,
    requirement_state: { profile: { title: "New engineer", summary: "Build products", required_skills: [{ name: "React", details: null }], preferred_skills: [], qualifications: [], min_years_experience: 3, selection_criteria: [] }, missing_fields: [], knowledge_status: "empty", proposal_ready: true, source_references: [] },
    job_description: null, job_posting: null, refresh_required: false, sync_result: null, screening_batch: null };
}
let jobs: JobDescriptionResponse[];
beforeEach(() => {
  vi.clearAllMocks();
  jobs = [job(), job(2, "draft"), job(3, "archived")];
  supervisor.response = undefined; supervisor.loading = false; supervisor.open = false; supervisor.refreshVersion = 0;
  vi.mocked(apiRequest).mockImplementation(async (path, options) => {
    if (path === "/job-descriptions" && !options?.method) return jobs;
    if (path === "/knowledge/documents") return [];
    if (options?.method === "DELETE") return undefined;
    throw new Error(`Unexpected synthetic request: ${path}`);
  });
  vi.spyOn(window, "confirm").mockReturnValue(true);
});
afterEach(() => vi.restoreAllMocks());

it("puts full job titles and clear actions in cards without technical labels or empty work panels", async () => {
  render(<JobDescriptionPage />);
  expect(await screen.findByRole("list", { name: "Saved job cards" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Jobs", exact: true })).toBeTruthy();
  expect(screen.getByText(jobs[0].title)).toBeTruthy();
  expect(screen.getByRole("button", { name: `View job: ${jobs[0].title}` })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Edit draft: Engineer 2" })).toBeTruthy();
  expect(screen.getAllByText("Updated 19 Oct 2026")).toHaveLength(3);
  expect(screen.queryByText(/F1|RAG|JD agent/)).toBeNull();
  expect(screen.queryByRole("region", { name: "Current job workspace" })).toBeNull();
  expect(screen.queryByRole("textbox", { name: "Job description" })).toBeNull();
  expect(vi.mocked(apiRequest).mock.calls.some(([, options]) => options?.method)).toBe(false);
  expect(supervisor.sendMessage).not.toHaveBeenCalled();
});

it("searches and filters saved jobs with a useful no-results state", async () => {
  render(<JobDescriptionPage />); await screen.findByRole("list", { name: "Saved job cards" });
  fireEvent.change(screen.getByRole("searchbox", { name: "Search jobs" }), { target: { value: "Engineer 2" } });
  expect(within(screen.getByRole("list", { name: "Saved job cards" })).getAllByRole("listitem")).toHaveLength(1);
  selectOption("Job status", "Approved");
  expect(screen.getByText("No jobs match your search.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
  expect(within(screen.getByRole("list", { name: "Saved job cards" })).getAllByRole("listitem")).toHaveLength(3);
  selectOption("Job status", "Archived");
  expect(screen.getByText("Engineer 3")).toBeTruthy();
  expect(screen.queryByText("Engineer 2")).toBeNull();
});

it("paginates jobs and resets the page when filtering", async () => {
  jobs = Array.from({ length: 23 }, (_, index) => job(index + 1));
  render(<JobDescriptionPage />); await screen.findByRole("list", { name: "Saved job cards" });
  expect(screen.getByText("1–10 of 23 jobs")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(screen.getByText("11–20 of 23 jobs")).toBeTruthy();
  expect(screen.getByText("Engineer 11")).toBeTruthy();
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Engineer 23" } });
  expect(screen.getByText("Page 1 of 1")).toBeTruthy();
  expect(screen.getByText("1–1 of 1 jobs")).toBeTruthy();
});

it("opens an approved job in a readable modal and restores focus when closed", async () => {
  render(<JobDescriptionPage />);
  const button = await screen.findByRole("button", { name: `View job: ${jobs[0].title}` });
  button.focus(); fireEvent.click(button);
  const modal = screen.getByRole("dialog", { name: "Job details" });
  expect(within(modal).getByText(/Saved description 1/).textContent).toBe(jobs[0].content);
  expect(within(modal).queryByRole("textbox")).toBeNull();
  expect(within(modal).getByRole("region", { name: "Discord publication controls" })).toBeTruthy();
  fireEvent.click(within(modal).getByRole("button", { name: "Close preview" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(document.activeElement).toBe(button);
});

it("saves draft edits explicitly and requires saving before approval", async () => {
  vi.mocked(apiRequest).mockImplementation(async (path, options) => {
    if (path === "/job-descriptions") return jobs;
    if (path === "/job-descriptions/2" && options?.method === "PATCH") return { ...jobs[1], ...JSON.parse(options.body as string) };
    if (path === "/job-descriptions/2/approve" && options?.method === "POST") return { ...jobs[1], title: "Updated engineer", status: "approved" };
    throw new Error(`Unexpected synthetic request: ${path}`);
  });
  render(<JobDescriptionPage />); fireEvent.click(await screen.findByRole("button", { name: "Edit draft: Engineer 2" }));
  const modal = screen.getByRole("dialog", { name: "Edit job draft" });
  fireEvent.change(within(modal).getByLabelText("Job title"), { target: { value: "Updated engineer" } });
  expect((within(modal).getByRole("button", { name: "Approve job description" }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(within(modal).getByRole("button", { name: "Save changes" }));
  await within(modal).findByText("Changes saved.");
  expect(apiRequest).toHaveBeenCalledWith("/job-descriptions/2", { method: "PATCH", body: JSON.stringify({ title: "Updated engineer", content: jobs[1].content }) });
  fireEvent.click(within(modal).getByRole("button", { name: "Approve job description" }));
  await waitFor(() => expect(apiRequest).toHaveBeenCalledWith("/job-descriptions/2/approve", { method: "POST" }));
  expect(supervisor.sendMessage).not.toHaveBeenCalled();
  expect(supervisor.setSelectedJobDescriptionId).toHaveBeenCalledWith(2);
});

it("protects unsaved draft edits when closing or starting a new job", async () => {
  render(<JobDescriptionPage />); fireEvent.click(await screen.findByRole("button", { name: "Edit draft: Engineer 2" }));
  fireEvent.change(screen.getByLabelText("Job title"), { target: { value: "Unsaved title" } });
  vi.mocked(window.confirm).mockReturnValue(false);
  fireEvent.click(screen.getByRole("button", { name: "Close preview" }));
  expect(screen.getByRole("dialog")).toBeTruthy();
  expect((screen.getByLabelText("Job title") as HTMLInputElement).value).toBe("Unsaved title");
  vi.mocked(window.confirm).mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: "Close preview" }));
  fireEvent.click(screen.getByRole("button", { name: "Edit draft: Engineer 2" }));
  expect((screen.getByLabelText("Job title") as HTMLInputElement).value).toBe("Engineer 2");
});

it("creates a separate draft from an approved job only on request", async () => {
  vi.mocked(apiRequest).mockImplementation(async (path, options) => {
    if (path === "/job-descriptions") return jobs;
    if (path === "/job-descriptions/1/revise" && options?.method === "POST") return { ...jobs[0], id: 4, status: "draft", version: 2 };
    throw new Error(`Unexpected synthetic request: ${path}`);
  });
  render(<JobDescriptionPage />);
  const button = await screen.findByRole("button", { name: `New draft: ${jobs[0].title}` });
  fireEvent.click(button); fireEvent.click(button);
  await screen.findByRole("dialog", { name: "Edit job draft" });
  expect(vi.mocked(apiRequest).mock.calls.filter(([path]) => path === "/job-descriptions/1/revise")).toHaveLength(1);
  expect(jobs[0].status).toBe("approved");
  expect(within(screen.getByRole("dialog", { name: "Edit job draft" })).getByText("Version 2")).toBeTruthy();
});

it("requires confirmation before deleting and leaves published posts alone", async () => {
  render(<JobDescriptionPage />);
  const button = await screen.findByRole("button", { name: "Delete job: Engineer 2" });
  vi.mocked(window.confirm).mockReturnValue(false); fireEvent.click(button);
  expect(vi.mocked(apiRequest).mock.calls.some(([, options]) => options?.method === "DELETE")).toBe(false);
  vi.mocked(window.confirm).mockReturnValue(true); fireEvent.click(button);
  await waitFor(() => expect(screen.queryByRole("button", { name: "Edit draft: Engineer 2" })).toBeNull());
  expect(apiRequest).toHaveBeenCalledWith("/job-descriptions/2", { method: "DELETE" });
  expect(vi.mocked(apiRequest).mock.calls.some(([path]) => path.includes("publish"))).toBe(false);
});

it("keeps assistant conversations available without a separate creation button", async () => {
  supervisor.response = response();
  render(<JobDescriptionPage />); await screen.findByRole("list", { name: "Saved job cards" });
  expect(screen.queryByRole("button", { name: "Create with assistant" })).toBeNull();
  expect(supervisor.startNewWorkflow).not.toHaveBeenCalled();
  expect(screen.queryByText("React")).toBeNull();
  expect(screen.queryByRole("button", { name: "Confirm requirements" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Generate job description" })).toBeNull();
  expect(screen.queryByRole("button", { name: /Open assistant|Continue with assistant/ })).toBeNull();
  expect(supervisor.sendMessage).not.toHaveBeenCalled();
});

it("recovers from a failed job list request", async () => {
  vi.mocked(apiRequest).mockRejectedValueOnce(new Error("Jobs unavailable."));
  render(<JobDescriptionPage />);
  expect((await screen.findByRole("alert")).textContent).toContain("Jobs unavailable");
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByRole("list", { name: "Saved job cards" })).toBeTruthy();
});

it("offers a helpful empty state instead of empty requirement and draft panels", async () => {
  jobs = []; render(<JobDescriptionPage />);
  expect(await screen.findByRole("heading", { name: "Create your first job" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Get started" })).toBeTruthy();
  expect(screen.queryByRole("region", { name: "Current job workspace" })).toBeNull();
});

it("loads references on demand and uploads a selected PDF only on submission", async () => {
  vi.mocked(apiRequest).mockImplementation(async (path, options) => {
    if (path === "/job-descriptions") return jobs;
    if (path === "/knowledge/documents") return [];
    if (path === "/knowledge/documents/upload" && options?.method === "POST") return { id: 1, title: "Backend reference", metadata_json: { page_count: 2 } };
    throw new Error(`Unexpected synthetic request: ${path}`);
  });
  render(<JobDescriptionPage />); await screen.findByRole("list", { name: "Saved job cards" });
  expect(apiRequest).not.toHaveBeenCalledWith("/knowledge/documents");
  fireEvent.click(screen.getByRole("button", { name: "Reference documents" }));
  const modal = screen.getByRole("dialog", { name: "Reference documents" });
  await within(modal).findByText("No reference documents yet. You can still create a job without them.");
  fireEvent.change(within(modal).getByLabelText(/Document title/), { target: { value: "Backend reference" } });
  const file = new File(["synthetic PDF"], "synthetic.pdf", { type: "application/pdf" });
  fireEvent.change(within(modal).getByLabelText("Job description PDF"), { target: { files: [file] } });
  fireEvent.click(within(modal).getByRole("button", { name: "Upload PDF" }));
  expect(await within(modal).findByText(/Added “Backend reference”/)).toBeTruthy();
  const request = vi.mocked(apiRequest).mock.calls.find(([path]) => path === "/knowledge/documents/upload")!;
  expect((request[1]?.body as FormData).get("title")).toBe("Backend reference");
  expect((request[1]?.body as FormData).get("file")).toBe(file);
  expect(supervisor.sendMessage).not.toHaveBeenCalled();
});

it("keeps failed saves retryable without losing typed edits", async () => {
  render(<JobDescriptionPage />); fireEvent.click(await screen.findByRole("button", { name: "Edit draft: Engineer 2" }));
  fireEvent.change(screen.getByLabelText("Job title"), { target: { value: "Keep my changes" } });
  vi.mocked(apiRequest).mockRejectedValueOnce(new Error("Save unavailable."));
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
  expect((await screen.findByRole("alert")).textContent).toContain("Save unavailable");
  expect((screen.getByLabelText("Job title") as HTMLInputElement).value).toBe("Keep my changes");
  expect((screen.getByRole("button", { name: "Save changes" }) as HTMLButtonElement).disabled).toBe(false);
});

it("previews a generated draft and opens manual editing only through Edit", async () => {
  supervisor.response = { ...response(), phase: "job_description_draft", job_description: job(4, "draft") };
  render(<JobDescriptionPage />);
  const workspace = await screen.findByRole("region", { name: "Current job workspace" });
  expect(within(workspace).getByRole("article", { name: "Job description preview" })).toBeTruthy();
  expect(within(workspace).queryByRole("textbox")).toBeNull();
  expect(within(workspace).queryByRole("button", { name: /Open assistant|Continue with assistant/ })).toBeNull();
  fireEvent.click(within(workspace).getByRole("button", { name: "Edit", exact: true }));
  expect((within(workspace).getByLabelText("Job title") as HTMLInputElement).value).toBe("Engineer 4");
  expect(document.activeElement).toBe(within(workspace).getByLabelText("Job title"));
  expect(within(workspace).getByRole("button", { name: "Cancel" })).toBeTruthy();
  expect(supervisor.sendMessage).not.toHaveBeenCalled();
});

it("confirms cancelling unsaved edits, restores saved text and returns focus to Edit", async () => {
  render(<JobDescriptionPage />); fireEvent.click(await screen.findByRole("button", { name: "Edit draft: Engineer 2" }));
  fireEvent.change(screen.getByLabelText("Job title"), { target: { value: "Unsaved title" } });
  fireEvent.change(screen.getByLabelText("Job description"), { target: { value: "Unsaved description" } });
  vi.mocked(window.confirm).mockReturnValue(false);
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect((screen.getByLabelText("Job title") as HTMLInputElement).value).toBe("Unsaved title");
  vi.mocked(window.confirm).mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  const modal = screen.getByRole("dialog", { name: "Job details" });
  expect(within(modal).queryByRole("textbox")).toBeNull();
  expect(within(modal).getByText(/Saved description 2/).textContent).toBe(jobs[1].content);
  expect(document.activeElement).toBe(within(modal).getByRole("button", { name: "Edit", exact: true }));
  fireEvent.click(within(modal).getByRole("button", { name: "Edit", exact: true }));
  expect((screen.getByLabelText("Job title") as HTMLInputElement).value).toBe("Engineer 2");
  expect(vi.mocked(apiRequest).mock.calls.some(([, options]) => options?.method)).toBe(false);
});

it("returns to the updated formatted preview after saving and supports further edits", async () => {
  vi.mocked(apiRequest).mockImplementation(async (path, options) => {
    if (path === "/job-descriptions") return jobs;
    if (path === "/job-descriptions/2" && options?.method === "PATCH") return { ...jobs[1], ...JSON.parse(options.body as string) };
    throw new Error(`Unexpected synthetic request: ${path}`);
  });
  render(<JobDescriptionPage />); fireEvent.click(await screen.findByRole("button", { name: "Edit draft: Engineer 2" }));
  fireEvent.change(screen.getByLabelText("Job description"), { target: { value: "## Responsibilities\n- Build accessible interfaces" } });
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
  await screen.findByText("Changes saved.");
  const modal = screen.getByRole("dialog", { name: "Job details" });
  expect(within(modal).queryByRole("textbox")).toBeNull();
  expect(within(modal).getByRole("heading", { name: "Responsibilities" })).toBeTruthy();
  expect(within(modal).getByRole("listitem").textContent).toBe("Build accessible interfaces");
  fireEvent.click(within(modal).getByRole("button", { name: "Edit", exact: true }));
  expect((screen.getByLabelText("Job description") as HTMLTextAreaElement).value).toContain("## Responsibilities");
});

it("keeps archived jobs read-only and never offers revision or publishing controls", async () => {
  render(<JobDescriptionPage />);
  fireEvent.click(await screen.findByRole("button", { name: "View job: Engineer 3" }));
  const modal = screen.getByRole("dialog", { name: "Job details" });
  expect(within(modal).getByText("Archived")).toBeTruthy();
  expect(within(modal).queryByRole("textbox")).toBeNull();
  expect(within(modal).queryByRole("button", { name: "Edit as new draft" })).toBeNull();
  expect(within(modal).queryByRole("region", { name: "Discord publication controls" })).toBeNull();
});

it("requires confirmation for reference removal and can recover from a failed reference load", async () => {
  let referencesLoaded = false;
  vi.mocked(apiRequest).mockImplementation(async (path, options) => {
    if (path === "/job-descriptions") return jobs;
    if (path === "/knowledge/documents") {
      if (!referencesLoaded) { referencesLoaded = true; throw new Error("Synthetic unavailable"); }
      return [{ id: 9, title: "Synthetic reference", metadata_json: {} }];
    }
    if (path === "/knowledge/documents/9" && options?.method === "DELETE") return undefined;
    throw new Error(`Unexpected synthetic request: ${path}`);
  });
  render(<JobDescriptionPage />); await screen.findByRole("list", { name: "Saved job cards" });
  fireEvent.click(screen.getByRole("button", { name: "Reference documents" }));
  const modal = screen.getByRole("dialog", { name: "Reference documents" });
  await within(modal).findByRole("alert");
  fireEvent.click(within(modal).getByRole("button", { name: "Reload documents" }));
  const remove = await within(modal).findByRole("button", { name: "Remove reference: Synthetic reference" });
  vi.mocked(window.confirm).mockReturnValue(false); fireEvent.click(remove);
  expect(vi.mocked(apiRequest).mock.calls.some(([, options]) => options?.method === "DELETE")).toBe(false);
  vi.mocked(window.confirm).mockReturnValue(true); fireEvent.click(remove);
  await waitFor(() => expect(within(modal).queryByText("Synthetic reference")).toBeNull());
  expect(apiRequest).toHaveBeenCalledWith("/knowledge/documents/9", { method: "DELETE" });
});

it("keeps card view and only the clearly named manual creation button", async () => {
  render(<JobDescriptionPage />);
  const cards = await screen.findByRole("list", { name: "Saved job cards" });
  expect(within(cards).getAllByRole("article")).toHaveLength(3);
  expect(screen.queryByRole("table")).toBeNull();
  expect(screen.getByRole("button", { name: "Create job description manually" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Create with assistant" })).toBeNull();
});

it("saves a manual job with screening requirements, then opens it for review without using the chatbot", async () => {
  vi.mocked(apiRequest).mockImplementation(async (path, options) => {
    if (path === "/job-descriptions") return jobs;
    if (path === "/job-descriptions/manual" && options?.method === "POST") return { ...job(10, "draft"), title: "Manual frontend role", content: "Build accessible React apps." };
    throw new Error(`Unexpected synthetic request: ${path}`);
  });
  render(<JobDescriptionPage />); await screen.findByRole("list", { name: "Saved job cards" });
  fireEvent.click(screen.getByRole("button", { name: "Create job description manually" }));
  const modal = screen.getByRole("dialog", { name: "Create job manually" });
  fireEvent.change(within(modal).getByLabelText(/Job title/), { target: { value: " Manual frontend role " } });
  fireEvent.change(within(modal).getByLabelText(/Job description/), { target: { value: "Build accessible React apps." } });
  fireEvent.change(within(modal).getByLabelText(/Required skills/), { target: { value: "React\nTypeScript\nReact\n" } });
  fireEvent.change(within(modal).getByLabelText(/Qualifications/), { target: { value: "Computer Science degree" } });
  fireEvent.change(within(modal).getByLabelText(/Minimum experience/), { target: { value: "3" } });
  const save = within(modal).getByRole("button", { name: "Save draft" });
  fireEvent.click(save); fireEvent.click(save);
  await screen.findByRole("dialog", { name: "Job details" });
  expect(apiRequest).toHaveBeenCalledWith("/job-descriptions/manual", { method: "POST", body: JSON.stringify({
    title: "Manual frontend role", content: "Build accessible React apps.", required_skills: [{ name: "React", details: null }, { name: "TypeScript", details: null }],
    preferred_skills: [], qualifications: [{ name: "Computer Science degree", details: null }], min_years_experience: 3,
  }) });
  expect(vi.mocked(apiRequest).mock.calls.filter(([path]) => path === "/job-descriptions/manual")).toHaveLength(1);
  expect(supervisor.sendMessage).not.toHaveBeenCalled();
  expect(supervisor.startNewWorkflow).not.toHaveBeenCalled();
});

it("keeps a failed manual creation retryable without losing text", async () => {
  render(<JobDescriptionPage />); await screen.findByRole("list", { name: "Saved job cards" });
  fireEvent.click(screen.getByRole("button", { name: "Create job description manually" }));
  const modal = screen.getByRole("dialog", { name: "Create job manually" });
  const save = within(modal).getByRole("button", { name: "Save draft" });
  expect((save as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(within(modal).getByLabelText(/Job title/), { target: { value: "Manual role" } });
  fireEvent.change(within(modal).getByLabelText(/Job description/), { target: { value: "Keep this text" } });
  fireEvent.change(within(modal).getByLabelText(/Required skills/), { target: { value: "Python" } });
  vi.mocked(apiRequest).mockRejectedValueOnce(new Error("Synthetic save error"));
  fireEvent.click(save);
  expect((await within(modal).findByRole("alert")).textContent).toContain("Synthetic save error");
  expect((within(modal).getByLabelText(/Job description/) as HTMLTextAreaElement).value).toBe("Keep this text");
  expect((save as HTMLButtonElement).disabled).toBe(false);
});

it("asks before discarding manual input and cancels without creating anything", async () => {
  render(<JobDescriptionPage />); await screen.findByRole("list", { name: "Saved job cards" });
  fireEvent.click(screen.getByRole("button", { name: "Create job description manually" }));
  const modal = screen.getByRole("dialog", { name: "Create job manually" });
  fireEvent.change(within(modal).getByLabelText(/Job title/), { target: { value: "Unsaved manual role" } });
  vi.mocked(window.confirm).mockReturnValue(false);
  fireEvent.click(within(modal).getByRole("button", { name: "Cancel" }));
  expect(screen.getByRole("dialog", { name: "Create job manually" })).toBeTruthy();
  vi.mocked(window.confirm).mockReturnValue(true);
  fireEvent.click(within(modal).getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(vi.mocked(apiRequest).mock.calls.some(([, options]) => options?.method === "POST")).toBe(false);
});
