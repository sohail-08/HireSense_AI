import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { InterviewCopilotPanel, type CopilotContext } from "../../src/components/interviews/InterviewCopilotPanel";
import { MeetingTabs } from "../../src/components/interviews/MeetingTabs";
import { readFileSync } from "node:fs";
import { SupervisorChatPanel } from "../../src/components/jobs/SupervisorChatPanel";
const api = vi.hoisted(() => vi.fn());
vi.mock("../../src/components/interviews/IdentityOverview", () => ({ IdentityOverview: () => null }));
vi.mock("../../src/api/apiClient", () => ({ apiRequest: api }));
const context: CopilotContext = {
  candidate: { name: "Test Candidate", email: "test@example.test", phone: "01234", location: null,
    skills: ["React"], qualifications: ["BSc in computing"], experience_years: 3, recent_roles: ["Engineer · Example"] },
  job_title: "Frontend Engineer", required_skills: ["React"], preferred_skills: [], qualifications: [],
  minimum_experience: 2, selection_criteria: [], messages: [], version: 0,
};
beforeEach(() => {
  api.mockReset(); api.mockResolvedValue(context);
  Object.defineProperty(HTMLElement.prototype, "scrollTo", { configurable: true, value: vi.fn() });
});

test("selecting a suggested task sends only its saved ID and opens the practical workspace after success", async () => {
  const option = { id: "a".repeat(32), title: "Fix a validation bug", summary: "Validate two supplied API inputs.", duration_minutes: 10, response_type: "code" };
  const suggested = { ...context, version: 1, messages: [{ role: "assistant" as const, content: "Choose a task.", questions: [], sources: [], task_options: [option] }] };
  api.mockResolvedValueOnce(suggested).mockResolvedValueOnce({ ...suggested, version: 2, open_practical_exercise: true,
    messages: [...suggested.messages, { role: "assistant", content: "Private task created.", questions: [], sources: [], task_created: true }] });
  const open = vi.fn();
  render(<InterviewCopilotPanel interviewId={12} activeTab="assistant" onOpenPractical={open} />);
  await screen.findByText("Fix a validation bug");
  expect(open).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Use this task" }));
  await waitFor(() => expect(open).toHaveBeenCalledOnce());
  expect(JSON.parse(api.mock.calls[1][1].body)).toEqual({ message: "Create task: Fix a validation bug", version: 1, selected_task_id: option.id });
  expect((screen.getByRole("button", { name: "Use this task" }) as HTMLButtonElement).disabled).toBe(true);
});

test("a failed task creation does not navigate or consume the suggestion", async () => {
  const option = { id: "a".repeat(32), title: "Quote a price", summary: "Calculate a total.", duration_minutes: 5, response_type: "text" };
  api.mockResolvedValueOnce({ ...context, version: 1, messages: [{ role: "assistant", content: "Choose a task.", questions: [], sources: [], task_options: [option] }] })
    .mockRejectedValueOnce(new Error("This task changed. Reload."));
  const open = vi.fn();
  render(<InterviewCopilotPanel interviewId={12} activeTab="assistant" onOpenPractical={open} />);
  fireEvent.click(await screen.findByRole("button", { name: "Use this task" }));
  await screen.findByText("This task changed. Reload.");
  expect(open).not.toHaveBeenCalled();
  expect((screen.getByRole("button", { name: "Use this task" }) as HTMLButtonElement).disabled).toBe(false);
});
test("shows saved candidate details and requests cited questions for this interview", async () => {
  api.mockResolvedValueOnce(context).mockResolvedValueOnce({ ...context, version: 1, messages: [{ role: "assistant", content: "Try this question.",
    questions: [{ question: "How do you manage React state?", requirement: "React", source_ids: [7] }],
    sources: [{ chunk_id: 7, document_title: "Synthetic React questions", excerpt: "State management question" }] }] });
  const user = userEvent.setup(); render(<InterviewCopilotPanel interviewId={12} />);
  await screen.findByText("Test Candidate");
  expect(screen.getByLabelText("Private interview assistance")).toBeTruthy();
  expect(screen.getByText("test@example.test")).toBeTruthy();
  expect(screen.getByText("Experience: 3 years")).toBeTruthy();
  await user.click(screen.getByRole("tab", { name: "Assistant", exact: true }));
  await user.click(screen.getByRole("button", { name: "Suggest questions" }));
  await screen.findByText("How do you manage React state?");
  expect(api.mock.calls[1][0]).toBe("/interview-rooms/12/copilot");
  expect(JSON.parse(api.mock.calls[1][1].body).version).toBe(0);
  await user.click(screen.getByText("Knowledge sources (1)"));
  expect(screen.getByText("State management question")).toBeTruthy();
  expect(screen.queryByText("Not shared with the candidate")).toBeNull();
});

