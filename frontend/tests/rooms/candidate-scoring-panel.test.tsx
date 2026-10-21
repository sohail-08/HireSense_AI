import React from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { CandidateScoringPanel } from "../../src/components/candidates/CandidateScoringPanel";
import { apiRequest } from "../../src/api/apiClient";

vi.mock("../../src/api/apiClient", () => ({ apiRequest: vi.fn() }));
const supervisor = vi.hoisted(() => ({ setSelectedApplicationIds: vi.fn() }));
vi.mock("../../src/components/assistant/SupervisorProvider", () => ({ useSupervisor: () => supervisor }));
vi.mock("../../src/components/interviews/InterviewSchedulingPanel", () => ({ InterviewSchedulingPanel: ({ selectedIds }: any) => <p>Interview selection: {selectedIds.join(",")}</p> }));

const categories = ["technical", "experience", "qualification"] as const;
const configuration = {
  requirement_version: "requirements-v1", formula_version: "formula-v1",
  category_weights: { technical: "50", experience: "30", qualification: "20" },
  requirements: categories.map((category, index) => ({ requirement_id: `r${index}`, name: ["React", "Relevant experience", "Degree"][index],
    category, classification: "required", weight: "1", evaluation_criterion: "CV evidence", requirement_version: "requirements-v1" })),
};
const result = { id: 42, application_id: 7, candidate_name: "Synthetic Candidate", rank: 1, review_state: "scored",
  final_score: "85", display_score: "85.00", breakdown: {
    categories: Object.fromEntries(categories.map(category => [category, { score: "85", category_weight: configuration.category_weights[category] }])),
    requirements: configuration.requirements.map((requirement, index) => ({ ...requirement, status: ["met", "partially_met", "unmet"][index],
      score_included: true, evidence: index === 2 ? [] : [{ block_id: "page-1", locator: "PDF page 1", quote: "Full source page that should not be displayed." }],
      evidence_preview: index === 2 ? [] : [{ block_id: "page-1", locator: "PDF page 1", quote: "Built React applications." }],
      reason: ["Professional React work is shown.", "Some relevant experience is shown.", "A degree is not listed."][index] })),
    required_gaps: [], counts: {}, review_flags: [],
  } };
const saved = { id: 10, configuration_id: 3, configuration, requirement_version: "requirements-v1", formula_version: "formula-v1",
  status: "completed", created_at: "2026-10-21T10:00:00Z", results: [result] };
let results = saved.results;
function makeResults(count: number) {
  return Array.from({ length: count }, (_, index) => ({ ...result, id: index + 100, application_id: index + 1,
    rank: index + 1, candidate_name: `Applicant ${index + 1}`, display_score: String(100 - index) }));
}
const defaultProps = { jobId: 1, refreshToken: "1", applicationCount: 1, pendingCount: 0, processing: false, ready: true,
  onScreenPending: vi.fn(async () => true), jobSelector: <label>Job posting<select id="screening-job" defaultValue="1"><option value="1">Example job</option></select></label> };

beforeEach(() => {
  vi.clearAllMocks();
  results = saved.results;
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function(this: HTMLDialogElement) { this.setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: function(this: HTMLDialogElement) { this.removeAttribute("open"); } });
  vi.mocked(apiRequest).mockImplementation(async (path, options) => {
    if (path === "/scoring/jobs/1/configuration") return options?.method === "POST" ? { id: 4, snapshot: configuration } : { ...configuration, approved_configuration: null };
    if (path === "/scoring/jobs/1/runs") return options?.method === "POST" ? { ...saved, id: 11, configuration_id: 4, results } : [saved, { ...saved, id: 9 }];
    if (path === "/scoring/runs/10") return { ...saved, results };
    throw new Error("Unexpected test request: " + path);
  });
});

