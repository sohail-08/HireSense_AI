import { fireEvent, screen, within } from "@testing-library/react";

export function selectOption(label: string, option: string | RegExp) {
  fireEvent.click(screen.getByRole("combobox", { name: label }));
  fireEvent.click(within(screen.getByRole("listbox", { name: label })).getByRole("option", { name: option }));
}