test("uses the central chatbot identity and compact composer while preserving conversation space", async () => {
  const user = userEvent.setup(); render(<InterviewCopilotPanel interviewId={12} fill />);
  await user.click(await screen.findByRole("tab", { name: "Assistant", exact: true }));
  const assistant = screen.getByRole("region", { name: "Interview assistant" });
  expect(within(assistant).getByRole("heading", { name: "HireSense assistant" })).toBeTruthy();
  expect(within(assistant).getByText("Private interview support")).toBeTruthy();
  expect(screen.queryByText("Only you can see this panel")).toBeNull();
  expect(screen.queryByText("Questions and follow-ups, just for you")).toBeNull();
  const log = within(assistant).getByRole("log", { name: "Interview assistant conversation" });
  expect(log.nextElementSibling?.className).toContain("hiresense-assistant-composer");
  const input = within(assistant).getByRole("textbox", { name: "Ask the interview assistant" });
  const send = within(assistant).getByRole("button", { name: "Send message" });
  expect(input.parentElement).toBe(send.parentElement);
  expect(input.getAttribute("rows")).toBe("1");
  expect(input.getAttribute("maxLength")).toBe("2000");
  expect(send.querySelector("svg")).toBeTruthy();
  expect((send as HTMLButtonElement).disabled).toBe(true);
  const css = readFileSync("src/index.css", "utf8");
  expect(css).toMatch(/\.hiresense-meeting-tabs-fill \.hiresense-interview-assistant > \[role="log"\] \{ flex: 1; min-height: 0; height: auto; max-height: none;/);
  expect(css).toMatch(/\.hiresense-meeting-tabs-fill \.hiresense-interview-assistant > form \{ flex-shrink: 0;/);
});
test("keeps a failed message for retry and displays the failure", async () => {
  api.mockResolvedValueOnce(context).mockRejectedValueOnce(new Error("Assistant unavailable"));
  const user = userEvent.setup(); render(<InterviewCopilotPanel interviewId={12} />);
  await user.click(await screen.findByRole("tab", { name: "Assistant", exact: true }));
  const input = await screen.findByLabelText("Ask the interview assistant");
  await user.type(input, "Ask about React"); await user.click(screen.getByRole("button", { name: "Send message" }));
  expect((await screen.findByRole("alert")).textContent).toContain("Assistant unavailable");
  expect((input as HTMLTextAreaElement).value).toBe("Ask about React");
});
test("does not send duplicate requests while generating", async () => {
  api.mockResolvedValueOnce(context).mockImplementationOnce(() => new Promise(() => {}));
  const user = userEvent.setup(); render(<InterviewCopilotPanel interviewId={12} />);
  await user.click(await screen.findByRole("tab", { name: "Assistant", exact: true }));
  await user.click(await screen.findByRole("button", { name: "Suggest questions" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Send message" }).hasAttribute("disabled")).toBe(true));
  expect(screen.getByRole("status").textContent).toBe("Working");
  expect((screen.getByLabelText("Ask the interview assistant") as HTMLTextAreaElement).disabled).toBe(true);
  expect(api).toHaveBeenCalledTimes(2);
});

test("keeps private assistant drafts and inner tab selection when switching workspace groups", async () => {
  const user = userEvent.setup(); render(<MeetingTabs fill variant="segmented" label="Workspace panel" tabs={[
    { id: "private", label: "Candidate & assistant", content: <InterviewCopilotPanel interviewId={12} fill /> },
    { id: "transcript", label: "Transcript & analysis", content: <p>Transcript tools</p> },
  ]} />);
  await user.click(await screen.findByRole("tab", { name: "Assistant", exact: true }));
  await user.type(screen.getByLabelText("Ask the interview assistant"), "Ask about testing");
  await user.click(screen.getByRole("tab", { name: "Transcript & analysis" }));
  expect(screen.queryByRole("tab", { name: "Assistant", exact: true })).toBeNull();
  await user.click(screen.getByRole("tab", { name: "Candidate & assistant" }));
  expect(screen.getByRole("tab", { name: "Assistant", exact: true }).getAttribute("aria-selected")).toBe("true");
  expect((screen.getByLabelText("Ask the interview assistant") as HTMLTextAreaElement).value).toBe("Ask about testing");
  await user.click(screen.getByRole("tab", { name: "Candidate info" }));
  expect(screen.getByRole("heading", { name: "Candidate information" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Send message" })).toBeNull();
  await user.click(screen.getByRole("tab", { name: "Assistant", exact: true }));
  expect((screen.getByLabelText("Ask the interview assistant") as HTMLTextAreaElement).value).toBe("Ask about testing");
  expect(api).toHaveBeenCalledTimes(1);
});

test("groups real job requirements into styled skills, experience, qualifications and selection criteria", async () => {
  api.mockResolvedValue({ ...context, preferred_skills: ["Accessibility"], qualifications: ["Relevant degree or equivalent experience"], selection_criteria: ["Explain testing choices"] });
  const user = userEvent.setup(); render(<InterviewCopilotPanel interviewId={12} fill />);
  await user.click(await screen.findByText("Job requirements"));
  const required = screen.getByRole("region", { name: "Required skills" });
  expect(within(required).getByText("React").className).toContain("rounded-lg");
  expect(within(screen.getByRole("region", { name: "Preferred skills" })).getByText("Accessibility")).toBeTruthy();
  expect(screen.getByText("2+ years")).toBeTruthy();
  expect(screen.getByText("Relevant degree or equivalent experience")).toBeTruthy();
  expect(screen.getByText("Explain testing choices")).toBeTruthy();
  expect(screen.getByLabelText("Private interview assistance").className).toContain("hiresense-private-panel");
  expect(screen.getByRole("tabpanel", { name: "Candidate info" }).parentElement?.className).toContain("hiresense-meeting-tabs-fill");
});

test("matches the central chatbot's bubbles, identity, input and icon button", async () => {
  const messages = [{ role: "user" as const, content: "A private question", questions: [], sources: [] },
    { role: "assistant" as const, content: "A private answer", questions: [], sources: [] }];
  api.mockResolvedValue({ ...context, messages });
  const user = userEvent.setup();
  render(<><SupervisorChatPanel open phaseLabel="Interview scheduling" messages={messages} loading={false} input="" placeholder="Message" onOpen={vi.fn()} onClose={vi.fn()} onInputChange={vi.fn()} onSend={vi.fn()} onNewSession={vi.fn()} /><InterviewCopilotPanel interviewId={12} fill /></>);
  await user.click(await screen.findByRole("tab", { name: "Assistant", exact: true }));
  const central = screen.getByRole("dialog", { name: "HireSense supervisor" });
  const interview = screen.getByRole("region", { name: "Interview assistant" });
  for (const text of ["A private question", "A private answer"]) {
    const source = within(central).getByText(text).parentElement!;
    const target = within(interview).getByText(text).parentElement!;
    expect(target.className).toBe(source.className);
    expect(target.parentElement?.className).toBe(source.parentElement?.className);
  }
  expect(interview.querySelector("header")?.className).toBe(central.querySelector("header")?.className);
  const centralInput = within(central).getByRole("textbox");
  const interviewInput = within(interview).getByRole("textbox");
  expect(interviewInput.className).toBe(centralInput.className);
  expect(interviewInput.parentElement?.className).toBe(centralInput.parentElement?.className);
  expect(within(interview).getByRole("button", { name: "Send message" }).className).toBe(within(central).getByRole("button", { name: "Send message" }).className);
  expect(within(interview).queryByRole("button", { name: "New workflow" })).toBeNull();
  expect(api).toHaveBeenCalledTimes(1);
});

test("sends with Enter, keeps Shift+Enter for new lines and ignores IME composition", async () => {
  const user = userEvent.setup(); render(<InterviewCopilotPanel interviewId={12} />);
  await user.click(await screen.findByRole("tab", { name: "Assistant", exact: true }));
  const input = screen.getByLabelText("Ask the interview assistant");
  await user.click(input); await user.keyboard("{Enter}");
  expect(api).toHaveBeenCalledTimes(1);
  await user.type(input, "Ask about React");
  fireEvent.keyDown(input, { key: "Enter", isComposing: true });
  expect(api).toHaveBeenCalledTimes(1);
  await user.keyboard("{Shift>}{Enter}{/Shift}and testing");
  expect((input as HTMLTextAreaElement).value).toBe("Ask about React\nand testing");
  expect(api).toHaveBeenCalledTimes(1);
  await user.keyboard("{Enter}");
  await waitFor(() => expect(api).toHaveBeenCalledTimes(2));
  expect(api.mock.calls[1][0]).toBe("/interview-rooms/12/copilot");
  expect(JSON.parse(api.mock.calls[1][1].body)).toEqual({ message: "Ask about React\nand testing", version: 0 });
  await waitFor(() => expect((input as HTMLTextAreaElement).value).toBe(""));
});
