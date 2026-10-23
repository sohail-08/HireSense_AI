import React, { useEffect, useState } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { MeetingTabs } from "../../src/components/interviews/MeetingTabs";

it("allows programmatic task navigation without unmounting other panels", () => {
  function Workspace() {
    const [active, setActive] = useState("assistant");
    return <MeetingTabs label="Workspace" activeId={active} onActiveChange={setActive} tabs={[
      { id: "assistant", label: "Assistant", content: <button onClick={() => setActive("practical")}>Task created</button> },
      { id: "practical", label: "Practical", content: <p>Private task draft</p> },
    ]} />;
  }
  render(<Workspace />);
  fireEvent.click(screen.getByRole("button", { name: "Task created" }));
  expect(screen.getByRole("tab", { name: "Practical" }).getAttribute("aria-selected")).toBe("true");
  expect(screen.getByRole("tabpanel", { name: "Practical" })).toBeTruthy();
  fireEvent.keyDown(screen.getByRole("tab", { name: "Practical" }), { key: "Home" });
  expect(screen.getByRole("button", { name: "Task created" })).toBeTruthy();
});

it.each(["underline", "segmented"] as const)("supports keyboard navigation and preserves mounted panel state with %s tabs", (variant) => {
  const mounted = vi.fn();
  function Draft() { const [text, setText] = useState(""); useEffect(() => { mounted(); }, []); return <input aria-label="Draft" value={text} onChange={event => setText(event.target.value)} />; }
  render(<MeetingTabs variant={variant} label="Example" tabs={[{ id: "draft", label: "Transcript", content: <Draft /> }, { id: "other", label: "Analysis", content: <p>Analysis content</p> }]} />);
  fireEvent.change(screen.getByLabelText("Draft"), { target: { value: "Keep my draft" } });
  fireEvent.keyDown(screen.getByRole("tab", { name: "Transcript" }), { key: "ArrowRight" });
  expect(screen.getByRole("tab", { name: "Analysis" }).getAttribute("aria-selected")).toBe("true");
  expect(screen.getAllByRole("tabpanel")).toHaveLength(1);
  expect(document.activeElement).toBe(screen.getByRole("tab", { name: "Analysis" }));
  fireEvent.keyDown(screen.getByRole("tab", { name: "Analysis" }), { key: "Home" });
  expect((screen.getByLabelText("Draft") as HTMLInputElement).value).toBe("Keep my draft");
  expect(mounted).toHaveBeenCalledTimes(1);
});

it("follows live text in the nested transcript pane, not the non-scrolling workspace wrapper", () => {
  render(<MeetingTabs fill variant="segmented" label="Workspace" tabs={[
    { id: "transcript-group", label: "Transcript group", content: <MeetingTabs fill label="Transcript tools" tabs={[
      { id: "transcript", label: "Live text", content: <div data-scroll-mode="panel" data-has-lines="true" data-auto-follow="true">Live words</div> },
    ]} /> },
    { id: "private", label: "Private tools", content: <p>Private content</p> },
  ]} />);
  const outer = screen.getByRole("tabpanel", { name: "Transcript group" });
  const inner = screen.getByRole("tabpanel", { name: "Live text" });
  Object.defineProperty(inner, "scrollHeight", { configurable: true, value: 1000 });
  fireEvent.click(screen.getByRole("tab", { name: "Private tools" }));
  fireEvent.click(screen.getByRole("tab", { name: "Transcript group" }));
  expect(inner.scrollTop).toBe(1000);
  expect(outer.scrollTop).toBe(0);
});

it("measures and updates the sticky group bar height for page-scrolling review tabs", () => {
  let resize = () => {};
  const disconnect = vi.fn();
  const bounds = vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ height: 60 } as DOMRect);
  vi.stubGlobal("ResizeObserver", class {
    constructor(callback: () => void) { resize = callback; }
    observe = vi.fn();
    disconnect = disconnect;
  });
  try {
    const view = render(<MeetingTabs pageScroll variant="segmented" label="Review groups" tabs={[
      { id: "transcript", label: "Transcript", content: <p>Review content</p> },
    ]} />);
    const root = screen.getByRole("tablist", { name: "Review groups" }).parentElement!;
    expect(root.style.getPropertyValue("--meeting-primary-tabs-height")).toBe("60px");
    bounds.mockReturnValue({ height: 80 } as DOMRect);
    act(() => resize());
    expect(root.style.getPropertyValue("--meeting-primary-tabs-height")).toBe("80px");
    view.unmount();
    expect(disconnect).toHaveBeenCalledTimes(1);
  } finally { bounds.mockRestore(); vi.unstubAllGlobals(); }
});
