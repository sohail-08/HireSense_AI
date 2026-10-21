import React, { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { DateTimePicker } from "../../src/components/common/DateTimePicker";
import { selectOption } from "./selectHelpers";

beforeEach(() => {
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value() { this.setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value() { this.removeAttribute("open"); } });
});

function Example({ kind = "date", initial = "2028-02-28" }: { kind?: "date" | "time"; initial?: string }) {
  const [value, setValue] = useState(initial);
  return <><DateTimePicker label="Choose" kind={kind} value={value} onChange={setValue} /><output aria-label="Saved value">{value}</output></>;
}

it("selects a leap day and stores an unchanged ISO date", () => {
  render(<Example />);
  const trigger = screen.getByRole("button", { name: "Choose" });
  fireEvent.click(trigger);
  fireEvent.click(screen.getByRole("button", { name: "February 29, 2028" }));
  expect(screen.getByLabelText("Saved value").textContent).toBe("2028-02-29");
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(document.activeElement).toBe(trigger);
});

it("validates manually entered dates and supports month navigation and clear", () => {
  render(<Example />); fireEvent.click(screen.getByRole("button", { name: "Choose" }));
  fireEvent.click(screen.getByRole("button", { name: "Next month" }));
  expect(screen.getByRole("grid", { name: "March 2028" })).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Enter date (YYYY-MM-DD)"), { target: { value: "2027-02-29" } });
  expect(screen.getByRole("alert")).toBeTruthy();
  expect((screen.getByRole("button", { name: "Use date" }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(screen.getByLabelText("Enter date (YYYY-MM-DD)"), { target: { value: "2029-01-02" } });
  fireEvent.click(screen.getByRole("button", { name: "Use date" }));
  expect(screen.getByLabelText("Saved value").textContent).toBe("2029-01-02");
  fireEvent.click(screen.getByRole("button", { name: "Choose" })); fireEvent.click(screen.getByRole("button", { name: "Clear" }));
  expect(screen.getByLabelText("Saved value").textContent).toBe("");
});

it("moves calendar focus across months with the keyboard", async () => {
  render(<Example initial="2028-02-29" />); fireEvent.click(screen.getByRole("button", { name: "Choose" }));
  fireEvent.keyDown(screen.getByRole("button", { name: "February 29, 2028" }), { key: "ArrowRight" });
  await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "March 1, 2028" })));
  fireEvent.click(document.activeElement!);
  expect(screen.getByLabelText("Saved value").textContent).toBe("2028-03-01");
});

it.each([["AM", "00:07"], ["PM", "12:07"]])("converts 12 %s correctly and commits only after Use time", (period, raw) => {
  render(<Example kind="time" initial="08:00" />); fireEvent.click(screen.getByRole("button", { name: "Choose" }));
  selectOption("Hour", "12"); selectOption("Minute", "07"); selectOption("AM / PM", period);
  expect(screen.getByLabelText("Saved value").textContent).toBe("08:00");
  expect(screen.getByRole("combobox", { name: "Hour" }).closest("dialog")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Use time" }));
  expect(screen.getByLabelText("Saved value").textContent).toBe(raw);
});

it("cancels time drafts without changing the value and never reopens after disabling", () => {
  const change = vi.fn();
  const view = render(<DateTimePicker label="Choose" kind="time" value="13:32" onChange={change} />);
  fireEvent.click(screen.getByRole("button", { name: "Choose" })); selectOption("Hour", "04");
  fireEvent(screen.getByRole("dialog"), new Event("cancel", { bubbles: true, cancelable: true }));
  expect(change).not.toHaveBeenCalled(); expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Choose" }));
  view.rerender(<DateTimePicker label="Choose" kind="time" value="13:32" onChange={change} disabled />);
  expect(screen.queryByRole("dialog")).toBeNull();
  view.rerender(<DateTimePicker label="Choose" kind="time" value="13:32" onChange={change} />);
  expect(screen.queryByRole("dialog")).toBeNull();
});
