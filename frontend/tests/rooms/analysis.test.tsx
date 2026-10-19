import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { InterviewAnalysisPanel } from "../../src/components/interviews/InterviewAnalysisPanel";
import { TranscriptCitation } from "../../src/components/interviews/TranscriptCitation";
import { analysisApi, type AnalysisState, type Citation } from "../../src/components/interviews/analysisApi";

vi.mock("../../src/components/interviews/analysisApi", () => ({ analysisApi: { read: vi.fn(), start: vi.fn(), correct: vi.fn(), references: vi.fn(), review: vi.fn() } }));
const citation: Citation = { interview_id: 1, segment_id: "a", session_id: "s", revision: "hash-a", quote: "commit changes", char_start: 13, char_end: 27,
  speaker: "CANDIDATE", start_at: "2026-10-19T00:00:03Z", end_at: "2026-10-19T00:00:05Z", start_offset_ms: 3000, end_offset_ms: 5000 };
function fixture(): AnalysisState {
  const dimension = { label: "direct", justification: "The answer addresses transactions.", citations: [citation], references: [], evidence_gaps: [], flags: [] };
  return { automatic: false, references: [], reference_revision: 0, versions: [{ id: 10, version: 1, status: "completed", created_at: "2026-10-19" }], run: {
    id: 10, version: 1, status: "completed", stage: "completed", stale: false, created_at: "2026-10-19", reviews: [],
    snapshot: { segments: [{ id: "q", hash: "hash-q", speaker: "INTERVIEWER", text: "Explain transactions", start_offset_ms: 0, end_offset_ms: 2000 },
      { id: "a", hash: "hash-a", speaker: "CANDIDATE", text: "Transactions commit changes atomically.", start_offset_ms: 3000, end_offset_ms: 5000 }],
      references: [], requirements: { requirements: [{ key: "skill:0", name: "Transactions" }] }, requirement_version: "v1" },
    result: { pairs: [{ id: "pair", question_ids: ["q"], answer_ids: ["a"], context_ids: [], subparts: [], excluded: false, unanswered: false,
      state: "analyzed", flags: [], pairing_confidence: "supported", pairing_reasons: ["The candidate responds after the question."],
      assessment: { relevance: dimension, accuracy: { ...dimension, label: "unable_to_verify" }, completeness: { ...dimension, label: "complete" }, quality: { ...dimension, label: "clear" }, expected_elements: ["Atomicity"], expected_elements_basis: "provisional" },
      suggestions: [{ id: "follow", question: "How would you test rollback?", reason: "Explore testing", requirement_ids: [], citations: [citation], expected_clarification: "A test example", priority: "normal", priority_reason: "Useful clarification" }] }],
      coverage: [{ requirement_id: "skill:1", name: "Testing", statuses: ["not_assessed"], evidence: [] }], gaps: [], unpaired: [] },
  } };
}
beforeEach(() => { vi.mocked(analysisApi.read).mockResolvedValue(fixture()); vi.mocked(analysisApi.start).mockResolvedValue({}); });

describe("interviewer answer analysis", () => {
  it("restores saved assessments without generating analysis on page load", async () => {
    render(<InterviewAnalysisPanel interviewId={1} />);
    expect(await screen.findByText("Question–answer timeline")).toBeTruthy();
    expect(screen.getByText(/accuracy · unable to verify/i)).toBeTruthy();
    expect(analysisApi.start).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Analyze saved answers" }));
    await waitFor(() => expect(analysisApi.start).toHaveBeenCalledWith(1, true));
  });
  it("opens and highlights the exact source and rejects changed source text", async () => {
    const { unmount } = render(<TranscriptCitation citation={citation} interviewId={1} runId={10} />);
    fireEvent.click(screen.getByRole("button"));
    expect(await screen.findByRole("dialog")).toBeTruthy();
    expect(document.querySelector("mark")?.textContent).toBe("commit changes");
    unmount();
    const changed = fixture(); changed.run!.snapshot.segments[1].hash = "changed";
    vi.mocked(analysisApi.read).mockResolvedValue(changed);
    render(<TranscriptCitation citation={citation} interviewId={1} runId={10} />);
    fireEvent.click(screen.getByRole("button"));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
  it("keeps not assessed distinct and records a suggestion as used without pretending it was spoken", async () => {
    render(<InterviewAnalysisPanel interviewId={1} />);
    await screen.findByText("Question–answer timeline");
    fireEvent.click(screen.getByText("Requirement evidence coverage"));
    expect(screen.getByText(/not a failure to meet it/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Mark used" }));
    await waitFor(() => expect(analysisApi.review).toHaveBeenCalledWith(1, 10, "suggestion_used", "follow"));
    expect(await screen.findByText(/Link a spoken question to confirm/)).toBeTruthy();
  });
  it("uses Unicode character offsets for exact highlighted quotes", async () => {
    const data = fixture(); data.run!.snapshot.segments[1].text = "👋 commit changes";
    vi.mocked(analysisApi.read).mockResolvedValue(data);
    render(<TranscriptCitation citation={{ ...citation, char_start: 2, char_end: 16 }} interviewId={1} runId={10} />);
    fireEvent.click(screen.getByRole("button"));
    await screen.findByRole("dialog");
    expect(document.querySelector("mark")?.textContent).toBe("commit changes");
  });
  it("offers correction controls and blocks saving an exchange with no question", async () => {
    render(<InterviewAnalysisPanel interviewId={1} />);
    await screen.findByText("Question–answer timeline");
    fireEvent.click(screen.getByRole("button", { name: "Correct pairing / merge / split" }));
    fireEvent.click(screen.getByRole("button", { name: "Split — add exchange after this" }));
    fireEvent.change(screen.getByLabelText("Reason for correction"), { target: { value: "Separate the follow-up." } });
    expect((screen.getByRole("button", { name: "Save correction & reanalyze" }) as HTMLButtonElement).disabled).toBe(true);
  });
  it("requires explicit approval before saving reference material", async () => {
    render(<InterviewAnalysisPanel interviewId={1} />);
    await screen.findByText("Question–answer timeline");
    fireEvent.click(screen.getByText("Approved answer guides & technical references"));
    fireEvent.change(screen.getByLabelText("Reference title"), { target: { value: "Atomicity" } });
    fireEvent.change(screen.getByLabelText("Reference text"), { target: { value: "All changes commit or none do." } });
    expect((screen.getByRole("button", { name: "Save approved reference" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByLabelText("I approve this material for assessing this interview."));
    fireEvent.click(screen.getByRole("button", { name: "Save approved reference" }));
    await waitFor(() => expect(analysisApi.references).toHaveBeenCalled());
  });
});
