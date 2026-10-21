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
const defaultProps = { jobId: 1, refreshToken: "1", applicationCount: 1, pendingCount: 0, processing: false, ready: true,
  onScreenPending: vi.fn(async () => true), jobSelector: <label>Job posting<select id="screening-job" defaultValue="1"><option value="1">Example job</option></select></label> };

beforeEach(() => {
  vi.clearAllMocks();
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function(this: HTMLDialogElement) { this.setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: function(this: HTMLDialogElement) { this.removeAttribute("open"); } });
  vi.mocked(apiRequest).mockImplementation(async (path, options) => {
    if (path === "/scoring/jobs/1/configuration") return options?.method === "POST" ? { id: 4, snapshot: configuration } : { ...configuration, approved_configuration: null };
    if (path === "/scoring/jobs/1/runs") return options?.method === "POST" ? { ...saved, id: 11, configuration_id: 4 } : [saved, { ...saved, id: 9 }];
    if (path === "/scoring/runs/10") return saved;
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
