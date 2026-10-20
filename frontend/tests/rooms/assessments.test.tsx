import React from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AssessmentView, ComparisonView, score } from "../../src/components/assessments/AssessmentView";
import { assessmentApi, type Assessment, type Comparison } from "../../src/components/assessments/assessmentApi";

vi.mock("../../src/components/assessments/assessmentApi", () => ({ assessmentApi: { export: vi.fn(), artifact: vi.fn(), blob: vi.fn() } }));
function fixture(): Assessment {
  return { id: 1, version: 2, application_id: 101, job_posting_id: 1, status: "completed", stage: "completed", completeness: "partial", review_status: "not_reviewed", stale: true,
    created_at: "2026-10-20T05:00:00Z", missing: [], notes: [], selection_policy: "latest-completed",
    result: { identification: { application_id: 101, job_posting_id: 1, candidate_name: "Synthetic Alpha", job_title: "Backend Engineer", requirement_version: "v1" },
      cv: null, completeness: "partial", missing: [], flags: [], policy: "CV 50% + interview 50%",
      score_summary: { cv_score: "80", interview_score: "60", final_score: "70", ready: true, question_count: 1, unanswered_count: 0, reason: "The final score combines the CV score and the interview score, with equal weight." },
      simple_summary: { strengths: [{ text: "The interview answer showed database transactions.", evidence_ids: ["source"] }], improvements: [] },
      evidence: { source: { id: "source", kind: "transcript", quote: "I test atomic transactions.", locator: "Candidate · 00:03", source_version: "test" } },
      matrix: [], interviews: [{ id: 1, date: "2026-10-20", analysis_id: 1, analysis_version: 1, rubric_version: "v2", limitations: [], pairs: [{ id: "q1", question: "How do you test transactions?", answer: "I test atomic transactions.", state: "analyzed", evidence_ids: ["source"], score: { percentage: 60 }, dimensions: { relevance: { label: "direct", finding: "The answer addressed the question.", evidence_ids: ["source"], gaps: [] } } }] }],
      summary: { position: [], strengths: [], limitations: [], verification: [], basis: "Saved results" } } };
}
beforeEach(() => { vi.clearAllMocks(); vi.mocked(assessmentApi.export).mockResolvedValue({ id: 5, status: "failed", format: "pdf", error: "PDF renderer unavailable." }); });

describe("simple candidate details", () => {
  it("formats scores exactly and keeps missing scores distinct from zero", () => {
    expect(score("2.675000")).toBe("2.68%");
    expect(score("0E-60")).toBe("0.00%");
    expect(score(null)).toBe("—");
  });
  it("shows three scores and plain reasons without technical controls", () => {
    render(<MemoryRouter><AssessmentView report={fixture()} /></MemoryRouter>);
    expect(screen.getByText("80.00%")).toBeTruthy();
    expect(screen.getByText("70.00%")).toBeTruthy();
    expect(screen.getByText(/These are saved results/)).toBeTruthy();
    expect(screen.getByText("The interview answer showed database transactions.")).toBeTruthy();
    expect(screen.queryByText("Requirement evidence matrix")).toBeNull();
    expect(screen.queryByLabelText("Assessment review note")).toBeNull();
    expect(assessmentApi.export).not.toHaveBeenCalled();
  });
  it("keeps question answers and supporting evidence collapsed until requested", () => {
    render(<MemoryRouter><AssessmentView report={fixture()} /></MemoryRouter>);
    const question = screen.getByText("How do you test transactions?").closest("details")!;
    expect(question.open).toBe(false);
    fireEvent.click(question.querySelector("summary")!);
    const evidence = screen.getByText("Why this score? View evidence").closest("details")!;
    expect(evidence.open).toBe(false);
    fireEvent.click(evidence.querySelector("summary")!);
    expect(screen.getByText("Candidate · 00:03")).toBeTruthy();
  });
  it("keeps HTML available if a PDF fails", async () => {
    render(<MemoryRouter><AssessmentView report={fixture()} /></MemoryRouter>);
    fireEvent.click(screen.getByText("Download this report"));
    fireEvent.click(screen.getByText("Prepare PDF"));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect((screen.getByText("Prepare HTML / print") as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByText("70.00%")).toBeTruthy();
  });
  it("does not invent final scores for older saved reports", () => {
    const r = fixture(); delete r.result.score_summary;
    const value = { id: 3, created_at: "synthetic", snapshot: { basis: "Saved comparison", policy: "Historical comparison", cv_order_compatible: false,
      combined_ranking_available: false, incompatibilities: [], interview_incompatibilities: [], assessments: [r], selected_cohort_application_ids: [101], cohort_policy: "Explicit cohort" } } satisfies Comparison;
    render(<MemoryRouter><ComparisonView value={value} /></MemoryRouter>);
    expect(screen.getAllByText("—")).toHaveLength(3);
    expect(screen.getByText("View details")).toBeTruthy();
  });
});
