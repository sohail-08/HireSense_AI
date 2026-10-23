import React from "react";
import { expect, it } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { EvidenceSummary, performanceHighlights } from "../../src/components/assessments/EvidenceSummary";

it("groups repeated highlights, shows only three, and keeps every source available", async () => {
  const points = [
    { text: "Question one: correct explanation.", summary_text: "Correct explanations", source: "source one" },
    { text: "Question two: correct explanation.", summary_text: "Correct explanations", source: "source two" },
    ...["Clear reasoning", "Relevant examples", "Complete answers", "Good explanation of rollback"].map(text => ({ text, summary_text: text, source: text + " source" })),
  ];
  const original = JSON.stringify(points);
  render(<EvidenceSummary value={{ strengths: points }} evidence={finding => <p>{finding.source}</p>} />);
  const card = screen.getByRole("region", { name: "Strengths" });
  expect(within(card).getAllByRole("listitem")).toHaveLength(3);
  expect(within(card).getAllByText("Correct explanations")).toHaveLength(1);
  expect(screen.queryByText("Question one: correct explanation.")).toBeNull();
  fireEvent.click(within(card).getByText("Sources (2)"));
  expect(await within(card).findByText("source one")).toBeTruthy();
  expect(within(card).getByText("source two")).toBeTruthy();
  fireEvent.click(within(card).getByRole("button", { name: "Show all strengths" }));
  expect(within(card).getAllByRole("listitem")).toHaveLength(5);
  expect(within(card).getByRole("button", { name: "Show fewer strengths" }).getAttribute("aria-expanded")).toBe("true");
  expect(JSON.stringify(points)).toBe(original);
});

it("keeps unknown topics separate from weaknesses and folds secondary details by default", () => {
  render(<EvidenceSummary value={{ evidence_gaps: [{ text: "Testing — not discussed." }], verification: [{ text: "Confirm unclear wording." }] }} evidence={() => null} />);
  expect(screen.getByRole("heading", { name: "Candidate performance" })).toBeTruthy();
  expect(screen.queryByText("Evidence summary")).toBeNull();
  const improve = screen.getByRole("region", { name: "Areas to improve" });
  expect(within(improve).getByText("No confirmed areas to improve.")).toBeTruthy();
  expect(within(improve).queryByText(/Testing/)).toBeNull();
  for (const name of ["Not yet assessed", "Needs checking"]) {
    const details = screen.getByRole("region", { name }).querySelector("details")!;
    expect(details.open).toBe(false);
    fireEvent.click(details.querySelector("summary")!);
    expect(details.open).toBe(true);
  }
});

it("bounds long legacy text without merging unrelated findings or losing the full explanation", async () => {
  const start = "Q1 · Relevance, accuracy: " + "A long original explanation ".repeat(15);
  const findings = [{ text: start + "First limitation." }, { text: start + "Different limitation." }];
  expect(performanceHighlights(findings)).toHaveLength(2);
  expect(performanceHighlights(findings).every(item => item.text.length <= 150)).toBe(true);
  render(<EvidenceSummary value={{ weaknesses: findings }} evidence={() => null} />);
  const card = screen.getByRole("region", { name: "Areas to improve" });
  expect(card.textContent).not.toContain("Q1");
  fireEvent.click(within(card).getAllByText("Sources")[0]);
  expect(await within(card).findByText(findings[0].text)).toBeTruthy();
});
