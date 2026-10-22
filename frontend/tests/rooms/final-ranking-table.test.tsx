import React from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { FinalRankingTable } from "../../src/components/assessments/FinalRankingTable";
import { assessmentApi, type FinalRanking } from "../../src/components/assessments/assessmentApi";
import { selectOption } from "./selectHelpers";

vi.mock("../../src/components/assessments/assessmentApi", () => ({ assessmentApi: { export: vi.fn(), artifact: vi.fn(), blob: vi.fn() } }));
function fixture(count = 12): FinalRanking {
  return { id: 7, status: "completed", stage: "completed", policy: "CV 40% + interview 60%", stale: false, incompatibilities: [], candidates: Array.from({ length: count }, (_, index) => ({
    application_id: index + 1, assessment_id: index + 100, candidate_name: `Candidate ${index + 1}`, final_rank: index + 1,
    cv_score: "80", interview_score: "60", final_score: "68", reason: "CV 40% + interview 60%",
  })) };
}
beforeEach(() => { vi.clearAllMocks(); vi.mocked(assessmentApi.export).mockResolvedValue({ id: 10, status: "queued", format: "pdf" }); });

it("paginates saved ranks without renumbering them when searching", () => {
  const ranking = fixture(); ranking.candidates[11].final_rank = 23;
  render(<FinalRankingTable ranking={ranking} onDetails={vi.fn()} />);
  expect(screen.getAllByRole("row")).toHaveLength(11);
  expect(screen.queryByText("Candidate 12")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(screen.getByText("Candidate 12")).toBeTruthy();
  fireEvent.change(screen.getByRole("searchbox", { name: "Search candidates" }), { target: { value: "Candidate 12" } });
  const row = screen.getByText("Candidate 12").closest("tr")!;
  expect(within(row).getByText("23")).toBeTruthy();
  expect(screen.getByText("Page 1 of 1")).toBeTruthy();
});

it("clears an empty search and preserves row IDs when changing page size", () => {
  render(<FinalRankingTable ranking={fixture()} onDetails={vi.fn()} />);
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Not a candidate" } });
  expect(screen.getByText("No matching candidates.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Clear search" }));
  selectOption("Candidates per page", "20");
  expect(screen.getAllByRole("row")).toHaveLength(13);
  expect(screen.getByText("Candidate 12")).toBeTruthy();
});

it("keeps missing scores distinct from scientific-notation zero scores", () => {
  const ranking = fixture(2);
  ranking.candidates[0] = { ...ranking.candidates[0], interview_score: "0E-60", cv_score: "2.675", final_score: "0" };
  ranking.candidates[1] = { ...ranking.candidates[1], final_rank: null, interview_score: null, final_score: null, reason: "Interview not scored yet" };
  const original = JSON.stringify(ranking);
  render(<FinalRankingTable ranking={ranking} onDetails={vi.fn()} />);
  const first = screen.getByText("Candidate 1").closest("tr")!;
  expect(within(first).getByText("2.68%")).toBeTruthy();
  expect(within(first).getAllByText("0.00%")).toHaveLength(2);
  const second = screen.getByText("Candidate 2").closest("tr")!;
  expect(within(second).getAllByText("—")).toHaveLength(3);
  expect(within(second).getByText("Interview not scored yet")).toBeTruthy();
  expect(JSON.stringify(ranking)).toBe(original);
});

it("opens the correct assessment and disables details when scoring is unfinished", () => {
  const open = vi.fn(); const ranking = fixture(1);
  const view = render(<FinalRankingTable ranking={ranking} onDetails={open} />);
  fireEvent.click(screen.getByRole("button", { name: "View details for Candidate 1" }));
  expect(open).toHaveBeenCalledWith(1, 100);
  view.rerender(<FinalRankingTable ranking={{ ...ranking, status: "processing", stage: "scoring_answers" }} onDetails={open} />);
  expect((screen.getByRole("button", { name: "View details for Candidate 1" }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText(/Scoring interview answers/)).toBeTruthy();
});

it("keeps stale-result warnings and incompatible evidence visible", () => {
  render(<FinalRankingTable ranking={{ ...fixture(1), stale: true, error: "Saved calculation failed.", incompatibilities: ["Different scoring weights.", "Different scoring weights."] }} onDetails={vi.fn()} />);
  expect(screen.getByRole("alert").textContent).toContain("failed");
  expect(screen.getByText(/Candidates or scores have changed/)).toBeTruthy();
  expect(screen.getAllByText("Different scoring weights.")).toHaveLength(1);
});

it("keeps exports explicit and uses the existing ranking export endpoint", async () => {
  render(<FinalRankingTable ranking={fixture(1)} onDetails={vi.fn()} />);
  expect(assessmentApi.export).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Download ranking"));
  fireEvent.click(screen.getByRole("button", { name: "Prepare PDF" }));
  await screen.findByText("PDF: queued");
  expect(assessmentApi.export).toHaveBeenCalledWith(7, "pdf", true);
});

it("shows a useful empty state without a misleading rank or score", () => {
  render(<FinalRankingTable ranking={fixture(0)} onDetails={vi.fn()} />);
  expect(screen.getByText("No candidates have applied for this job yet.")).toBeTruthy();
  expect(screen.queryByRole("table")).toBeNull();
  expect(screen.queryByText("0.00%")).toBeNull();
});
