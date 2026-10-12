// Current snapshots mark scored outcomes explicitly; historical snapshots
// infer membership from their technical/experience/qualification category.
export function scoredEvidenceRequirements<T extends { category: string | null; score_included?: boolean }>(requirements: T[]): T[] {
  return requirements.filter((item) => item.score_included !== false &&
    ["technical", "experience", "qualification"].includes(item.category ?? ""));
}

export function weightUnits(value: string): bigint | null {
  if (!/^(?:\d+(?:\.\d{0,6})?|\.\d{1,6})$/.test(value) || value.length > 20) return null;
  const [whole = "0", fraction = ""] = value.split(".");
  return BigInt(whole || "0") * 1000000n + BigInt(fraction.padEnd(6, "0"));
}

// ROUND_HALF_UP on precise decimal strings, never binary floating-point scores.
export function displayPercent(value: string | null): string {
  if (value === null) return "N/A";
  const [whole, fraction = ""] = value.split(".");
  let hundredths = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0").slice(0, 2));
  if (Number(fraction[2] ?? "0") >= 5) hundredths += 1n;
  return String(hundredths / 100n) + "." + String(hundredths % 100n).padStart(2, "0") + "%";
}
