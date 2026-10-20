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
  // Numeric(80, 60) zero values arrive from PostgreSQL/Decimal as "0E-60".
  // Parse the coefficient and exponent exactly instead of converting to Number.
  const parsed = /^([+-]?)(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$/.exec(value.trim());
  if (!parsed || value.length > 512) return "N/A";
  const fraction = parsed[3] ?? parsed[4] ?? "";
  const exponent = Number(parsed[5] ?? "0");
  if (!Number.isInteger(exponent) || Math.abs(exponent) > 1000) return "N/A";
  const coefficient = BigInt((parsed[2] ?? "0") + fraction);
  const shift = exponent - fraction.length + 2;
  let hundredths: bigint;
  if (shift >= 0) hundredths = coefficient * 10n ** BigInt(shift);
  else {
    const divisor = 10n ** BigInt(-shift);
    hundredths = coefficient / divisor;
    if ((coefficient % divisor) * 2n >= divisor) hundredths += 1n;
  }
  const sign = parsed[1] === "-" && hundredths !== 0n ? "-" : "";
  return sign + String(hundredths / 100n) + "." + String(hundredths % 100n).padStart(2, "0") + "%";
}
