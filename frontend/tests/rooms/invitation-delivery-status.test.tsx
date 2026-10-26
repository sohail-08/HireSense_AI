import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { InvitationDeliveryStatus, type InvitationDeliveryBatch } from "../../src/components/interviews/InvitationDeliveryStatus";

const recipient = { application_id: 1, name: "Samira Ahmed", email: "samira@example.test" };
const delivery = { id: 9, application_id: 1, status: "sent", attempts: 1, error_category: null, retryable: false, in_flight: false };
const base: InvitationDeliveryBatch = { status: "completed", recipient_count: 1, recipients: [recipient], deliveries: [delivery], sent: 1, failed: 0, uncertain: 0 };
const metric = (label: string) => screen.getByLabelText(`${label} invitations`).querySelector("p")!.textContent;

it("shows an in-flight uncertain SMTP claim as sending, not an unconfirmed result", () => {
  render(<InvitationDeliveryStatus busy={false} onRetry={vi.fn()} batch={{ ...base, status: "sending", sent: 0, uncertain: 1, deliveries: [{ ...delivery, status: "uncertain", in_flight: true, retryable: true }] }} />);
  expect(screen.getByRole("heading", { name: "Sending invitations…" })).toBeTruthy();
  expect(within(screen.getByRole("list", { name: "Candidate invitation deliveries" })).getByText("Sending")).toBeTruthy();
  expect(screen.getByText("samira@example.test")).toBeTruthy();
  expect(metric("Pending")).toBe("1"); expect(metric("Unconfirmed")).toBe("0");
  expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("0");
  expect(screen.queryByText(/not retried automatically/)).toBeNull();
  expect(screen.queryByRole("button", { name: /Retry/ })).toBeNull();
});

it("distinguishes sent, queued, failed and unconfirmed invitations with accurate progress", () => {
  const onRetry = vi.fn();
  const batch = { ...base, status: "sending", recipient_count: 4,
    recipients: [recipient, ...[2, 3, 4].map(id => ({ application_id: id, name: `Candidate ${id}` }))],
    deliveries: [delivery,
      { ...delivery, id: 10, application_id: 2, status: "failed", attempts: 3, error_category: "smtp_not_configured", retryable: true },
      { ...delivery, id: 11, application_id: 3, status: "uncertain", retryable: true },
      { ...delivery, id: 12, application_id: 4, status: "pending" }],
  };
  const view = render(<InvitationDeliveryStatus batch={batch} busy={false} onRetry={onRetry} />);
  for (const name of ["Sent", "Pending", "Failed", "Unconfirmed"]) expect(metric(name)).toBe("1");
  expect(screen.getByText("3 of 4 processed")).toBeTruthy();
  expect(screen.getByRole("progressbar").getAttribute("aria-valuemax")).toBe("4");
  expect(screen.getByText("Email settings need to be configured.")).toBeTruthy();
  expect(screen.getByText(/not retried automatically/)).toBeTruthy();
  const retries = screen.getAllByRole("button", { name: /Retry failed delivery/ });
  expect(retries).toHaveLength(1);
  fireEvent.click(retries[0]); expect(onRetry).toHaveBeenCalledWith(10, 3);
  view.rerender(<InvitationDeliveryStatus batch={batch} busy onRetry={onRetry} />);
  expect((screen.getByRole("button", { name: /Retry failed delivery/ }) as HTMLButtonElement).disabled).toBe(true);
});

it("shows a completed success state only when every invitation is sent", () => {
  render(<InvitationDeliveryStatus batch={base} busy={false} onRetry={vi.fn()} />);
  expect(screen.getByRole("heading", { name: "Invitation results" })).toBeTruthy();
  expect(screen.getByText("Completed")).toBeTruthy();
  expect(screen.getByText("Your interview invitations have been sent.")).toBeTruthy();
  expect(metric("Sent")).toBe("1"); expect(metric("Pending")).toBe("0");
  expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("1");
});

it("marks finished problem deliveries for review without reporting all emails sent", () => {
  render(<InvitationDeliveryStatus batch={{ ...base, deliveries: [{ ...delivery, status: "uncertain" }] }} busy={false} onRetry={vi.fn()} />);
  expect(screen.getByText("Review needed")).toBeTruthy();
  expect(screen.queryByText("Completed")).toBeNull();
  expect(metric("Sent")).toBe("0"); expect(metric("Unconfirmed")).toBe("1");
  expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("1");
});

it("uses aggregate counts when legacy delivery details are unavailable", () => {
  render(<InvitationDeliveryStatus batch={{ ...base, deliveries: [] }} busy={false} onRetry={vi.fn()} />);
  expect(metric("Sent")).toBe("1");
  expect(screen.getByText("Completed")).toBeTruthy();
});

it("does not invent success or expose internal identifiers and raw error categories", () => {
  render(<InvitationDeliveryStatus batch={{ ...base, recipients: [], deliveries: [{ ...delivery, status: "failed", error_category: "private_provider_diagnostic" }] }} busy={false} onRetry={vi.fn()} />);
  expect(screen.getByText("Candidate invitation")).toBeTruthy();
  expect(screen.queryByText(/private_provider_diagnostic|Application #/)).toBeNull();
  expect(screen.queryByText("Your interview invitations have been sent.")).toBeNull();
});
