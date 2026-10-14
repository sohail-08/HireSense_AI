import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { InterviewCopilotPanel, type CopilotContext } from "../../src/components/interviews/InterviewCopilotPanel";
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
  expect(screen.getByText("test@example.test")).toBeTruthy();
  expect(screen.getByText("Experience: 3 years")).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "Suggest questions" }));
  await screen.findByText("How do you manage React state?");
  expect(api.mock.calls[1][0]).toBe("/interview-rooms/12/copilot");
  expect(JSON.parse(api.mock.calls[1][1].body).version).toBe(0);
  await user.click(screen.getByText("Knowledge sources (1)"));
  expect(screen.getByText("State management question")).toBeTruthy();
  expect(screen.getByText("Not shared with the candidate")).toBeTruthy();
});
test("keeps a failed message for retry and displays the failure", async () => {
  api.mockResolvedValueOnce(context).mockRejectedValueOnce(new Error("Assistant unavailable"));
  const user = userEvent.setup(); render(<InterviewCopilotPanel interviewId={12} />);
  const input = await screen.findByLabelText("Ask the interview assistant");
  await user.type(input, "Ask about React"); await user.click(screen.getByRole("button", { name: "Send" }));
  expect((await screen.findByRole("alert")).textContent).toContain("Assistant unavailable");
  expect((input as HTMLTextAreaElement).value).toBe("Ask about React");
});
test("does not send duplicate requests while generating", async () => {
  api.mockResolvedValueOnce(context).mockImplementationOnce(() => new Promise(() => {}));
  const user = userEvent.setup(); render(<InterviewCopilotPanel interviewId={12} />);
  await user.click(await screen.findByRole("button", { name: "Suggest questions" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Send" }).hasAttribute("disabled")).toBe(true));
  expect(api).toHaveBeenCalledTimes(2);
});
