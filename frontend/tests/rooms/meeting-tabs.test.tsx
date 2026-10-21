import React, { useEffect, useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { MeetingTabs } from "../../src/components/interviews/MeetingTabs";

it("supports keyboard navigation and preserves mounted panel state", () => {
  const mounted = vi.fn();
  function Draft() { const [text, setText] = useState(""); useEffect(() => { mounted(); }, []); return <input aria-label="Draft" value={text} onChange={event => setText(event.target.value)} />; }
  render(<MeetingTabs label="Example" tabs={[{ id: "draft", label: "Transcript", content: <Draft /> }, { id: "other", label: "Analysis", content: <p>Analysis content</p> }]} />);
  fireEvent.change(screen.getByLabelText("Draft"), { target: { value: "Keep my draft" } });
  fireEvent.keyDown(screen.getByRole("tab", { name: "Transcript" }), { key: "ArrowRight" });
  expect(screen.getByRole("tab", { name: "Analysis" }).getAttribute("aria-selected")).toBe("true");
  expect(screen.getAllByRole("tabpanel")).toHaveLength(1);
  expect(document.activeElement).toBe(screen.getByRole("tab", { name: "Analysis" }));
  fireEvent.keyDown(screen.getByRole("tab", { name: "Analysis" }), { key: "Home" });
  expect((screen.getByLabelText("Draft") as HTMLInputElement).value).toBe("Keep my draft");
  expect(mounted).toHaveBeenCalledTimes(1);
});
