import React from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AssessmentView, ComparisonView, score } from "../../src/components/assessments/AssessmentView";
import { assessmentApi, type Assessment, type Comparison } from "../../src/components/assessments/assessmentApi";

vi.mock("../../src/components/assessments/assessmentApi", () => ({ assessmentApi: { export: vi.fn(), artifact: vi.fn(), blob: vi.fn() } }));
function fixture(): Assessment {
  return { id: 1, version: 2, application_id: 101, job_posting_id: 1, status: "completed", stage: "completed", completeness: "partial", review_status: "not_reviewed", stale: true,
    created_at: "2026-10-20T05:00:00Z", missing: [], notes: [], selection_policy: "latest-completed",
    result: { identification: { application_id: 101, job_posting_id: 1, candidate_name: "Synthetic Alpha", job_title: "Backend Engineer", requirement_version: "v1" },
      cv: null, completeness: "partial", missing: [], flags: [], policy: "CV 40% + interview 60%",
      score_summary: { cv_score: "80", interview_score: "60", final_score: "68", cv_weight: 40, interview_weight: 60, ready: true, question_count: 1, unanswered_count: 0, reason: "The final score weights the CV score at 40% and the interview score at 60%." },
      simple_summary: { strengths: [{ text: "The interview answer showed database transactions.", evidence_ids: ["source"] }], improvements: [] },
      evidence: { source: { id: "source", kind: "transcript", quote: "I test atomic transactions.", locator: "Candidate · 00:03", source_version: "test" } },
      matrix: [], interviews: [{ id: 1, date: "2026-10-20", analysis_id: 1, analysis_version: 1, rubric_version: "v2", limitations: [], pairs: [{ id: "q1", question: "How do you test transactions?", answer: "I test atomic transactions.", state: "analyzed", evidence_ids: ["source"], score: { percentage: 60 }, dimensions: { relevance: { label: "direct", finding: "The answer addressed the question.", evidence_ids: ["source"], gaps: [] } } }] }],
      summary: { position: [], strengths: [], limitations: [], verification: [], basis: "Saved results" } } };
}
beforeEach(() => { vi.clearAllMocks(); vi.mocked(assessmentApi.export).mockResolvedValue({ id: 5, status: "failed", format: "pdf", error: "PDF renderer unavailable." }); });

