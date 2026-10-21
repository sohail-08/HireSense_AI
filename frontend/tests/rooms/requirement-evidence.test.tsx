import React from "react";
import { expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { RequirementEvidence } from "../../src/components/candidates/RequirementEvidence";

it("shows a short reason and focused excerpts without a full-source option", () => {
  const long = "Private contact details and unrelated skills. Engineer | Example | Jan 2022 - Present. Built APIs.";
  render(<RequirementEvidence requirement={{ name: "At least 3 years of relevant experience", status: "met",
    reason: "Employment dates support at least 3 years 9 months of relevant work, meeting the 3-year minimum.",
    evidence: [{ block_id: "page-1", locator: "PDF page 1", quote: long }],
    evidence_preview: [{ block_id: "page-1", locator: "PDF page 1", quote: "Engineer | Example | Jan 2022 - Present.", omitted_before: true, omitted_after: true }],
  }} />);
  expect(screen.getByText(/Employment dates support at least 3 years 9 months/)).toBeTruthy();
  expect(screen.queryByText(/View full source/)).toBeNull();
  expect(screen.queryByText(long, { exact: false })).toBeNull();
  expect(screen.getByText("Met").className).toContain("emerald");
  const preview = document.querySelector("article > blockquote");
  expect(preview?.textContent).toContain("Engineer | Example | Jan 2022 - Present.");
  expect(preview?.textContent).not.toContain("Private contact");
  expect(preview?.className).toContain("whitespace-pre-line");
});

it("uses honest reasoning for unmet outcomes with no evidence", () => {
  render(<RequirementEvidence requirement={{ name: "Docker", status: "unmet", evidence: [] }} />);
  expect(screen.getByText("The CV does not provide enough evidence for this requirement.")).toBeTruthy();
  expect(screen.getByText("No supporting CV example found.")).toBeTruthy();
  expect(screen.getByText("Unmet").className).toContain("rose");
  expect(screen.queryByText(/View full source/)).toBeNull();
});

it("shows a concise saved citation for legacy results without full passages", () => {
  render(<RequirementEvidence requirement={{ name: "React", status: "partially_met",
    evidence: [{ block_id: "old", locator: "DOCX paragraph 2", quote: "Original saved CV evidence." }] }} />);
  expect(screen.getByText(/supports part of this requirement/)).toBeTruthy();
  expect(screen.getByText(/Original saved CV evidence/)).toBeTruthy();
  expect(screen.getByText("Partially met").className).toContain("amber");
  expect(screen.queryByText(/View full source/)).toBeNull();
});

it("bounds legacy citations and keeps only two short excerpts", () => {
  const long = "Relevant example. ".repeat(50);
  render(<RequirementEvidence requirement={{ name: "React", status: "met", evidence: [
    { block_id: "1", locator: "PDF page 1", quote: long },
    { block_id: "2", locator: "PDF page 2", quote: long },
    { block_id: "3", locator: "PDF page 3", quote: long },
  ] }} />);
  expect(document.querySelectorAll("blockquote")).toHaveLength(2);
  expect(document.querySelector("blockquote")?.textContent?.length).toBeLessThan(280);
  expect(screen.queryByText("PDF page 3")).toBeNull();
});
