import React from "react";
import { readFileSync } from "node:fs";
import { afterEach, beforeEach, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

let styles: HTMLStyleElement;
beforeEach(() => {
  // JSDOM does not implement cascade layers. Exercise the actual base rules
  // without their wrapper; the production build checks Tailwind integration.
  const source = readFileSync("src/index.css", "utf8");
  const base = source.split("@layer base {")[1].split("/* LiveKit")[0].trim();
  styles = document.createElement("style");
  styles.textContent = base.slice(0, base.lastIndexOf("}"));
  document.head.appendChild(styles);
});
afterEach(() => styles.remove());

it("uses a hand cursor for enabled interactive controls", () => {
  render(<>
    <button>Action</button><a href="/jobs">Jobs</a>
    <details><summary>Details</summary></details>
    <select aria-label="Job"><option>Example</option></select>
    <label htmlFor="name">Name label</label><input id="name" />
    <label><input type="checkbox" aria-label="Select candidate" />Select candidate label</label>
    <input type="radio" aria-label="Choice" /><input type="file" aria-label="Upload" />
    <input type="submit" value="Submit" /><input type="range" aria-label="Volume" />
    <div role="button" tabIndex={0}>Custom action</div>
  </>);
  for (const control of [
    screen.getByText("Action"), screen.getByText("Jobs"), screen.getByText("Details"),
    screen.getByLabelText("Job"), screen.getByText("Name label"), screen.getByLabelText("Select candidate"),
    screen.getByText("Select candidate label"), screen.getByLabelText("Choice"), screen.getByLabelText("Upload"),
    screen.getByDisplayValue("Submit"), screen.getByLabelText("Volume"), screen.getByText("Custom action"),
  ]) expect(getComputedStyle(control).cursor).toBe("pointer");
});

it("keeps disabled controls unavailable, including fieldset and ARIA states", () => {
  render(<>
    <button disabled>Disabled action</button>
    <select disabled aria-label="Disabled select"><option>Example</option></select>
    <input disabled type="checkbox" aria-label="Disabled checkbox" />
    <fieldset disabled><button>Fieldset action</button></fieldset>
    <div role="button" aria-disabled="true">Unavailable action</div>
    <a href="/jobs" aria-disabled="true">Unavailable link</a>
    <label>Unavailable choice<input type="radio" disabled /></label>
  </>);
  for (const control of [
    screen.getByText("Disabled action"), screen.getByLabelText("Disabled select"),
    screen.getByLabelText("Disabled checkbox"), screen.getByText("Fieldset action"),
    screen.getByText("Unavailable action"), screen.getByText("Unavailable link"), screen.getByText("Unavailable choice"),
  ]) expect(getComputedStyle(control).cursor).toBe("not-allowed");
});

it("does not turn text entry fields or plain content into hand cursors", () => {
  render(<><input aria-label="Email" type="email" /><textarea aria-label="Message" /><p>Plain content</p><a>Not a link</a></>);
  for (const control of [screen.getByLabelText("Email"), screen.getByLabelText("Message"), screen.getByText("Plain content"), screen.getByText("Not a link")]) {
    expect(getComputedStyle(control).cursor).not.toBe("pointer");
  }
});
