import React, { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { apiRequest } from "../../src/api/apiClient";
import { InterviewSchedulingPanel } from "../../src/components/interviews/InterviewSchedulingPanel";

vi.mock("../../src/api/apiClient", () => ({ apiRequest: vi.fn() }));
vi.mock("../../src/components/common/DateTimePicker", () => ({ DateTimePicker: ({ label, value, onChange }: any) => <label>{label}<input value={value} onChange={e => onChange(e.target.value)} /></label> }));

it("preserves sending progress and the receipt when confirmed candidates leave the checked selection", async () => {
  const recipients = [{ application_id: 1, name: "Candidate One", email: "one@example.test", local_start: "2026-11-01T10:00:00+06:00", local_end: "2026-11-01T10:30:00+06:00", timezone: "Asia/Dhaka", duration_minutes: 30 }];
  const sender = { from_email: "interviews@example.test", reply_to: "owner@example.test" };
  vi.mocked(apiRequest).mockImplementation(async path => {
    if (path === "/interviews/selection/preview") return { selection_token: "selection", selected: recipients, excluded: [], warnings: [], recipient_count: 1 } as any;
    if (path === "/interviews/invitations/prepare") return { id: 7, confirmation_token: "confirmation", sender, recipients, recipient_count: 1 } as any;
    if (path === "/interviews/batches/7/confirm") return { id: 7, status: "sending", sender, recipients, recipient_count: 1, deliveries: [], pending: 1 } as any;
    if (path === "/interviews/batches/7") return { id: 7, status: "completed", sender, recipients, recipient_count: 1, deliveries: [], sent: 1, failed: 0, uncertain: 0 } as any;
    throw new Error(`Unexpected request: ${path}`);
  });
  function Page() {
    const [ids, setIds] = useState([1]);
    return <InterviewSchedulingPanel jobId={1} rankingRunId={10} selectedIds={ids} onUpdated={() => setIds([])} />;
  }
  render(<Page />);
  fireEvent.click(screen.getByRole("button", { name: "Preview candidate selection" }));
  fireEvent.click(await screen.findByRole("button", { name: "Continue to schedule" }));
  fireEvent.change(screen.getByLabelText("Date"), { target: { value: "2026-11-01" } });
  fireEvent.change(screen.getByLabelText("Start time"), { target: { value: "10:00" } });
  fireEvent.click(screen.getByRole("button", { name: "Preview schedule & email" }));
  fireEvent.click(await screen.findByRole("button", { name: "Confirm & send 1 invitation(s)" }));
  expect(await screen.findByText("Sending invitations…")).toBeTruthy();
  expect(await screen.findByText("Invitation results", {}, { timeout: 4000 })).toBeTruthy();
  expect(screen.getByText("1 sent · 0 failed · 0 uncertain")).toBeTruthy();
});
