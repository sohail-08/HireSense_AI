import React from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { CandidatesPage } from "../../src/pages/CandidatesPage";
import { apiBlob, apiRequest } from "../../src/api/apiClient";
import { selectOption } from "./selectHelpers";

vi.mock("../../src/api/apiClient", () => ({ apiRequest: vi.fn(), apiBlob: vi.fn(), ApiError: class extends Error {} }));
const supervisor = vi.hoisted(() => ({ refreshVersion: 0, response: undefined }));
vi.mock("../../src/components/assistant/SupervisorProvider", () => ({ useSupervisor: () => supervisor }));
vi.mock("../../src/components/common/applicationNotificationEvents", () => ({ notifyApplicationsChanged: vi.fn() }));

const config = { configured: true, form_url: "https://forms.example.test/apply", job_column: "Job Posting", missing_settings: [] };
const cv = { id: 9, original_filename: "Synthetic CV.pdf", mime_type: "application/pdf", file_size_bytes: 44000 };
const applications = [
  { id: 1, job_posting_id: 7, job_title: "Frontend Engineer", status: "received", submitted_at: "2026-10-20T04:00:00Z",
    candidate: { id: 11, name: "Ada Candidate", email: "ada@example.test", phone: "123456", location: "Dhaka", linkedin_url: null, portfolio_url: null }, cv_documents: [cv] },
  { id: 2, job_posting_id: 8, job_title: "Frontend Engineer", status: "reviewed", submitted_at: "2026-10-19T04:00:00Z",
    candidate: { id: 12, name: "Grace Candidate", email: "grace@example.test", phone: "987654", location: null, linkedin_url: null, portfolio_url: null }, cv_documents: [] },
];
let items = applications;

function respond(path: string, options?: RequestInit): any {
  if (path === "/candidates/google-forms/configuration") return config;
  if (path === "/candidates/job-postings") return [7, 8].map(id => ({ id, title: "Frontend Engineer", published_at: id === 7 ? "2026-10-20T04:00:00Z" : "2026-10-19T04:00:00Z" }));
  if (path === "/candidates/applications") return items;
  if (path === "/candidates/applications/1" && options?.method === "DELETE") return null;
  if (path === "/candidates/applications/bulk-delete" && options?.method === "POST") {
    const ids = JSON.parse(options.body as string).application_ids;
    return { deleted_application_ids: ids, deleted_count: ids.length };
  }
  throw new Error("Unexpected request: " + path);
}
function openPage() { return render(<MemoryRouter><CandidatesPage /></MemoryRouter>); }
async function inspect() { fireEvent.click(await screen.findByRole("button", { name: "Inspect Ada Candidate" })); return screen.getByRole("dialog"); }

beforeEach(() => {
  items = applications;
  vi.mocked(apiRequest).mockReset(); vi.mocked(apiBlob).mockReset();
  vi.mocked(apiRequest).mockImplementation(async (path, options) => respond(path, options));
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function(this: HTMLDialogElement) { this.setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: function(this: HTMLDialogElement) { this.removeAttribute("open"); } });
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:synthetic-cv") });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
});

