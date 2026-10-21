import React from "react";
import { expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { RequirementEvidence } from "../../src/components/candidates/RequirementEvidence";

it("shows a short reason and focused excerpts while full passages stay collapsed", () => {
  const long = "Private contact details and unrelated skills. Engineer | Example | Jan 2022 - Present. Built APIs.";
  render(<RequirementEvidence requirement={{ name: "At least 3 years of relevant experience", status: "met",
    reason: "Employment dates support at least 3 years 9 months of relevant work, meeting the 3-year minimum.",
    evidence: [{ block_id: "page-1", locator: "PDF page 1", quote: long }],
    evidence_preview: [{ block_id: "page-1", locator: "PDF page 1", quote: "Engineer | Example | Jan 2022 - Present.", omitted_before: true, omitted_after: true }],
  }} />);
  expect(screen.getByText(/Employment dates support at least 3 years 9 months/)).toBeTruthy();
  const details = screen.getByText("View full source passages (1)").closest("details");
  expect(details?.open).toBe(false);
  expect(details?.textContent).toContain(long);
  const preview = document.querySelector("article > blockquote");
  expect(preview?.textContent).toContain("Engineer | Example | Jan 2022 - Present.");
  expect(preview?.textContent).not.toContain("Private contact");
  expect(preview?.className).toContain("whitespace-pre-line");
});

it("uses honest reasoning for unmet outcomes with no evidence", () => {
  render(<RequirementEvidence requirement={{ name: "Docker", status: "unmet", evidence: [] }} />);
  expect(screen.getByText("The CV does not provide enough evidence for this requirement.")).toBeTruthy();
  expect(screen.getByText("No verified supporting evidence was found in this CV.")).toBeTruthy();
  expect(screen.queryByText(/View full source/)).toBeNull();
});

it("keeps legacy full evidence available without showing a wall of text by default", () => {
  render(<RequirementEvidence requirement={{ name: "React", status: "partially_met",
    evidence: [{ block_id: "old", locator: "DOCX paragraph 2", quote: "Original saved CV evidence." }] }} />);
  expect(screen.getByText(/supports part of this requirement/)).toBeTruthy();
  expect(screen.getByText("View full source passages (1)").closest("details")?.open).toBe(false);
});