describe("simple candidate details", () => {
  it("keeps historical report weights and totals instead of relabelling them", () => {
    const report = fixture();
    report.result.score_summary = { ...report.result.score_summary!, cv_weight: 50, interview_weight: 50, final_score: "70", reason: "Saved 50/50 calculation." };
    render(<MemoryRouter><AssessmentView report={report} /></MemoryRouter>);
    expect(screen.getByText(/CV 50% \+ interview 50%/)).toBeTruthy();
    expect(screen.getByText("70.00%")).toBeTruthy();
    expect(screen.queryByText(/CV 40% \+ interview 60%/)).toBeNull();
  });
  it("replaces the old summary with four traceable categories in new reports", () => {
    const report = fixture();
    report.result.evidence_summary = {
      strengths: [{ text: "Supported atomicity explanation.", evidence_ids: ["source", "source"] }], weaknesses: [],
      evidence_gaps: [{ text: "Failure testing was not explored.", evidence_ids: ["source"] }],
      verification: [{ text: "Confirm the contextual transcription reading.", evidence_ids: ["source"] }],
    };
    const saved = JSON.stringify(report);
    render(<MemoryRouter><AssessmentView report={report} /></MemoryRouter>);
    const summary = screen.getByRole("region", { name: "Evidence-based summary" });
    for (const name of ["Strengths", "Weaknesses", "Evidence gaps", "Further verification"]) expect(within(summary).getByRole("region", { name })).toBeTruthy();
    const strengths = within(summary).getByRole("region", { name: "Strengths" });
    fireEvent.click(within(strengths).getByText("View supporting evidence"));
    expect(strengths.querySelectorAll("blockquote")).toHaveLength(1);
    expect(within(strengths).getByText(/Candidate · 00:03/)).toBeTruthy();
    expect(screen.queryByText("Areas to improve")).toBeNull();
    expect(JSON.stringify(report)).toBe(saved);
    expect(assessmentApi.export).not.toHaveBeenCalled();
  });
  it("formats scores exactly and keeps missing scores distinct from zero", () => {
    expect(score("2.675000")).toBe("2.68%");
    expect(score("0E-60")).toBe("0.00%");
    expect(score(null)).toBe("—");
  });
  it("shows three scores and plain reasons without technical controls", () => {
    render(<MemoryRouter><AssessmentView report={fixture()} /></MemoryRouter>);
    expect(screen.getByText("80.00%")).toBeTruthy();
    expect(screen.getByText("68.00%")).toBeTruthy();
    expect(screen.getByText(/CV 40% \+ interview 60%/)).toBeTruthy();
    expect(screen.getByText(/These are saved results/)).toBeTruthy();
    expect(screen.getByText("The interview answer showed database transactions.")).toBeTruthy();
    expect(screen.queryByText("Requirement evidence matrix")).toBeNull();
    expect(screen.queryByLabelText("Assessment review note")).toBeNull();
    expect(assessmentApi.export).not.toHaveBeenCalled();
  });
  it("keeps question answers and score explanations collapsed until requested", () => {
    render(<MemoryRouter><AssessmentView report={fixture()} /></MemoryRouter>);
    const question = screen.getByText("How do you test transactions?").closest("details")!;
    expect(question.open).toBe(false);
    fireEvent.click(question.querySelector("summary")!);
    const evidence = screen.getByText("Why this score?").closest("details")!;
    expect(evidence.open).toBe(false);
    fireEvent.click(evidence.querySelector("summary")!);
    expect(screen.getByText("The answer addressed the question.")).toBeTruthy();
    expect(screen.queryByText("Candidate · 00:03")).toBeNull();
  });
  it("offers a single PDF download button and allows retry if preparation fails", async () => {
    render(<MemoryRouter><AssessmentView report={fixture()} /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: "Download this report" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(assessmentApi.export).toHaveBeenCalledWith(1, "pdf");
    expect((screen.getByRole("button", { name: "Download this report" }) as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByText("Prepare HTML / print")).toBeNull();
    expect(screen.queryByText("Prepare PDF")).toBeNull();
    expect(screen.getByText("68.00%")).toBeTruthy();
    expect(screen.getByText("80.00%").className).toContain("text-teal-800");
    expect(screen.getAllByText("60.00%")[0].className).toContain("text-violet-800");
    expect(screen.getByText("68.00%").className).toContain("text-blue-700");
  });
  it("prints the answer once even when all scoring categories cite it", () => {
    const report = fixture();
    const pair = report.result.interviews[0].pairs[0];
    pair.answer = "Sorry. I'm not sure about that one.";
    report.result.evidence.source.quote = pair.answer;
    pair.dimensions = Object.fromEntries(["relevance", "accuracy", "completeness", "quality"].map(name => [name, {
      label: "unmet", finding: `No support for ${name}.`, evidence_ids: ["source", "source"], gaps: [],
    }]));
    const saved = JSON.stringify(report);
    render(<MemoryRouter><AssessmentView report={report} /></MemoryRouter>);
    const question = screen.getByText(pair.question).closest("details")!;
    fireEvent.click(question.querySelector("summary")!);
    fireEvent.click(screen.getByText("Why this score?"));
    expect(within(question).getAllByText(pair.answer, { exact: false })).toHaveLength(1);
    expect(within(question).queryByText("Candidate · 00:03")).toBeNull();
    expect(within(question).queryByText("Answer source")).toBeNull();
    expect(question.querySelectorAll("blockquote")).toHaveLength(0);
    for (const name of ["relevance", "accuracy", "completeness", "quality"]) {
      expect(within(question).getByText(`No support for ${name}.`)).toBeTruthy();
    }
    expect(JSON.stringify(report)).toBe(saved);
  });
  it("hides question reference quotes and source locators without changing saved evidence", () => {
    const report = fixture();
    const pair = report.result.interviews[0].pairs[0];
    const guide = { id: "guide", kind: "answer_guide", quote: "Transactions should be atomic.", locator: "Question bank · Transactions", source_version: "v1" };
    report.result.evidence.guide = guide;
    report.result.evidence.alias = { ...guide, id: "alias", quote: "Transactions should  be atomic.", locator: "Question bank · Examples" };
    pair.dimensions.relevance.evidence_ids.push("guide", "alias", "missing");
    pair.dimensions.accuracy = { ...pair.dimensions.relevance, evidence_ids: ["guide", "alias", "source"] };
    const saved = JSON.stringify(report);
    render(<MemoryRouter><AssessmentView report={report} /></MemoryRouter>);
    const question = screen.getByText(pair.question).closest("details")!;
    expect(within(question).queryByText(guide.quote)).toBeNull();
    expect(within(question).queryByText(guide.locator)).toBeNull();
    expect(within(question).queryByText("Question bank · Examples")).toBeNull();
    expect(question.querySelectorAll("blockquote")).toHaveLength(0);
    expect(JSON.stringify(report)).toBe(saved);
  });
  it("shows the answer once without extra transcript passages or timestamps", () => {
    const report = fixture();
    const pair = report.result.interviews[0].pairs[0];
    pair.answer = "I test atomic transactions.\nI also test rollback.";
    report.result.evidence.excerpt = { ...report.result.evidence.source, id: "excerpt", quote: "I also  test rollback.", locator: "Candidate · 00:05" };
    report.result.evidence.extra = { ...report.result.evidence.source, id: "extra", quote: "I check database isolation.", locator: "Candidate · 00:09" };
    pair.evidence_ids.push("excerpt", "extra");
    render(<MemoryRouter><AssessmentView report={report} /></MemoryRouter>);
    const question = screen.getByText(pair.question).closest("details")!;
    expect(question.querySelectorAll("blockquote")).toHaveLength(0);
    expect(within(question).queryByText("I check database isolation.")).toBeNull();
    expect(within(question).queryByText("Candidate · 00:05")).toBeNull();
    expect(within(question).queryByText("Candidate · 00:09")).toBeNull();
    expect(within(question).getAllByText(/I test atomic transactions/)).toHaveLength(1);
  });
  it("keeps unanswered questions readable when source IDs are missing", () => {
    const report = fixture();
    const pair = report.result.interviews[0].pairs[0];
    pair.answer = ""; pair.evidence_ids = ["missing"]; pair.dimensions = {};
    render(<MemoryRouter><AssessmentView report={report} /></MemoryRouter>);
    expect(screen.getByText(/No answer recorded. This question scores zero./)).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Question sources" })).toBeNull();
  });
  it("preserves the separate CV evidence section", () => {
    const report = fixture();
    report.result.evidence.cv = { id: "cv", kind: "cv", quote: "Built transaction tests.", locator: "CV page 1", source_version: "v1" };
    report.result.matrix.push({ requirement_id: "testing", name: "Database testing", classification: "technical", version: "v1", weight: 1,
      cv_status: "met", cv_evidence_ids: ["cv"], interview_statuses: [], interview_coverage: "covered", questions_asked: [], interview_evidence: [],
      conflict: false, uncertainty: [], verification: "Saved evidence" });
    render(<MemoryRouter><AssessmentView report={report} /></MemoryRouter>);
    fireEvent.click(screen.getByText("CV evidence"));
    expect(screen.getByText("Built transaction tests.")).toBeTruthy();
    expect(screen.getByText(/CV page 1 · Source version v1/)).toBeTruthy();
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
