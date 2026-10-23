import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { InterviewAnalysisPanel } from "../../src/components/interviews/InterviewAnalysisPanel";
import { TranscriptCitation } from "../../src/components/interviews/TranscriptCitation";
import { analysisApi, type AnalysisState, type Citation } from "../../src/components/interviews/analysisApi";
import { readFileSync } from "node:fs";

vi.mock("../../src/components/interviews/analysisApi", () => ({ analysisApi: { read: vi.fn(), start: vi.fn() } }));
const citation: Citation = { interview_id: 1, segment_id: "a", session_id: "s", revision: "hash-a", quote: "commit changes", char_start: 13, char_end: 27,
  speaker: "CANDIDATE", start_at: "2026-10-19T00:00:03Z", end_at: "2026-10-19T00:00:05Z", start_offset_ms: 3000, end_offset_ms: 5000 };
function fixture(): AnalysisState {
  const dimension = { label: "direct", justification: "The answer addresses transactions.", citations: [citation], references: [], evidence_gaps: [], flags: [] };
  return { automatic: false, references: [], reference_revision: 0, versions: [{ id: 10, version: 1, status: "completed", created_at: "2026-10-19" }], run: {
    id: 10, version: 1, status: "completed", stage: "completed", stale: false, created_at: "2026-10-19", reviews: [{ id: 4, kind: "assessment_review", target_id: "pair", payload: { note: "An old manual review" }, created_at: "2026-10-19" }],
    snapshot: { segments: [{ id: "q", hash: "hash-q", speaker: "INTERVIEWER", text: "Explain transactions", start_offset_ms: 0, end_offset_ms: 2000 },
      { id: "a", hash: "hash-a", speaker: "CANDIDATE", text: "Transactions commit changes atomically.", start_offset_ms: 3000, end_offset_ms: 5000 }],
      references: [], requirements: { requirements: [{ key: "skill:0", name: "Transactions" }] }, requirement_version: "v1" },
    result: { pairs: [{ id: "pair", question_ids: ["q"], answer_ids: ["a"], context_ids: [], subparts: [], excluded: false, unanswered: false,
      state: "analyzed", flags: [], pairing_confidence: "supported", pairing_reasons: ["The candidate responds after the question."],
      score: { percentage: 75, earned: 3, possible: 4, rubric_version: "v2", breakdown: {
        relevance: { value: 1, weight: 25, status: "met", reason: dimension.justification },
        accuracy: { value: 0, weight: 25, status: "unmet", reason: "Accuracy is not established by the answer guide." },
        completeness: { value: 1, weight: 25, status: "met", reason: "The expected elements are addressed." },
        quality: { value: 1, weight: 25, status: "met", reason: "The answer includes clear technical reasoning." } } },
      assessment: { relevance: dimension, accuracy: { ...dimension, label: "unable_to_verify" }, completeness: { ...dimension, label: "complete" }, quality: { ...dimension, label: "clear" }, expected_elements: ["Atomicity"], expected_elements_basis: "provisional" },
      suggestions: [{ id: "follow", question: "How would you test rollback?", reason: "Explore testing", requirement_ids: [], citations: [citation], expected_clarification: "A test example", priority: "normal", priority_reason: "Useful clarification" }] }],
      coverage: [{ requirement_id: "skill:1", name: "Testing", statuses: ["not_assessed"], evidence: [] }], gaps: [], unpaired: [] },
  } };
}
beforeEach(() => { vi.mocked(analysisApi.read).mockReset().mockResolvedValue(fixture()); vi.mocked(analysisApi.start).mockReset().mockResolvedValue({}); });

