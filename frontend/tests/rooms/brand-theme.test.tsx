import { expect, it } from "vitest";
import { readFileSync } from "node:fs";

const css = readFileSync("src/index.css", "utf8");
function color(token: string) {
  const value = css.match(new RegExp(`--color-${token}:\\s*(#[0-9a-f]{6});`, "i"))?.[1];
  if (!value) throw new Error(`Theme color missing: ${token}`);
  return value;
}
function luminance(hex: string) {
  const linear = [1, 3, 5].map(offset => {
    const channel = parseInt(hex.slice(offset, offset + 2), 16) / 255;
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
}
function contrast(foreground: string, background: string) {
  const values = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (values[0] + 0.05) / (values[1] + 0.05);
}

it("defines the reference-inspired indigo palette globally for existing utilities", () => {
  expect(color("blue-600")).toBe("#403795");
  expect(css).toContain("@theme {");
  for (const shade of [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950]) {
    expect(color(`blue-${shade}`)).toMatch(/^#[0-9a-f]{6}$/);
  }
  expect(css).toContain("body { background-color: var(--color-slate-100); color: var(--color-slate-900); }");
  expect(css).toContain("accent-color: var(--color-blue-600)");
});

it("keeps primary text, links and selected states above normal-text contrast requirements", () => {
  for (const shade of [500, 600, 700, 800, 900]) {
    expect(contrast("#ffffff", color(`blue-${shade}`))).toBeGreaterThanOrEqual(4.5);
  }
  expect(contrast(color("blue-800"), color("blue-50"))).toBeGreaterThanOrEqual(4.5);
  expect(contrast(color("blue-700"), "#ffffff")).toBeGreaterThanOrEqual(4.5);
  expect(contrast(color("slate-500"), color("slate-100"))).toBeGreaterThanOrEqual(4.5);
  expect(contrast(color("slate-600"), color("slate-50"))).toBeGreaterThanOrEqual(4.5);
  expect(contrast(color("blue-400"), "#ffffff")).toBeGreaterThanOrEqual(3);
});

it("uses shared primary colors in the console and LiveKit with accessible messenger bubble colors", () => {
  expect(css).toContain("--lk-accent-bg: var(--color-blue-600)");
  expect(css).toMatch(/\.hiresense-console-back \{[^}]*color: var\(--color-blue-600\)/);
  expect(css).toMatch(/\[aria-selected="true"\] \{[^}]*color: var\(--color-blue-700\)/);
  expect(css).toContain(".hiresense-share-control[aria-pressed=\"true\"] { border-color: var(--color-blue-300); background: var(--color-blue-600)");
  expect(css).toMatch(/\.hiresense-end-control \{[^}]*background: #be123c/);
  expect(css).toMatch(/\[data-side="outgoing"\] \.hiresense-transcript-bubble \{[^}]*background: var\(--color-blue-600\); color: white/);
  const incoming = css.match(/\.hiresense-transcript-bubble \{[^}]*background: (#[0-9a-f]{6});[^}]*color: (#[0-9a-f]{6})/)!;
  expect(contrast(incoming[2], incoming[1])).toBeGreaterThanOrEqual(4.5);
  expect(contrast("#ffffff", color("blue-600"))).toBeGreaterThanOrEqual(4.5);
  const thread = css.match(/\.hiresense-transcript-thread \{[^}]*background: (#[0-9a-f]{6})/)![1];
  const timestamp = css.match(/\.hiresense-transcript-time \{[^}]*color: (#[0-9a-f]{6})/)![1];
  expect(contrast(timestamp, thread)).toBeGreaterThanOrEqual(4.5);
});
