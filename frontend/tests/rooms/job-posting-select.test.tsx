import React, { useState } from "react";
import { expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { JobPostingSelect } from "../../src/components/candidates/JobPostingSelect";

const jobs = [
  { id: 7, title: "Machine Learning Engineer", application_count: 1 },
  { id: 6, title: "Frontend Engineer", application_count: 4 },
  { id: 9, title: "Frontend Engineer", application_count: 0 },
];

function Example() {
  const [value, setValue] = useState(7);
  return <><JobPostingSelect jobs={jobs} value={value} loading={false} onChange={setValue} /><button>Outside action</button></>;
}

it("renders a styled popup outside clipped cards and identifies the selected job", () => {
  render(<Example />);
  const trigger = screen.getByRole("combobox", { name: "Job posting" });
  expect(trigger.textContent).toContain("Machine Learning Engineer");
  expect(trigger.textContent).toContain("Posting #7 · 1 candidate");
  fireEvent.click(trigger);
  const list = screen.getByRole("listbox", { name: "Job posting" });
  expect(list.parentElement).toBe(document.body);
  expect(list.style.position).toBe("fixed");
  expect(within(list).getAllByRole("option")).toHaveLength(3);
  expect(within(list).getByRole("option", { selected: true }).textContent).toContain("Posting #7");
  fireEvent.click(within(list).getByRole("option", { name: /Posting #6/ }));
  expect(screen.queryByRole("listbox")).toBeNull();
  expect(trigger.textContent).toContain("Frontend Engineer");
  expect(trigger.textContent).toContain("Posting #6 · 4 candidates");
});

it("supports arrows, Home, End, Enter and Escape without changing jobs on navigation", async () => {
  render(<Example />);
  const trigger = screen.getByRole("combobox"); trigger.focus();
  fireEvent.keyDown(trigger, { key: "ArrowDown" });
  fireEvent.keyDown(trigger, { key: "ArrowDown" });
  expect(trigger.getAttribute("aria-activedescendant")).toBe(screen.getByRole("option", { name: /Posting #6/ }).id);
  expect(trigger.textContent).toContain("Posting #7");
  fireEvent.keyDown(trigger, { key: "End" });
  fireEvent.keyDown(trigger, { key: "Enter" });
  expect(trigger.textContent).toContain("Posting #9");
  await waitFor(() => expect(document.activeElement).toBe(trigger));
  fireEvent.keyDown(trigger, { key: "Home" });
  fireEvent.keyDown(trigger, { key: "Escape" });
  expect(screen.queryByRole("listbox")).toBeNull();
  expect(trigger.textContent).toContain("Posting #9");
  expect(document.activeElement).toBe(trigger);
});

it("supports type-ahead and lets Tab move to the next control", async () => {
  const user = userEvent.setup();
  render(<Example />);
  const trigger = screen.getByRole("combobox"); trigger.focus();
  await user.keyboard("fro");
  expect(trigger.getAttribute("aria-activedescendant")).toBe(screen.getByRole("option", { name: /Posting #6/ }).id);
  await user.tab();
  expect(screen.queryByRole("listbox")).toBeNull();
  expect(document.activeElement).toBe(screen.getByRole("button", { name: "Outside action" }));
  expect(trigger.textContent).toContain("Posting #7");
});

it("dismisses on outside clicks and focus changes", async () => {
  render(<Example />);
  const trigger = screen.getByRole("combobox");
  fireEvent.click(trigger); fireEvent.pointerDown(document.body);
  expect(screen.queryByRole("listbox")).toBeNull();
  fireEvent.click(trigger); screen.getByRole("button", { name: "Outside action" }).focus();
  await waitFor(() => expect(screen.queryByRole("listbox")).toBeNull());
});

it("disables loading and empty selectors", () => {
  const change = vi.fn();
  const view = render(<JobPostingSelect jobs={jobs} value={7} loading onChange={change} />);
  expect((screen.getByRole("combobox") as HTMLButtonElement).disabled).toBe(true);
  view.rerender(<JobPostingSelect jobs={[]} loading={false} onChange={change} />);
  expect(screen.getByText("No job postings available")).toBeTruthy();
  fireEvent.click(screen.getByRole("combobox"));
  expect(screen.queryByRole("listbox")).toBeNull();
  expect(change).not.toHaveBeenCalled();
});

it("keeps the popup inside the viewport and opens upward when space below is limited", () => {
  render(<Example />);
  const trigger = screen.getByRole("combobox");
  vi.spyOn(trigger, "getBoundingClientRect").mockReturnValue({ left: window.innerWidth - 80, top: window.innerHeight - 100, bottom: window.innerHeight - 40, width: 300 } as DOMRect);
  fireEvent.click(trigger);
  const popup = screen.getByRole("listbox");
  expect(popup.style.bottom).toBe("108px");
  expect(Number.parseFloat(popup.style.left) + Number.parseFloat(popup.style.width)).toBeLessThanOrEqual(window.innerWidth - 12);
});
