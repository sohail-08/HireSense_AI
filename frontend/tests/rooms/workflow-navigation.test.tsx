import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { Link, MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { revealSection } from "../../src/components/common/useSectionReveal";
import { workflowDestination } from "../../src/components/assistant/workflowDestination";
import { SupervisorProvider, useSupervisor } from "../../src/components/assistant/SupervisorProvider";
import { WorkflowReveal } from "../../src/components/assistant/WorkflowReveal";
import { apiRequest } from "../../src/api/apiClient";
import type { SupervisorChatResponse } from "../../src/types";

vi.mock("../../src/api/apiClient", () => ({ apiRequest: vi.fn(), ApiError: class extends Error {} }));
const draft = { id: 7, status: "draft" } as SupervisorChatResponse["job_description"];
function reply(patch: Partial<SupervisorChatResponse> = {}): SupervisorChatResponse {
  return { session_id: "test", phase: "job_description_draft", route: "generate_job_description", outcome: "success", assistant_message: "Draft ready", messages: [],
    requirement_profile_id: null, requirement_state: {} as SupervisorChatResponse["requirement_state"], job_description: draft, job_posting: null,
    refresh_required: false, sync_result: null, screening_batch: null, ...patch };
}
beforeEach(() => {
  sessionStorage.clear(); vi.clearAllMocks();
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: vi.fn() });
  Object.defineProperty(HTMLElement.prototype, "scrollTo", { configurable: true, value: vi.fn() });
  Object.defineProperty(window, "matchMedia", { configurable: true, value: vi.fn(() => ({ matches: false })) });
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
});

it("maps structured job, screening, scheduling and report outcomes to explicit destinations", () => {
  expect(workflowDestination(reply())).toEqual({ path: "/interviewer/jobs", section: "job-description-review" });
  expect(workflowDestination(reply({ route: "job_posting", job_description: { ...draft!, status: "approved" } }))).toEqual({ path: "/interviewer/jobs", section: "job-publication" });
  expect(workflowDestination(reply({ route: "screen_candidates", screening_batch: { job_posting_id: 22 } as any }), 11)).toEqual({ path: "/interviewer/assessments?job=22", section: "cv-screening" });
  expect(workflowDestination(reply({ route: "interviews", phase: "interview_schedule" }))).toEqual({ path: "/interviewer/schedule-interviews", section: "interview-candidates" });
  expect(workflowDestination(reply({ route: "interviews", phase: "interview_sent" }))).toEqual({ path: "/interviewer/interviews", section: "interview-list" });
  expect(workflowDestination(reply({ route: "sync_responses", sync_result: {} as any }))).toEqual({ path: "/interviewer/candidates", section: "candidate-list" });
  expect(workflowDestination(reply({ route: "candidate_assessments", assessment_links: [{ label: "Report", path: "/interviewer/reports?run=5&application=7&ignored=1" }] }))).toEqual({ path: "/interviewer/reports?application=7&run=5", section: "assessment-details" });
  expect(workflowDestination(reply({ route: "candidate_assessments", assessment_links: [{ label: "Ranking", path: "/interviewer/reports?job=11" }] }))).toEqual({ path: "/interviewer/reports?job=11", section: "final-ranking" });
});

it("does not redirect for help, missing draft details, failures or unsafe report URLs", () => {
  for (const patch of [{ route: "help" }, { job_description: null }, { outcome: "failure" as const },
    ...["https://outside.test/interviewer/reports?run=1", "javascript:alert(1)", "http://[", "/interviewer/jobs"].map(path => ({ route: "candidate_assessments", assessment_links: [{ label: "Report", path }] }))]) {
    expect(workflowDestination(reply(patch))).toBeUndefined();
  }
});

it("reveals delayed content once, respects reduced motion and preserves input focus", async () => {
  Object.defineProperty(window, "matchMedia", { configurable: true, value: () => ({ matches: true }) });
  const view = render(<><input aria-label="Continue typing" /><div /></>);
  screen.getByLabelText("Continue typing").focus();
  const cancel = revealSection("late-result");
  expect(HTMLElement.prototype.scrollIntoView).not.toHaveBeenCalled();
  view.rerender(<><input aria-label="Continue typing" /><section id="late-result">Ready</section></>);
  await waitFor(() => expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalledOnce());
  expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalledWith({ behavior: "auto", block: "start", inline: "nearest" });
  expect(document.activeElement).toBe(screen.getByLabelText("Continue typing"));
  view.rerender(<><input aria-label="Continue typing" /><section id="late-result">Background update</section></>);
  expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalledOnce(); cancel();
});

