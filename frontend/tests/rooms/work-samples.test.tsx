import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, test, vi } from "vitest";
import { ApiError } from "../../src/api/apiClient";
import { CandidateWorkSample } from "../../src/components/interviews/CandidateWorkSample";
import { WorkSamplePanel } from "../../src/components/interviews/WorkSamplePanel";
import { WorkSampleReview } from "../../src/components/interviews/WorkSampleReview";
import { PracticalAssessments } from "../../src/components/assessments/PracticalAssessments";
import { type ExerciseState, type ExerciseTask } from "../../src/components/interviews/workSampleApi";

const api = vi.hoisted(() => ({ candidateRead: vi.fn(), ready: vi.fn(), candidateSave: vi.fn(), read: vi.fn(), save: vi.fn(),
  templates: vi.fn(), template: vi.fn(), draft: vi.fn(), action: vi.fn(), assess: vi.fn(), review: vi.fn() }));
vi.mock("../../src/components/interviews/workSampleApi", async original => ({ ...await original<any>(), workSampleApi: api }));

const task: ExerciseTask = { title: "Customer quotation", instructions: "Prepare a quotation for two units using the catalogue.", materials: "Basic costs 100 per unit.",
  deliverables: "A quote and explanation.", duration_minutes: 15, tools_policy: "Use supplied materials only. No AI or outside help.", response_type: "text",
  criteria: [{ id: "correctness", title: "Correctness", description: "The quote uses the supplied prices.", weight: 100 }] };
function state(status = "running", content = "", revision = 0): ExerciseState {
  return { server_now: new Date().toISOString(), exercise: { id: 1, task, task_hash: "task-hash", status, version: 3, approved_at: new Date().toISOString(),
    attempt: { id: 10, number: 1, status, content, explanation: "", revision, remaining_seconds: 900,
      deadline_at: status === "running" ? new Date(Date.now() + 900000).toISOString() : null, started_at: null, saved_at: null, finished_at: null, submission_hash: null },
    attempts: [], assessments: [], events: [] } };
}
const evaluation = { summary: "The quotation uses the supplied price.", score: 100, findings: [{ criterion_id: "correctness", label: "met" as const,
  reason: "Two units cost 200.", evidence: [{ field: "content" as const, line_start: 1, line_end: 1, quote: "200" }] }] };
beforeEach(() => {
  api.candidateRead.mockResolvedValue(state()); api.read.mockResolvedValue(state("draft")); api.templates.mockResolvedValue([]);
  api.ready.mockResolvedValue(state("ready")); api.candidateSave.mockImplementation(async (_id, rev, content, explanation, submit) => {
    const result = state(submit ? "submitted" : "running", content, rev + 1); result.exercise!.attempt!.explanation = explanation; return result;
  });
  api.save.mockResolvedValue(state("draft")); api.action.mockResolvedValue(state("shared"));
});

test("candidate readiness does not start the timer or reveal an assessment", async () => {
  api.candidateRead.mockResolvedValue(state("shared"));
  render(<CandidateWorkSample />);
  const button = await screen.findByRole("button", { name: "I’m ready" });
  expect(screen.queryByLabelText("Exercise time remaining")).toBeNull();
  fireEvent.click(button);
  await screen.findByRole("button", { name: "Ready · waiting for interviewer" });
  expect(api.ready).toHaveBeenCalledWith(10);
  expect(screen.queryByRole("button", { name: "Start exercise" })).toBeNull();
  expect(screen.queryByLabelText("Practical assessment findings")).toBeNull();
});

test("autosave keeps exact text and sends the expected revision", async () => {
  render(<CandidateWorkSample />);
  const input = await screen.findByLabelText("Your response");
  fireEvent.change(input, { target: { value: "  exact\ntext  " } });
  await waitFor(() => expect(api.candidateSave).toHaveBeenCalledWith(10, 0, "  exact\ntext  ", "", false), { timeout: 2500 });
  await screen.findByText("Saved", { exact: true });
  expect((input as HTMLTextAreaElement).value).toBe("  exact\ntext  ");
});

test("a delayed save receipt cannot overwrite newer typing", async () => {
  let complete!: (value: ExerciseState) => void;
  api.candidateSave.mockImplementationOnce(() => new Promise(resolve => { complete = resolve; }));
  render(<CandidateWorkSample />);
  const input = await screen.findByLabelText("Your response");
  fireEvent.change(input, { target: { value: "first" } });
  fireEvent.click(screen.getByRole("button", { name: "Save now" }));
  await waitFor(() => expect(api.candidateSave).toHaveBeenCalled());
  fireEvent.change(input, { target: { value: "newer typing" } });
  await act(async () => complete(state("running", "first", 1)));
  expect((input as HTMLTextAreaElement).value).toBe("newer typing");
  fireEvent.click(screen.getByRole("button", { name: "Save now" }));
  await waitFor(() => expect(api.candidateSave).toHaveBeenLastCalledWith(10, 1, "newer typing", "", false));
});

test("submission requires confirmation, includes unsaved text and locks the response", async () => {
  render(<CandidateWorkSample />);
  const input = await screen.findByLabelText("Your response");
  fireEvent.change(input, { target: { value: "My final response" } });
  fireEvent.click(screen.getByRole("button", { name: "Submit exercise" }));
  expect(api.candidateSave).not.toHaveBeenCalled();
  fireEvent.click(await screen.findByRole("button", { name: "Confirm submission" }));
  await waitFor(() => expect(api.candidateSave).toHaveBeenCalledWith(10, 0, "My final response", "", true));
  await screen.findByRole("heading", { name: "Submission received" });
  expect((input as HTMLTextAreaElement).readOnly).toBe(true);
  expect(screen.queryByRole("button", { name: "Submit exercise" })).toBeNull();
});

