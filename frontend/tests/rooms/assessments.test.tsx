import React from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AssessmentView, ComparisonView, score } from "../../src/components/assessments/AssessmentView";
import { assessmentApi, type Assessment, type Comparison } from "../../src/components/assessments/assessmentApi";

vi.mock("../../src/components/assessments/assessmentApi", () => ({ assessmentApi: { export: vi.fn(), artifact: vi.fn(), blob: vi.fn(), review: vi.fn() } }));
function fixture(): Assessment {
  return { id: 1, version: 2, application_id: 101, job_posting_id: 1, status: "completed", stage: "completed", completeness: "partial", review_status: "not_reviewed", stale: true,
    created_at: "2026-10-20T05:00:00Z", missing: ["Finalized transcript"], notes: [], selection_policy: "latest-completed",
    result: { identification: { application_id: 101, job_posting_id: 1, candidate_name: "Synthetic Alpha", job_title: "Backend Engineer", requirement_version: "v1" },
      cv: null, completeness: "partial", missing: ["Finalized transcript"], flags: [], policy: "CV score order only; interview findings are separate.",
      evidence: { source: { id: "source", kind: "cv", quote: "Built atomic transactions.", locator: "Synthetic PDF page 1", source_version: "cv-hash-v1" } },
      matrix: [], interviews: [], summary: { position: [{ id: "fact", text: "A saved evidence finding.", evidence_ids: ["source"] }], strengths: [], limitations: [], verification: [], basis: "Deterministic evidence summary" } } };
}
beforeEach(() => { vi.clearAllMocks(); vi.mocked(assessmentApi.export).mockResolvedValue({ id: 5, status: "failed", format: "pdf", error: "PDF renderer unavailable." }); });
describe("private consolidated assessments", () => {
  it("uses the same exact decimal half-up formatting as exported scores", () => {
    expect(score("2.675000")).toBe("2.68%");
    expect(score("0.000000")).toBe("0.00%");
    expect(score(null)).toBe("Not available");
  });
  it("shows missing sources and stale notice separately from completed generation", () => {
    render(<MemoryRouter><AssessmentView report={fixture()} /></MemoryRouter>);
    expect(screen.getByText(/Relevant source versions changed/)).toBeTruthy();
    expect(screen.getByText(/Partial report: missing/)).toBeTruthy();
    expect(screen.getByText("Finalized transcript")).toBeTruthy();
    expect(assessmentApi.export).not.toHaveBeenCalled();
  });
  it("opens saved source evidence and records an attributable review note", async () => {
    const r = fixture(); vi.mocked(assessmentApi.review).mockResolvedValue(r);
    render(<MemoryRouter><AssessmentView report={r} /></MemoryRouter>);
    fireEvent.click(screen.getByText("Evidence: Synthetic PDF page 1"));
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getByText("Built atomic transactions.")).toBeTruthy();
    fireEvent.click(screen.getByText("Close"));
    fireEvent.change(screen.getByLabelText("Assessment review note"), { target: { value: "Verify the integration test example." } });
    fireEvent.click(screen.getByText("Save note"));
    await waitFor(() => expect(assessmentApi.review).toHaveBeenCalledWith(1, "Verify the integration test example.", true));
  });
  it("keeps HTML preparation available when a PDF export fails", async () => {
    render(<MemoryRouter><AssessmentView report={fixture()} /></MemoryRouter>);
    fireEvent.click(screen.getByText("Prepare PDF"));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect((screen.getByText("Prepare HTML / print") as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByText("A saved evidence finding.")).toBeTruthy();
  });
  it("labels incompatible comparisons informational and never invents a combined score", () => {
    const value = { id: 3, created_at: "synthetic", snapshot: { basis: "Informational comparison", policy: "No combined ranking is calculated.", cv_order_compatible: false,
      combined_ranking_available: false, incompatibilities: ["CV weights differ"], interview_incompatibilities: [], assessments: [fixture()], selected_cohort_application_ids: [101,102], cohort_policy: "Explicit cohort" } } satisfies Comparison;
    render(<MemoryRouter><ComparisonView value={value} /></MemoryRouter>);
    expect(screen.getByText("CV weights differ")).toBeTruthy();
    expect(screen.queryByText(/Comparison cohort CV rank/)).toBeNull();
    expect(screen.getByText(/CV score: Not available/)).toBeTruthy();
  });
});