it("waits for hidden tabs and never scrolls behind an open dialog", async () => {
  const view = render(<><div hidden><section id="hidden-result">Result</section></div><dialog open>Confirmation</dialog></>);
  const cancel = revealSection("hidden-result");
  await act(async () => { await new Promise(resolve => window.setTimeout(resolve, 25)); });
  expect(HTMLElement.prototype.scrollIntoView).not.toHaveBeenCalled();
  view.rerender(<><div><section id="hidden-result">Result</section></div><dialog open>Confirmation</dialog></>);
  await act(async () => { await new Promise(resolve => window.setTimeout(resolve, 25)); });
  expect(HTMLElement.prototype.scrollIntoView).not.toHaveBeenCalled();
  view.rerender(<div><section id="hidden-result">Result</section></div>);
  await waitFor(() => expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalledOnce()); cancel();
});

it("cancels a pending reveal when the user starts scrolling", async () => {
  const view = render(<div />);
  const cancel = revealSection("cancelled-result");
  fireEvent.wheel(window);
  view.rerender(<section id="cancelled-result">Result</section>);
  await act(async () => { await new Promise(resolve => window.setTimeout(resolve, 25)); });
  expect(HTMLElement.prototype.scrollIntoView).not.toHaveBeenCalled(); cancel();
});

it("waits for loading content above the target to settle before revealing it", async () => {
  const view = render(<div data-workflow-ready="false"><section id="stable-result">Loading layout</section></div>);
  const cancel = revealSection("stable-result");
  await act(async () => { await new Promise(resolve => window.setTimeout(resolve, 25)); });
  expect(HTMLElement.prototype.scrollIntoView).not.toHaveBeenCalled();
  view.rerender(<div data-workflow-ready="true"><section id="stable-result">Ready</section></div>);
  await waitFor(() => expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalledOnce()); cancel();
});

function Commands() {
  const { sendMessage } = useSupervisor();
  const location = useLocation();
  return <><p data-testid="location">{location.pathname}{location.hash}</p><button onClick={() => void sendMessage("Draft a job")}>Run command</button><Link to="/interviewer/candidates">Browse candidates</Link></>;
}
function page(start = "/interviewer/candidates") {
  return render(<MemoryRouter initialEntries={[start]}><SupervisorProvider><WorkflowReveal /><Commands /><Routes>
    <Route path="/interviewer/jobs" element={<section id="job-description-review">Job review</section>} />
    <Route path="/interviewer/candidates" element={<section id="candidate-list">Candidates</section>} />
  </Routes></SupervisorProvider></MemoryRouter>);
}

it("redirects an explicit assistant command to its section and dismisses the mobile overlay", async () => {
  vi.mocked(apiRequest).mockResolvedValue(reply());
  page(); fireEvent.click(screen.getByRole("button", { name: "Run command" }));
  await screen.findByText("Job review");
  await waitFor(() => expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalledOnce());
  expect(screen.getByTestId("location").textContent).toBe("/interviewer/jobs#job-description-review");
  expect(document.getElementById("supervisor-chat-panel")?.getAttribute("aria-hidden")).toBe("true");
});

it("restores a saved chat without redirecting or scrolling", async () => {
  sessionStorage.setItem("hiresense_supervisor_session_id", "test");
  vi.mocked(apiRequest).mockResolvedValue(reply()); page();
  await waitFor(() => expect(apiRequest).toHaveBeenCalledWith("/supervisor/sessions/test"));
  expect(screen.getByTestId("location").textContent).toBe("/interviewer/candidates");
  expect(HTMLElement.prototype.scrollIntoView).not.toHaveBeenCalled();
});

it("keeps the desktop assistant open and can reveal the same destination for a later command", async () => {
  Object.defineProperty(window, "matchMedia", { configurable: true, value: (query: string) => ({ matches: query === "(min-width: 1024px)" }) });
  vi.mocked(apiRequest).mockResolvedValue(reply()); page();
  fireEvent.click(screen.getByRole("button", { name: "Run command" }));
  await waitFor(() => expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalledOnce());
  expect(document.getElementById("supervisor-chat-panel")?.getAttribute("aria-hidden")).toBe("false");
  fireEvent.click(screen.getByRole("button", { name: "Run command" }));
  await waitFor(() => expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalledTimes(2));
});

it("does not hijack navigation when a slow assistant response arrives", async () => {
  let complete!: (value: SupervisorChatResponse) => void;
  vi.mocked(apiRequest).mockImplementation(() => new Promise(resolve => { complete = resolve as typeof complete; }));
  page("/interviewer/jobs"); fireEvent.click(screen.getByRole("button", { name: "Run command" }));
  fireEvent.click(screen.getByRole("link", { name: "Browse candidates" }));
  await act(async () => complete(reply()));
  expect(screen.getByTestId("location").textContent).toBe("/interviewer/candidates");
  expect(HTMLElement.prototype.scrollIntoView).not.toHaveBeenCalled();
});