it("groups the selector, compact weights and latest ranking without previous-ranking controls", async () => {
  render(<CandidateScoringPanel {...defaultProps} />);
  expect(await screen.findByText("Synthetic Candidate")).toBeTruthy();
  const ranking = screen.getByRole("region", { name: "Candidate ranking" });
  expect(within(ranking).getByLabelText("Job posting")).toBeTruthy();
  expect(within(ranking).getAllByRole("spinbutton")).toHaveLength(3);
  expect(within(ranking).getByRole("table")).toBeTruthy();
  expect(screen.queryByText(/Previous rankings|View an earlier result|hiring-success probability/)).toBeNull();
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(vi.mocked(apiRequest).mock.calls.some(([path]) => path === "/scoring/runs/9")).toBe(false);
});

it("opens evidence in a portal modal with colored outcomes and restores focus on closing", async () => {
  render(<CandidateScoringPanel {...defaultProps} />);
  const trigger = await screen.findByRole("button", { name: "Inspect evidence for Synthetic Candidate" });
  trigger.focus(); fireEvent.click(trigger);
  const modal = screen.getByRole("dialog", { name: "Synthetic Candidate" });
  expect(modal.parentElement).toBe(document.body);
  expect(document.body.style.overflow).toBe("hidden");
  expect(within(modal).getByText("Met").className).toContain("emerald");
  expect(within(modal).getByText("Partially met").className).toContain("amber");
  expect(within(modal).getByText("Unmet").className).toContain("rose");
  expect(within(modal).queryByText(/View full source|Full source page/)).toBeNull();
  fireEvent.click(within(modal).getByRole("button", { name: "Close evidence" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(document.activeElement).toBe(trigger);
  expect(document.body.style.overflow).not.toBe("hidden");
});

it("closes evidence on Escape and backdrop click", async () => {
  render(<CandidateScoringPanel {...defaultProps} />);
  const trigger = await screen.findByRole("button", { name: "Inspect evidence for Synthetic Candidate" });
  fireEvent.click(trigger); fireEvent(screen.getByRole("dialog"), new Event("cancel", { cancelable: true }));
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(trigger); fireEvent.click(screen.getByRole("dialog"));
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("validates totals and keeps saving and ranking behavior intact", async () => {
  render(<CandidateScoringPanel {...defaultProps} />);
  await screen.findByText("Synthetic Candidate");
  fireEvent.change(screen.getByLabelText("Technical skills (%)"), { target: { value: "60" } });
  expect((screen.getByRole("button", { name: "Rank candidates" }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText(/add up to 100%/)).toBeTruthy();
  expect(screen.getByText(/Current results use technical skills 50%/)).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Experience (%)"), { target: { value: "20" } });
  fireEvent.click(screen.getByRole("button", { name: "Rank candidates" }));
  await screen.findByText("Ranking updated.");
  const post = vi.mocked(apiRequest).mock.calls.find(([path, options]) => path.endsWith("/configuration") && options?.method === "POST");
  expect(JSON.parse(post![1]!.body as string).category_weights).toEqual({ technical: "60", experience: "20", qualification: "20" });
  expect(apiRequest).toHaveBeenCalledWith("/scoring/jobs/1/runs", { method: "POST", body: JSON.stringify({ configuration_id: 4 }) });
});

it("preserves candidate selection for interview scheduling", async () => {
  render(<CandidateScoringPanel {...defaultProps} />);
  fireEvent.click(await screen.findByRole("checkbox", { name: "Select Synthetic Candidate for interview" }));
  expect(screen.getByText("Interview selection: 7")).toBeTruthy();
  await waitFor(() => expect(supervisor.setSelectedApplicationIds).toHaveBeenLastCalledWith([7]));
});

it("queues pending CV screening after saving weights and prevents duplicate actions", async () => {
  render(<CandidateScoringPanel {...defaultProps} pendingCount={1} />);
  await screen.findByText("Synthetic Candidate");
  fireEvent.click(screen.getByRole("button", { name: "Rank candidates" }));
  await waitFor(() => expect(defaultProps.onScreenPending).toHaveBeenCalledOnce());
  expect(vi.mocked(apiRequest).mock.calls.some(([path, options]) => path.endsWith("/runs") && options?.method === "POST")).toBe(false);
});

it("paginates the complete sorted ranking without changing saved ranks or scores", async () => {
  results = makeResults(23).reverse();
  render(<CandidateScoringPanel {...defaultProps} />);
  await screen.findByText("Applicant 1");
  expect(screen.getByText("1–10 of 23 candidates")).toBeTruthy();
  expect(screen.queryByText("Applicant 11")).toBeNull();
  expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(11);
  fireEvent.click(screen.getByRole("button", { name: "Go to ranking page 2" }));
  const firstRow = within(screen.getByRole("table")).getAllByRole("row")[1];
  expect(firstRow.children[1].textContent).toBe("11");
  expect(firstRow.children[3].textContent).toBe("90%");
  expect(screen.getByText("11–20 of 23 candidates")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(screen.getByText("21–23 of 23 candidates")).toBeTruthy();
  expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByRole("button", { name: "Go to ranking page 3" }).getAttribute("aria-current")).toBe("page");
});

it("preserves interview selections and opens the right evidence on later pages", async () => {
  results = makeResults(12);
  render(<CandidateScoringPanel {...defaultProps} />);
  fireEvent.click(await screen.findByRole("checkbox", { name: "Select Applicant 1 for interview" }));
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Select Applicant 11 for interview" }));
  expect(screen.getByText("Interview selection: 1,11")).toBeTruthy();
  const trigger = screen.getByRole("button", { name: "Inspect evidence for Applicant 11" });
  trigger.focus(); fireEvent.click(trigger);
  expect(screen.getByRole("dialog", { name: "Applicant 11" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Close evidence" }));
  expect(document.activeElement).toBe(trigger);
  expect(screen.getByText("Page 2 of 2")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Previous" }));
  expect((screen.getByRole("checkbox", { name: "Select Applicant 1 for interview" }) as HTMLInputElement).checked).toBe(true);
  fireEvent.change(screen.getByLabelText("Candidates per page"), { target: { value: "20" } });
  expect(screen.getByText("Page 1 of 1")).toBeTruthy();
  expect((screen.getByRole("checkbox", { name: "Select Applicant 11 for interview" }) as HTMLInputElement).checked).toBe(true);
});

it("resets to page one and clears interview selection when ranking is updated", async () => {
  results = makeResults(12);
  render(<CandidateScoringPanel {...defaultProps} />);
  await screen.findByText("Applicant 1");
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Select Applicant 11 for interview" }));
  fireEvent.click(screen.getByRole("button", { name: "Rank candidates" }));
  await screen.findByText("Ranking updated.");
  expect(screen.getByText("Page 1 of 2")).toBeTruthy();
  expect(screen.getByText("Interview selection:")).toBeTruthy();
  expect(screen.queryByText("Applicant 11")).toBeNull();
});

it("keeps controls visible but unavailable for a single page or an empty ranking", async () => {
  const view = render(<CandidateScoringPanel {...defaultProps} />);
  await screen.findByText("Synthetic Candidate");
  expect(screen.getByText("Page 1 of 1")).toBeTruthy();
  expect((screen.getByRole("button", { name: "Previous" }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(true);
  results = [];
  view.rerender(<CandidateScoringPanel {...defaultProps} refreshToken="2" />);
  await screen.findByText("0 candidates");
  expect(screen.getByText("Page 1 of 1")).toBeTruthy();
  expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(true);
});

it("bounds numbered controls for large rankings and changes page size", async () => {
  results = makeResults(101);
  render(<CandidateScoringPanel {...defaultProps} />);
  await screen.findByText("Applicant 1");
  expect(screen.getAllByRole("button", { name: /Go to ranking page/ }).length).toBeLessThanOrEqual(7);
  fireEvent.click(screen.getByRole("button", { name: "Go to ranking page 11" }));
  expect(screen.getByText("101–101 of 101 candidates")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Candidates per page"), { target: { value: "5" } });
  expect(screen.getByText("1–5 of 101 candidates")).toBeTruthy();
  expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(6);
});
