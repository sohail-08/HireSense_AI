import React, { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { StyledSelect } from "../../src/components/common/StyledSelect";

const options = [{ value: "", label: "Choose one", disabled: true }, { value: "a", label: "Alpha" },
  { value: "disabled", label: "Unavailable", disabled: true }, { value: "b", label: "Beta", description: "More details" }];

it("skips disabled options and commits the correct value with the keyboard", () => {
  const change = vi.fn();
  render(<StyledSelect label="Example" value="" options={options} onChange={change} />);
  const control = screen.getByRole("combobox", { name: "Example" });
  fireEvent.keyDown(control, { key: "ArrowDown" });
  fireEvent.keyDown(control, { key: "ArrowDown" });
  expect(control.getAttribute("aria-activedescendant")).toBe(screen.getByRole("option", { name: "Beta More details" }).id);
  fireEvent.keyDown(control, { key: "Enter" });
  expect(change).toHaveBeenCalledWith("b");
  expect(screen.queryByRole("listbox")).toBeNull();
});

it("supports multiple choices without Ctrl/Cmd and keeps the menu open", async () => {
  function Example() {
    const [values, setValues] = useState<string[]>([]);
    return <><StyledSelect multiple label="Passages" value={values} options={options} onChange={setValues} /><output>{values.join(",")}</output></>;
  }
  const user = userEvent.setup(); render(<Example />);
  const control = screen.getByRole("combobox", { name: "Passages" });
  await user.click(control);
  await user.click(screen.getByRole("option", { name: "Alpha" }));
  await user.click(screen.getByRole("option", { name: "Beta More details" }));
  expect(screen.getByRole("listbox").getAttribute("aria-multiselectable")).toBe("true");
  expect(screen.getAllByRole("option", { selected: true })).toHaveLength(2);
  expect(screen.getByText("a,b")).toBeTruthy();
  await user.click(screen.getByRole("option", { name: "Alpha" }));
  expect(screen.getByText("1 selected")).toBeTruthy();
  expect(screen.getByRole("status").textContent).toBe("b");
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("listbox")).toBeNull();
});

it("never selects disabled options by pointer", () => {
  const change = vi.fn();
  render(<StyledSelect label="Example" value="a" options={options} onChange={change} />);
  fireEvent.click(screen.getByRole("combobox"));
  fireEvent.click(screen.getByRole("option", { name: "Unavailable" }));
  expect(change).not.toHaveBeenCalled();
});

it("respects a disabled fieldset and does not reopen when re-enabled", () => {
  const change = vi.fn();
  const view = render(<fieldset disabled><StyledSelect label="Example" value="a" options={options} onChange={change} /></fieldset>);
  fireEvent.click(screen.getByRole("combobox"));
  expect(screen.queryByRole("listbox")).toBeNull();
  view.rerender(<StyledSelect label="Example" value="a" options={options} onChange={change} />);
  fireEvent.click(screen.getByRole("combobox"));
  expect(screen.getByRole("listbox")).toBeTruthy();
  view.rerender(<StyledSelect label="Example" value="a" options={options} disabled onChange={change} />);
  expect(screen.queryByRole("listbox")).toBeNull();
  view.rerender(<StyledSelect label="Example" value="a" options={options} onChange={change} />);
  expect(screen.queryByRole("listbox")).toBeNull();
});

it("keeps menus inside their dialog's top layer", () => {
  render(<dialog open aria-label="Example dialog"><StyledSelect label="Example" value="a" options={options} onChange={() => {}} /></dialog>);
  const dialog = screen.getByRole("dialog");
  fireEvent.click(within(dialog).getByRole("combobox"));
  expect(within(dialog).getByRole("listbox").parentElement).toBe(dialog);
});