it("shows numbered candidates without setup, initials or a CV column", async () => {
  openPage();
  expect(await screen.findByText("Ada Candidate")).toBeTruthy();
  const table = screen.getByRole("table");
  expect(table.textContent).not.toContain("Posting #");
  expect(within(table).getAllByRole("row")).toHaveLength(3);
  expect(screen.queryByText(/F1|CV collection|Collected applications/)).toBeNull();
  expect(screen.queryByText("Application collection setup")).toBeNull();
  expect(within(table).queryByRole("columnheader", { name: "CV" })).toBeNull();
  expect(screen.queryByText("AC")).toBeNull();
  expect(within(within(table).getAllByRole("row")[1]).getAllByRole("cell")[0].textContent).toBe("1");
  expect(within(within(table).getAllByRole("row")[2]).getAllByRole("cell")[0].textContent).toBe("2");
  expect(screen.getByRole("button", { name: "Sync responses" })).toBeTruthy();
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("filters identical job titles by posting ID and combines that filter with search", async () => {
  openPage(); await screen.findByText("Ada Candidate");
  selectOption("Job posting", /Published 19 Oct 2026/);
  expect(screen.queryByText("Ada Candidate")).toBeNull();
  expect(screen.getByText("Grace Candidate")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Search candidates"), { target: { value: "ada@example.test" } });
  expect(screen.getByText("No candidates match your filters")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
  expect(screen.getByText("Ada Candidate")).toBeTruthy();
});

it("loads saved candidates even when form setup fails", async () => {
  vi.mocked(apiRequest).mockImplementation(async (path, options) => {
    if (path.includes("configuration")) throw new Error("Setup unavailable");
    return respond(path, options);
  });
  openPage();
  expect(await screen.findByText("Ada Candidate")).toBeTruthy();
  expect((screen.getByRole("button", { name: "Sync responses" }) as HTMLButtonElement).disabled).toBe(true);
});

it("opens details in a top-level modal and restores focus after closing", async () => {
  openPage();
  const trigger = await screen.findByRole("button", { name: "Inspect Ada Candidate" }); trigger.focus();
  fireEvent.click(trigger);
  const modal = screen.getByRole("dialog");
  expect(modal.textContent).not.toContain("Posting #");
  expect(modal.parentElement).toBe(document.body);
  expect(within(modal).getByText("123456")).toBeTruthy();
  expect(within(modal).queryByText("Location")).toBeNull();
  expect(within(modal).queryByText("Dhaka")).toBeNull();
  expect(within(modal).getByText("Synthetic CV.pdf")).toBeTruthy();
  expect(document.body.style.overflow).toBe("hidden");
  fireEvent.click(within(modal).getByRole("button", { name: "Close candidate details" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(document.activeElement).toBe(trigger);
  expect(document.body.style.overflow).not.toBe("hidden");
});

it("opens an authenticated PDF blob without putting a token or storage path in a URL", async () => {
  const popup = { opener: {}, document: { title: "", body: { textContent: "" } }, closed: false, location: { replace: vi.fn() }, close: vi.fn() };
  vi.spyOn(window, "open").mockReturnValue(popup as unknown as Window);
  vi.mocked(apiBlob).mockResolvedValue(new Blob(["synthetic"], { type: "application/pdf" }));
  openPage(); const modal = await inspect();
  fireEvent.click(within(modal).getByRole("button", { name: "Open CV" }));
  await waitFor(() => expect(popup.location.replace).toHaveBeenCalledWith("blob:synthetic-cv"));
  expect(apiBlob).toHaveBeenCalledWith("/candidates/applications/1/cvs/9", { signal: expect.any(AbortSignal) });
  expect(popup.opener).toBeNull();
});

it("shows a useful error if the browser blocks the CV window", async () => {
  vi.spyOn(window, "open").mockReturnValue(null);
  openPage(); const modal = await inspect();
  fireEvent.click(within(modal).getByRole("button", { name: "Open CV" }));
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", expect.stringContaining("use Download instead"));
  expect(apiBlob).not.toHaveBeenCalled();
});

it("cancels an unfinished CV request when the modal closes", async () => {
  const popup = { opener: {}, document: { title: "", body: { textContent: "" } }, closed: false, location: { replace: vi.fn() }, close: vi.fn() };
  vi.spyOn(window, "open").mockReturnValue(popup as unknown as Window);
  let finish!: (value: Blob) => void;
  vi.mocked(apiBlob).mockReturnValue(new Promise(resolve => { finish = resolve; }));
  openPage(); const modal = await inspect();
  fireEvent.click(within(modal).getByRole("button", { name: "Open CV" }));
  const signal = vi.mocked(apiBlob).mock.calls[0][1]?.signal;
  fireEvent.click(within(modal).getByRole("button", { name: "Done" }));
  expect(signal?.aborted).toBe(true); expect(popup.close).toHaveBeenCalled();
  finish(new Blob(["synthetic"]));
  await waitFor(() => expect(popup.location.replace).not.toHaveBeenCalled());
});

it("requires explicit deletion confirmation and removes the row after success", async () => {
  openPage(); const modal = await inspect();
  fireEvent.click(within(modal).getByRole("button", { name: "Delete application" }));
  expect(vi.mocked(apiRequest).mock.calls.some(([, options]) => options?.method === "DELETE")).toBe(false);
  fireEvent.click(within(modal).getByRole("button", { name: "Delete permanently" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(screen.queryByRole("button", { name: "Inspect Ada Candidate" })).toBeNull();
  expect(apiRequest).toHaveBeenCalledWith("/candidates/applications/1", { method: "DELETE" });
  await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText("Search candidates")));
});

it("keeps the candidate and shows the error when deletion fails", async () => {
  vi.mocked(apiRequest).mockImplementation(async (path, options) => {
    if (options?.method === "DELETE") throw new Error("Could not delete this application. Please try again.");
    return respond(path, options);
  });
  openPage(); const modal = await inspect();
  fireEvent.click(within(modal).getByRole("button", { name: "Delete application" }));
  fireEvent.click(within(modal).getByRole("button", { name: "Delete permanently" }));
  expect(await within(modal).findByRole("alert")).toHaveProperty("textContent", expect.stringContaining("Could not delete"));
  expect(screen.getByRole("button", { name: "Inspect Ada Candidate" })).toBeTruthy();
});

it("downloads Word CVs without trying to open a browser PDF preview", async () => {
  items = [{ ...applications[0], cv_documents: [{ ...cv, original_filename: "Synthetic CV.docx", mime_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" }] }];
  vi.mocked(apiBlob).mockResolvedValue(new Blob(["synthetic word content"]));
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  try {
    openPage(); const modal = await inspect();
    expect(within(modal).queryByRole("button", { name: "Open CV" })).toBeNull();
    fireEvent.click(within(modal).getByRole("button", { name: "Download" }));
    await waitFor(() => expect(click).toHaveBeenCalledOnce());
    expect(apiBlob).toHaveBeenCalledWith("/candidates/applications/1/cvs/9?download=true", { signal: expect.any(AbortSignal) });
  } finally { click.mockRestore(); }
});

it("closes the native modal on Escape/cancel and rejects unsafe profile links", async () => {
  items = [{ ...applications[0], candidate: { ...applications[0].candidate, linkedin_url: "javascript:alert(1)" as any } }];
  openPage(); const modal = await inspect();
  expect(within(modal).getByText("Link unavailable")).toBeTruthy();
  expect(within(modal).queryByRole("link", { name: "Open linkedin" })).toBeNull();
  fireEvent(modal, new Event("cancel", { cancelable: true }));
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("paginates the table and resets the page when a filter changes", async () => {
  items = Array.from({ length: 12 }, (_, index) => ({ ...applications[0], id: index + 1, candidate: { ...applications[0].candidate, name: `Applicant ${index + 1}` } }));
  openPage(); await screen.findByText("Applicant 1");
  expect(screen.queryByText("Applicant 11")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(screen.getByText("Applicant 11")).toBeTruthy();
  expect(within(screen.getByRole("table")).getAllByRole("row")[1].children[0].textContent).toBe("11");
  fireEvent.change(screen.getByLabelText("Search candidates"), { target: { value: "Applicant 1" } });
  expect(screen.getByText("Applicant 1")).toBeTruthy();
  expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(true);
});

it("deletes an individual row only after confirmation and can cancel safely", async () => {
  openPage(); await screen.findByText("Ada Candidate");
  fireEvent.click(screen.getByRole("button", { name: "Delete Ada Candidate" }));
  expect(screen.getByRole("dialog").textContent).toContain("Delete this application?");
  expect(vi.mocked(apiRequest).mock.calls.some(([path]) => path.includes("bulk-delete"))).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Delete Ada Candidate" }));
  fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(screen.queryByText("Ada Candidate")).toBeNull();
  expect(screen.getByText("Grace Candidate")).toBeTruthy();
  expect(apiRequest).toHaveBeenCalledWith("/candidates/applications/bulk-delete", { method: "POST", body: JSON.stringify({ application_ids: [1] }) });
});

it("keeps pagination visible and disables navigation for a single page or empty results", async () => {
  openPage(); await screen.findByText("Ada Candidate");
  expect(screen.getByText("Page 1 of 1")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Go to page 1" }).getAttribute("aria-current")).toBe("page");
  expect((screen.getByRole("button", { name: "Previous" }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(screen.getByLabelText("Search candidates"), { target: { value: "not found" } });
  expect(screen.getByText("0 applications · 2 total")).toBeTruthy();
  expect(screen.getByText("Page 1 of 1")).toBeTruthy();
});

it("changes page size, navigates directly and keeps numbering and selection consistent", async () => {
  items = Array.from({ length: 23 }, (_, index) => ({ ...applications[0], id: index + 1, candidate: { ...applications[0].candidate, name: `Applicant ${index + 1}` } }));
  openPage(); await screen.findByText("Applicant 1");
  selectOption("Candidates per page", "5");
  expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(6);
  expect(screen.getByText("1–5 of 23 applications")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Select candidates" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Select Applicant 1" }));
  fireEvent.click(screen.getByRole("button", { name: "Go to page 3" }));
  expect(screen.getByText("11–15 of 23 applications")).toBeTruthy();
  expect(screen.getByText("1 selected · up to 100")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Go to page 3" }).getAttribute("aria-current")).toBe("page");
  selectOption("Candidates per page", "20");
  expect(screen.getByText("Page 1 of 2")).toBeTruthy();
  expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(21);
  expect((screen.getByRole("checkbox", { name: "Select Applicant 1" }) as HTMLInputElement).checked).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(screen.getByText("21–23 of 23 applications")).toBeTruthy();
  expect(within(screen.getByRole("table")).getAllByRole("row")[1].children[1].textContent).toBe("21");
});

it("bounds page buttons for a large list and allows jumping to the last page", async () => {
  items = Array.from({ length: 101 }, (_, index) => ({ ...applications[0], id: index + 1, candidate: { ...applications[0].candidate, name: `Applicant ${index + 1}` } }));
  openPage(); await screen.findByText("Applicant 1");
  expect(screen.getAllByRole("button", { name: /Go to page/ }).length).toBeLessThanOrEqual(7);
  fireEvent.click(screen.getByRole("button", { name: "Go to page 11" }));
  expect(screen.getByText("101–101 of 101 applications")).toBeTruthy();
  expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(true);
  selectOption("Job posting", /Published 20 Oct 2026/);
  expect(screen.getByText("Page 1 of 11")).toBeTruthy();
});

it("moves back when deletion empties the last page", async () => {
  items = Array.from({ length: 11 }, (_, index) => ({ ...applications[0], id: index + 1, candidate: { ...applications[0].candidate, name: `Applicant ${index + 1}` } }));
  openPage(); await screen.findByText("Applicant 1");
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  fireEvent.click(screen.getByRole("button", { name: "Delete Applicant 11" }));
  fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(screen.getByText("Page 1 of 1")).toBeTruthy();
  expect(screen.getByText("Applicant 1")).toBeTruthy();
  expect(screen.getByText("1–10 of 10 applications")).toBeTruthy();
});

it("reveals selection controls on demand and deletes the group in one request", async () => {
  openPage(); await screen.findByText("Ada Candidate");
  expect(screen.queryByRole("checkbox")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Select candidates" }));
  expect((screen.getByRole("button", { name: "Delete selected" }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole("checkbox", { name: "Select Ada Candidate" }));
  expect((screen.getByRole("checkbox", { name: "Select all on this page" }) as HTMLInputElement).indeterminate).toBe(true);
  fireEvent.click(screen.getByRole("checkbox", { name: "Select Grace Candidate" }));
  fireEvent.click(screen.getByRole("button", { name: "Delete selected" }));
  expect(screen.getByRole("dialog").textContent).toContain("Delete 2 applications?");
  fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(screen.getByText("No candidates yet")).toBeTruthy();
  expect(vi.mocked(apiRequest).mock.calls.filter(([path]) => path.includes("bulk-delete"))).toHaveLength(1);
  expect(apiRequest).toHaveBeenCalledWith("/candidates/applications/bulk-delete", { method: "POST", body: JSON.stringify({ application_ids: [1, 2] }) });
});

it("selects only the current page, preserves selections across pages and clears them for new filters", async () => {
  items = Array.from({ length: 12 }, (_, index) => ({ ...applications[0], id: index + 1, candidate: { ...applications[0].candidate, name: `Applicant ${index + 1}` } }));
  openPage(); await screen.findByText("Applicant 1");
  fireEvent.click(screen.getByRole("button", { name: "Select candidates" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Select all on this page" }));
  expect(screen.getByText("10 selected · up to 100")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  expect((screen.getByRole("checkbox", { name: "Select Applicant 11" }) as HTMLInputElement).checked).toBe(false);
  fireEvent.click(screen.getByRole("checkbox", { name: "Select Applicant 11" }));
  expect(screen.getByText("11 selected · up to 100")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Search candidates"), { target: { value: "Applicant 12" } });
  expect(screen.getByText("0 selected · up to 100")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Cancel selection" }));
  expect(screen.queryByRole("checkbox")).toBeNull();
});

it("retains selected rows after a failed bulk deletion and prevents duplicate submission", async () => {
  let reject!: (reason: Error) => void;
  vi.mocked(apiRequest).mockImplementation(async (path, options) => {
    if (path.includes("bulk-delete")) return new Promise((_, fail) => { reject = fail; });
    return respond(path, options);
  });
  openPage(); await screen.findByText("Ada Candidate");
  fireEvent.click(screen.getByRole("button", { name: "Select candidates" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Select all on this page" }));
  fireEvent.click(screen.getByRole("button", { name: "Delete selected" }));
  fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
  expect((screen.getByRole("button", { name: "Deleting…" }) as HTMLButtonElement).disabled).toBe(true);
  reject(new Error("Could not delete applications"));
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Could not delete applications");
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByText("2 selected · up to 100")).toBeTruthy();
  expect(screen.getByText("Ada Candidate")).toBeTruthy();
});