test("revision conflicts preserve local text and require explicit recovery", async () => {
  api.candidateSave.mockRejectedValue(new ApiError("Changed in another tab", 409));
  render(<CandidateWorkSample />);
  const input = await screen.findByLabelText("Your response");
  fireEvent.change(input, { target: { value: "Keep my unsaved text" } });
  api.candidateRead.mockResolvedValue(state("running", "Another tab's saved text", 1));
  fireEvent.click(screen.getByRole("button", { name: "Save now" }));
  await screen.findByText("Changed in another tab");
  expect((input as HTMLTextAreaElement).value).toBe("Keep my unsaved text");
  expect((screen.getByRole("button", { name: "Submit exercise" }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Load saved version" }));
  expect(await screen.findByText(/Copy your unsaved changes first/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Keep local text" }));
  expect((input as HTMLTextAreaElement).value).toBe("Keep my unsaved text");
});

test("a pause during autosave preserves text for resumption rather than treating it as a competing writer", async () => {
  api.candidateSave.mockRejectedValueOnce(new ApiError("The exercise is not running", 409));
  render(<CandidateWorkSample />);
  const input = await screen.findByLabelText("Your response");
  fireEvent.change(input, { target: { value: "Work interrupted by a pause" } });
  api.candidateRead.mockResolvedValue(state("paused"));
  fireEvent.click(screen.getByRole("button", { name: "Save now" }));
  await screen.findByText(/The interviewer paused the exercise/);
  expect((input as HTMLTextAreaElement).value).toBe("Work interrupted by a pause");
  expect(screen.queryByRole("button", { name: "Load saved version" })).toBeNull();
  expect((input as HTMLTextAreaElement).readOnly).toBe(true);
});

test("ending access keeps unsaved work visible without permitting more saves", async () => {
  const view = render(<CandidateWorkSample />);
  const input = await screen.findByLabelText("Your response");
  fireEvent.change(input, { target: { value: "Unsaved before the interview ended" } });
  view.rerender(<CandidateWorkSample closed />);
  expect((input as HTMLTextAreaElement).value).toBe("Unsaved before the interview ended");
  expect((input as HTMLTextAreaElement).readOnly).toBe(true);
  expect(screen.getByText(/Any unsaved text remains visible/)).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Submit exercise" })).toBeNull();
  expect(api.candidateSave).not.toHaveBeenCalled();
});

test("interviewer approves and shares the saved task in two explicit steps", async () => {
  render(<WorkSamplePanel interviewId={7} />);
  await screen.findByDisplayValue("Customer quotation");
  expect(api.action).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Approve & share task" }));
  fireEvent.click(await screen.findByRole("button", { name: "Approve & share", exact: true }));
  await waitFor(() => expect(api.save).toHaveBeenCalledWith(7, task, 3));
  expect(api.action).toHaveBeenCalledWith(7, 3, "share");
  await screen.findByText(/Waiting for the candidate to read/);
  expect(screen.queryByLabelText("Task title")).toBeNull();
});

test("a private task cannot silently adopt a newer revision while being edited", async () => {
  api.read.mockResolvedValueOnce(state("draft"));
  render(<WorkSamplePanel interviewId={7} />);
  const title = await screen.findByLabelText("Task title");
  fireEvent.change(title, { target: { value: "My edited task" } });
  const newer = state("draft"); newer.exercise!.version = 9;
  api.read.mockResolvedValue(newer);
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 2600)); });
  fireEvent.click(screen.getByRole("button", { name: "Save private draft" }));
  await waitFor(() => expect(api.save).toHaveBeenCalledWith(7, expect.objectContaining({ title: "My edited task" }), 3));
});

test("human approval requires a review note and preserves evidence", async () => {
  const approve = vi.fn();
  render(<WorkSampleReview task={task} busy={false} onApprove={approve} assessment={{ id: 3, attempt_id: 10, status: "draft", result: evaluation,
    approved_result: null, review_reason: null, approved_at: null, approved_by: null, error: null }} />);
  const button = screen.getByRole("button", { name: "Approve assessment" });
  expect((button as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(screen.getByLabelText("Review note"), { target: { value: "Checked the quote against the catalogue." } });
  fireEvent.click(button);
  expect(approve).toHaveBeenCalledWith(evaluation, "Checked the quote against the catalogue.");
  expect(screen.getByText("AI assessment draft")).toBeTruthy();
});

test("reports distinguish unapproved practical work from the existing final score", () => {
  render(<MemoryRouter><PracticalAssessments values={[{ interview_id: 7, exercise_id: 1, title: task.title, task, task_hash: "hash", attempt: 1,
    status: "submitted", content: "200", explanation: "100 times 2", submission_hash: "submission", review_status: "draft", assessment: null,
    approved_at: null, approved_by: null }]} /></MemoryRouter>);
  expect(screen.getByText(/not included in the 40% CV/)).toBeTruthy();
  expect(screen.getByText(/No interviewer-approved assessment yet/)).toBeTruthy();
  expect(screen.queryByLabelText("Practical assessment findings")).toBeNull();
  expect(screen.getByRole("link", { name: /Open interview workspace/ }).getAttribute("href")).toBe("/interviews/7/console");
});
