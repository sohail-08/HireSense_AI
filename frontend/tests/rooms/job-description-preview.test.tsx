import React from "react";
import { expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { JobDescriptionPreview } from "../../src/components/jobs/JobDescriptionPreview";

it("formats saved headings, bullets and emphasis without repeating the title", () => {
  render(<JobDescriptionPreview title="Backend Engineer" content={"# Backend Engineer\n\nBuild reliable services.\n\n## Responsibilities\n- Build **secure APIs**\n- Test with `Pytest`\n\n## Skills\n- Python\n- SQL"} />);
  const preview = screen.getByRole("article", { name: "Job description preview" });
  expect(within(preview).getAllByRole("heading", { name: "Backend Engineer" })).toHaveLength(1);
  expect(within(preview).getByRole("heading", { name: "Responsibilities" })).toBeTruthy();
  expect(within(preview).getAllByRole("listitem")).toHaveLength(4);
  expect(within(preview).getByText("secure APIs").tagName).toBe("STRONG");
  expect(within(preview).getByText("Pytest").tagName).toBe("CODE");
  expect(preview.textContent).not.toContain("##");
  expect(preview.textContent).not.toContain("**");
});

it("uses manually saved text instead of old structured fields and preserves plain paragraphs", () => {
  const text = "Custom description.\nWork with designers.\n\nA second paragraph.";
  render(<JobDescriptionPreview title="Manual role" content={text} />);
  expect(screen.getByText(/Custom description/).textContent).toBe("Custom description.\nWork with designers.");
  expect(screen.getByText("A second paragraph.")).toBeTruthy();
});

it("preserves numbered steps and headings that differ from the job title", () => {
  render(<JobDescriptionPreview title="Backend Engineer" content={"# About our team\nA small team.\n\n## Selection\n3. Technical conversation\n4. Final interview"} />);
  expect(screen.getByRole("heading", { name: "About our team" })).toBeTruthy();
  expect(screen.getByRole("list").getAttribute("start")).toBe("3");
  expect(screen.getAllByRole("listitem")).toHaveLength(2);
});

it("escapes untrusted HTML and never creates executable links or images", () => {
  const content = '<script>alert("test")</script>\n<img src="x" onerror="alert(1)">\n[click](javascript:alert(1))';
  const { container } = render(<JobDescriptionPreview title="Untrusted description" content={content} />);
  expect(container.querySelector("script, img, a")).toBeNull();
  expect(screen.getByRole("article").textContent).toContain('<img src="x"');
});