describe("simplified interviewer answer analysis", () => {
  it("shows four evidence categories with immutable source links without generating on read", async () => {
    const data = fixture();
    data.run!.result.evidence_summary = {
      strengths: [{ id: "one", text: "The answer addresses transaction atomicity.", rule: "validated_dimension_labels", pair_id: "pair", citations: [citation], references: [], source: { kind: "exchange", state: "analyzed" } }],
      weaknesses: [], evidence_gaps: [{ id: "two", text: "Testing was not explored.", rule: "requirement_not_explored", pair_id: null, citations: [], references: [], source: { kind: "requirement", requirement_id: "skill:1", version: "v1" } }], verification: [],
    };
    vi.mocked(analysisApi.read).mockResolvedValue(data);
    const saved = JSON.stringify(data);
    render(<InterviewAnalysisPanel interviewId={1} />);
    const summary = await screen.findByRole("region", { name: "Candidate performance" });
    for (const name of ["Strengths", "Areas to improve", "Not yet assessed", "Needs checking"]) expect(within(summary).getByRole("region", { name })).toBeTruthy();
    fireEvent.click(within(within(summary).getByRole("region", { name: "Strengths" })).getByText("Sources"));
    fireEvent.click(await within(summary).findByRole("button", { name: /Candidate · 00:03/ }));
    expect(await screen.findByRole("dialog", { name: "Transcript source passage" })).toBeTruthy();
    expect(analysisApi.read).toHaveBeenCalledWith(1, 10);
    expect(analysisApi.start).not.toHaveBeenCalled();
    expect(JSON.stringify(data)).toBe(saved);
  });

  it("discloses contextual ASR readings while leaving the original answer unchanged", async () => {
    const data = fixture(), pair = data.run!.result.pairs![0];
    pair.assessment!.interpretation = { status: "context_supported", support_status: "supported_by_check", meaning: "An interpreted answer.", notes: [{ original: citation, interpreted_as: "atomic commits", reason: "Supported by the adjacent explanation.", context: [citation] }] };
    vi.mocked(analysisApi.read).mockResolvedValue(data);
    render(<InterviewAnalysisPanel interviewId={1} />);
    fireEvent.click(await screen.findByText("Transcription interpretation"));
    expect(screen.getByText("atomic commits")).toBeTruthy();
    expect(screen.getByText("Transactions commit changes atomically.")).toBeTruthy();
    expect(screen.getByText(/not verified against audio/)).toBeTruthy();
  });

  it("keeps ambiguous wording unscored and does not show unsupported judgments", async () => {
    const data = fixture(), pair = data.run!.result.pairs![0];
    delete pair.score;
    pair.state = "needs_clarification";
    pair.score_unavailable_reason = "Verify the unclear negation before scoring.";
    pair.assessment!.interpretation = { status: "uncertain", support_status: "supported_by_check", meaning: "Unclear", notes: [] };
    vi.mocked(analysisApi.read).mockResolvedValue(data);
    render(<InterviewAnalysisPanel interviewId={1} />);
    expect(await screen.findByText("Wording needs verification")).toBeTruthy();
    expect(screen.queryByLabelText(/Answer score/)).toBeNull();
    expect(screen.getAllByText("Not scored")).toHaveLength(4);
    expect(screen.queryByText("The answer addresses transactions.")).toBeNull();
    expect(screen.queryByText("Transcription interpretation")).toBeNull();
  });

  it("retries failed evidence checks without asking the API to reroll accepted grades", async () => {
    const data = fixture(); data.run!.result.pairs![0].state = "analysis_failed";
    delete data.run!.result.pairs![0].score;
    vi.mocked(analysisApi.read).mockResolvedValue(data);
    render(<InterviewAnalysisPanel interviewId={1} />);
    fireEvent.click(await screen.findByRole("button", { name: "Analyze answers" }));
    await waitFor(() => expect(analysisApi.start).toHaveBeenCalledWith(1, true, false, true));
  });

  it("loads only the latest saved analysis without generating anything on page load", async () => {
    render(<InterviewAnalysisPanel interviewId={1} />);
    await screen.findByText("Questions & answers");
    expect(screen.getByText("Ready")).toBeTruthy();
    expect(screen.getByLabelText("Answer score 75%")).toBeTruthy();
    expect(within(screen.getByRole("region", { name: "accuracy score" })).getByText("Unmet")).toBeTruthy();
    expect(analysisApi.read).toHaveBeenCalledWith(1);
    expect(analysisApi.start).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Analyze answers" }));
    await waitFor(() => expect(analysisApi.start).toHaveBeenCalledWith(1, true, false, false));
  });

  it("removes pairing corrections, reviews, follow-ups and analysis versions including their controls", async () => {
    render(<InterviewAnalysisPanel interviewId={1} />);
    await screen.findByText("Questions & answers");
    fireEvent.click(screen.getByText("Scoring options"));
    for (const name of [/Correct pairing/i, /merge/i, /split/i, /Save review/i, /Mark used/i, /Dismiss/i, /Link spoken question/i]) expect(screen.queryByRole("button", { name })).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
    for (const text of [/Your review/i, /An old manual review/i, /Suggested follow-ups/i, /How would you test rollback/i, /Analysis version/i, /Version 1/i, /Pairing:/i]) expect(screen.queryByText(text)).toBeNull();
    expect(screen.queryByText(/needs review/i)).toBeNull();
  });

  it("removes per-answer evidence and detailed explanations while keeping the question, answer and score", async () => {
    render(<InterviewAnalysisPanel interviewId={1} />);
    await screen.findByText("Questions & answers");
    for (const text of ["Evidence & details", "Cited transcript passages", "Full score explanations", "Answer guide points"]) expect(screen.queryByText(text)).toBeNull();
    expect(screen.queryByRole("region", { name: "Transcript evidence" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Scoring details" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Candidate · 00:03/ })).toBeNull();
    expect(screen.getByText("Explain transactions")).toBeTruthy();
    expect(screen.getByText("Transactions commit changes atomically.")).toBeTruthy();
    expect(screen.getByLabelText("Answer score 75%")).toBeTruthy();
  });

  it("shortens missing-evidence boilerplate without changing saved reasons or scores", async () => {
    const data = fixture(); const pair = data.run!.result.pairs![0];
    const transcriptReason = "The available transcript evidence does not establish this criterion. No credit is awarded for unsupported evidence.";
    const referenceReason = "Accuracy is not established by a relevant cited answer guide or technical reference. No credit is awarded for missing support.";
    pair.score!.breakdown.relevance = { ...pair.score!.breakdown.relevance, reason: transcriptReason, value: 0, status: "unmet" };
    pair.score!.breakdown.accuracy.reason = referenceReason;
    const original = JSON.stringify(data);
    vi.mocked(analysisApi.read).mockResolvedValue(data);
    render(<InterviewAnalysisPanel interviewId={1} />);
    await screen.findByText("Questions & answers");
    expect(within(screen.getByRole("region", { name: "relevance score" })).getByText("Not enough supporting evidence in the transcript.")).toBeTruthy();
    expect(within(screen.getByRole("region", { name: "accuracy score" })).getByText("No supporting guide or reference was available.")).toBeTruthy();
    expect(screen.queryByText(transcriptReason)).toBeNull();
    expect(screen.queryByText(referenceReason)).toBeNull();
    expect(JSON.stringify(data)).toBe(original);
  });

  it("retains all three scoring statuses with distinct colors and no invented score", async () => {
    const data = fixture();
    data.run!.result.pairs![0].score!.breakdown.completeness = { value: 0.5, weight: 25, status: "partially_met", reason: "Some answer points are missing." };
    vi.mocked(analysisApi.read).mockResolvedValue(data);
    render(<InterviewAnalysisPanel interviewId={1} />);
    await screen.findByText("Questions & answers");
    expect(within(screen.getByRole("region", { name: "relevance score" })).getByText("Met").className).toContain("emerald");
    expect(within(screen.getByRole("region", { name: "accuracy score" })).getByText("Unmet").className).toContain("rose");
    expect(within(screen.getByRole("region", { name: "completeness score" })).getByText("Partially met").className).toContain("amber");
    const css = readFileSync("src/index.css", "utf8");
    expect(css).toContain("grid-template-columns: repeat(auto-fit, minmax(min(100%, 15rem), 1fr))");
  });

  it("removes answer references from the question card without deleting saved reference data", async () => {
    const data = fixture(); const assessment = data.run!.result.pairs![0].assessment!;
    const ref = { reference_id: "ref", title: "Transactions guide", quote: "Commit changes atomically.", version: "v1" };
    assessment.accuracy.references = [ref]; assessment.completeness.references = [ref];
    const original = JSON.stringify(data);
    vi.mocked(analysisApi.read).mockResolvedValue(data);
    render(<InterviewAnalysisPanel interviewId={1} />);
    await screen.findByText("Questions & answers");
    expect(screen.queryByText("Transactions guide")).toBeNull();
    expect(screen.queryByText("Commit changes atomically.")).toBeNull();
    expect(JSON.stringify(data)).toBe(original);
  });

  it("removes requirement coverage from the panel without changing saved mappings", async () => {
    const data = fixture(); data.run!.result.coverage![0].statuses = ["supporting_evidence", "contradictory_evidence"];
    const saved = JSON.stringify(data);
    vi.mocked(analysisApi.read).mockResolvedValue(data);
    render(<InterviewAnalysisPanel interviewId={1} />);
    await screen.findByText("Questions & answers");
    expect(screen.queryByText("Job requirements covered")).toBeNull();
    expect(screen.queryByText("Testing")).toBeNull();
    expect(screen.queryByText("Supported by the interview · Conflicting evidence")).toBeNull();
    expect(JSON.stringify(data)).toBe(saved);
  });

  it("matches the two-sided transcript bubbles without changing saved passages or timestamps", async () => {
    const data = fixture();
    const interviewerText = "Welcome.\nCan you hear me clearly?";
    const candidateText = "Yes, thank you. " + "long-text".repeat(30);
    data.run!.snapshot.segments.push(
      { id: "intro", hash: "intro", speaker: "INTERVIEWER", text: interviewerText, start_offset_ms: 61000, end_offset_ms: 64000 },
      { id: "reply", hash: "reply", speaker: "CANDIDATE", text: candidateText, start_offset_ms: 65000, end_offset_ms: 69000 },
    );
    data.run!.result.unpaired = [{ segment_id: "intro", kind: "procedural" }, { segment_id: "reply", kind: "procedural" }];
    const saved = JSON.stringify(data);
    vi.mocked(analysisApi.read).mockResolvedValue(data);
    render(<InterviewAnalysisPanel interviewId={1} />);
    fireEvent.click(await screen.findByText("Other transcript passages"));
    const list = screen.getByRole("list", { name: "Other transcript passages" });
    const cards = within(list).getAllByRole("listitem");
    expect(cards).toHaveLength(2);
    expect(cards[0].textContent).toContain(interviewerText);
    expect(cards[1].textContent).toContain(candidateText);
    expect(list.className).toContain("hiresense-transcript-thread");
    expect(cards[0].className).toBe("hiresense-transcript-entry");
    expect(cards[0].getAttribute("data-side")).toBe("outgoing");
    expect(cards[1].getAttribute("data-side")).toBe("incoming");
    expect(cards[0].getAttribute("aria-label")).toBe("Interviewer · 01:01");
    expect(cards[1].getAttribute("aria-label")).toBe("Candidate · 01:05");
    expect(within(cards[0]).getByLabelText("At 01:01")).toBeTruthy();
    expect(within(cards[1]).getByLabelText("At 01:05")).toBeTruthy();
    expect(cards[1].querySelector("p")?.className).toBe("hiresense-transcript-copy");
    expect(cards[1].querySelector(".hiresense-transcript-bubble")?.nextElementSibling?.className).toBe("hiresense-transcript-meta");
    expect(cards[1].querySelector(".hiresense-transcript-bubble .hiresense-transcript-time")).toBeNull();
    expect(JSON.stringify(data)).toBe(saved);
    expect(analysisApi.start).not.toHaveBeenCalled();
  });

  it("hides the other passages section when there are none", async () => {
    render(<InterviewAnalysisPanel interviewId={1} />);
    await screen.findByText("Questions & answers");
    expect(screen.queryByText("Other transcript passages")).toBeNull();
  });

  it("handles missing passages and unknown speakers without inventing text or timestamps", async () => {
    const data = fixture();
    data.run!.snapshot.segments.push({ id: "unknown", hash: "unknown", speaker: "UNKNOWN", text: "A saved passage.", start_offset_ms: 10000, end_offset_ms: 12000 });
    data.run!.result.unpaired = [{ segment_id: "missing", kind: "context" }, { segment_id: "unknown", kind: "context" }];
    vi.mocked(analysisApi.read).mockResolvedValue(data);
    render(<InterviewAnalysisPanel interviewId={1} />);
    fireEvent.click(await screen.findByText("Other transcript passages"));
    const cards = within(screen.getByRole("list", { name: "Other transcript passages" })).getAllByRole("listitem");
    expect(within(cards[0]).getByText("Source unavailable")).toBeTruthy();
    expect(cards[0].querySelector("[aria-label^='At ']")).toBeNull();
    expect(cards[0].getAttribute("data-side")).toBe("neutral");
    expect(cards[1].getAttribute("data-side")).toBe("neutral");
    expect(within(cards[1]).getByText("A saved passage.")).toBeTruthy();
    expect(within(cards[1]).getByLabelText("At 00:10")).toBeTruthy();
  });

  it("does not invent a score when only an assessment is available", async () => {
    const data = fixture(); data.run!.result.pairs![0].score = undefined;
    vi.mocked(analysisApi.read).mockResolvedValue(data);
    render(<InterviewAnalysisPanel interviewId={1} />);
    await screen.findByText("Questions & answers");
    expect(screen.getAllByText("Not scored")).toHaveLength(4);
    expect(screen.queryByLabelText(/Answer score/)).toBeNull();
  });

  it("preserves explicit reanalysis and stopping automatic updates without history controls", async () => {
    vi.mocked(analysisApi.read).mockResolvedValue({ ...fixture(), automatic: true });
    render(<InterviewAnalysisPanel interviewId={1} />);
    await screen.findByText("Questions & answers"); fireEvent.click(screen.getByText("Scoring options"));
    fireEvent.click(screen.getByRole("button", { name: "Analyze again" }));
    await waitFor(() => expect(analysisApi.start).toHaveBeenCalledWith(1, true, false, true));
    await waitFor(() => expect((screen.getByRole("button", { name: "Stop live updates" }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "Stop live updates" }));
    await waitFor(() => expect(analysisApi.start).toHaveBeenCalledWith(1, false));
  });

  it("can score a finished live answer without exposing manual pairing edits", async () => {
    const data = fixture(); data.run!.result.pairs![0].state = "answer_in_progress";
    vi.mocked(analysisApi.read).mockResolvedValue(data);
    render(<InterviewAnalysisPanel interviewId={1} />);
    fireEvent.click(await screen.findByRole("button", { name: "Score this answer now" }));
    await waitFor(() => expect(analysisApi.start).toHaveBeenCalledWith(1, true, true));
  });

  it("preserves transcript gaps and analysis failures without repeating warnings", async () => {
    const data = fixture();
    data.run!.status = "failed"; data.run!.error = "The analysis service is unavailable.";
    data.run!.stale = true; data.run!.result.gaps = ["Some speech may be missing.", "Some speech may be missing."];
    vi.mocked(analysisApi.read).mockResolvedValue(data);
    render(<InterviewAnalysisPanel interviewId={1} />);
    await screen.findByText("Analysis failed");
    expect(screen.getByRole("alert").textContent).toContain("unavailable");
    expect(screen.getAllByText("Some speech may be missing.")).toHaveLength(1);
    expect(screen.getByText(/The transcript or reference material has changed/)).toBeTruthy();
  });

  it("opens exact sources and rejects a changed source revision", async () => {
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

  it("uses Unicode character offsets for exact highlighted quotes", async () => {
    const data = fixture(); data.run!.snapshot.segments[1].text = "👋 commit changes";
    vi.mocked(analysisApi.read).mockResolvedValue(data);
    render(<TranscriptCitation citation={{ ...citation, char_start: 2, char_end: 16 }} interviewId={1} runId={10} />);
    fireEvent.click(screen.getByRole("button")); await screen.findByRole("dialog");
    expect(document.querySelector("mark")?.textContent).toBe("commit changes");
  });
});
