import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { InterviewCopilotPanel, type CopilotContext } from "../../src/components/interviews/InterviewCopilotPanel";
import { MeetingTabs } from "../../src/components/interviews/MeetingTabs";
import { readFileSync } from "node:fs";
const api = vi.hoisted(() => vi.fn());
vi.mock("../../src/api/apiClient", () => ({ apiRequest: api }));
const context: CopilotContext = {
  candidate: { name: "Test Candidate", email: "test@example.test", phone: "01234", location: null,
    skills: ["React"], qualifications: ["BSc in computing"], experience_years: 3, recent_roles: ["Engineer · Example"] },
  job_title: "Frontend Engineer", required_skills: ["React"], preferred_skills: [], qualifications: [],
  minimum_experience: 2, selection_criteria: [], messages: [], version: 0,
};
beforeEach(() => { api.mockReset(); api.mockResolvedValue(context); });
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

test("prioritizes conversation space with no repeated header and a single-row composer", async () => {
  const user = userEvent.setup(); render(<InterviewCopilotPanel interviewId={12} fill />);
  await user.click(await screen.findByRole("tab", { name: "Assistant", exact: true }));
  const assistant = screen.getByRole("region", { name: "Interview assistant" });
  expect(assistant.querySelector("header")).toBeNull();
  expect(screen.queryByText("Only you can see this panel")).toBeNull();
  expect(screen.queryByText("Questions and follow-ups, just for you")).toBeNull();
  const log = within(assistant).getByRole("log", { name: "Interview assistant conversation" });
  expect(log.nextElementSibling?.className).toContain("hiresense-assistant-composer");
  const input = within(assistant).getByRole("textbox", { name: "Ask the interview assistant" });
  const send = within(assistant).getByRole("button", { name: "Send" });
  expect(input.parentElement).toBe(send.parentElement);
  expect(input.getAttribute("rows")).toBe("2");
  const css = readFileSync("src/index.css", "utf8");
  expect(css).toMatch(/\.hiresense-meeting-tabs-fill \.hiresense-interview-assistant > \[role="log"\] \{ flex: 1; min-height: 0; height: auto; max-height: none;/);
  expect(css).toMatch(/\.hiresense-meeting-tabs-fill \.hiresense-interview-assistant > form \{ flex-shrink: 0;/);
});
test("keeps a failed message for retry and displays the failure", async () => {
  api.mockResolvedValueOnce(context).mockRejectedValueOnce(new Error("Assistant unavailable"));
  const user = userEvent.setup(); render(<InterviewCopilotPanel interviewId={12} />);
  await user.click(await screen.findByRole("tab", { name: "Assistant", exact: true }));
  const input = await screen.findByLabelText("Ask the interview assistant");
  await user.type(input, "Ask about React"); await user.click(screen.getByRole("button", { name: "Send" }));
  expect((await screen.findByRole("alert")).textContent).toContain("Assistant unavailable");
  expect((input as HTMLTextAreaElement).value).toBe("Ask about React");
});
test("does not send duplicate requests while generating", async () => {
  api.mockResolvedValueOnce(context).mockImplementationOnce(() => new Promise(() => {}));
  const user = userEvent.setup(); render(<InterviewCopilotPanel interviewId={12} />);
  await user.click(await screen.findByRole("tab", { name: "Assistant", exact: true }));
  await user.click(await screen.findByRole("button", { name: "Suggest questions" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Send" }).hasAttribute("disabled")).toBe(true));
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
  expect(screen.queryByRole("button", { name: "Send" })).toBeNull();
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
