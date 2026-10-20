import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../src/components/candidates/scoringDisplay.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
});
const { displayPercent, scoredEvidenceRequirements, weightUnits } = await import("data:text/javascript;base64," + Buffer.from(outputText).toString("base64"));

test("category totals use decimal units without floating-point drift", () => {
  assert.equal(["33.33", "33.33", "33.34"].reduce((sum, weight) => sum + weightUnits(weight), 0n), 100000000n);
  assert.equal(["50", "30", "20"].reduce((sum, weight) => sum + weightUnits(weight), 0n), 100000000n);
  assert.equal(weightUnits("0.000001"), 1n);
  assert.equal(weightUnits(".5"), 500000n);
  assert.equal(weightUnits("0"), 0n);
});

test("incomplete, negative, nonfinite and overprecise weights cannot be approved", () => {
  for (const value of ["", "-1", "NaN", "Infinity", "1e2", "0.0000001", ".", "10%", "100000000000000000000"]) {
    assert.equal(weightUnits(value), null, value);
  }
  assert.notEqual(["50", "30", "19.99"].reduce((sum, weight) => sum + weightUnits(weight), 0n), 100000000n);
});

test("score display rounds decimal strings half-up to two places", () => {
  assert.equal(displayPercent("82.345"), "82.35%");
  assert.equal(displayPercent("82.34499999999999999999999999"), "82.34%");
  assert.equal(displayPercent("99.999"), "100.00%");
  assert.equal(displayPercent("50"), "50.00%");
  assert.equal(displayPercent("0.00000000000000000000000001"), "0.00%");
});

test("missing category scores remain N/A instead of fabricated coverage", () => {
  assert.equal(displayPercent(null), "N/A");
  assert.equal(displayPercent("0"), "0.00%");
});

test("PostgreSQL scientific-notation decimals retain exact half-up formatting", () => {
  assert.equal(displayPercent("0E-60"), "0.00%");
  assert.equal(displayPercent("1E-60"), "0.00%");
  assert.equal(displayPercent("2.675E+0"), "2.68%");
  assert.equal(displayPercent("8.2345e1"), "82.35%");
  assert.equal(displayPercent("1E+2"), "100.00%");
  assert.equal(displayPercent("-2.675E+0"), "-2.68%");
  assert.equal(displayPercent(".005"), "0.01%");
  assert.equal(displayPercent("-0E-60"), "0.00%");
});

test("invalid score text is unavailable instead of crashing or becoming zero", () => {
  for (const value of ["", "NaN", "Infinity", "bad data", "1e1000000", "1.2.3", "9".repeat(513)]) {
    assert.equal(displayPercent(value), "N/A", value);
  }
});

test("evidence view omits complete evidence-only records without changing saved data", () => {
  const requirements = [
    { name: "React", category: "technical", score_included: true, evidence: ["Scored quote"] },
    { name: "Component design", category: null, score_included: false, evidence: ["Hidden quote"] },
    { name: "Two years", category: "experience", score_included: true },
    { name: "Degree", category: "qualification", score_included: true },
  ];
  const before = structuredClone(requirements);
  assert.deepEqual(scoredEvidenceRequirements(requirements).map((item) => item.name), ["React", "Two years", "Degree"]);
  assert.deepEqual(requirements, before);
});

test("historical evidence-only records without inclusion flags are also omitted", () => {
  const requirements = [{ category: "technical", name: "Scored" }, { category: null, name: "Evidence only" }];
  assert.deepEqual(scoredEvidenceRequirements(requirements).map((item) => item.name), ["Scored"]);
});

test("explicit exclusion cannot be exposed as scored evidence", () => {
  assert.deepEqual(scoredEvidenceRequirements([{ category: "technical", score_included: false }]), []);
});
