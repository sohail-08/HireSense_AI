import type { ReactNode } from "react";

export const summaryCategories = ["strengths", "weaknesses", "evidence_gaps", "verification"] as const;
export type SummaryCategory = typeof summaryCategories[number];
const titles: Record<SummaryCategory, string> = {
  strengths: "Strengths", weaknesses: "Weaknesses", evidence_gaps: "Evidence gaps", verification: "Further verification",
};
const colors: Record<SummaryCategory, string> = {
  strengths: "border-emerald-100 bg-emerald-50/40", weaknesses: "border-rose-100 bg-rose-50/30",
  evidence_gaps: "border-amber-100 bg-amber-50/40", verification: "border-blue-100 bg-blue-50/40",
};
const empty: Record<SummaryCategory, string> = {
  strengths: "No supported strengths recorded yet.", weaknesses: "No demonstrated weaknesses recorded. Missing evidence is not a weakness.",
  evidence_gaps: "No additional evidence gaps recorded.", verification: "No additional verification points recorded.",
};

export function EvidenceSummary<T extends { text: string }>({ value, evidence }: {
  value: Partial<Record<SummaryCategory, T[]>>; evidence: (finding: T) => ReactNode;
}) {
  return <section aria-label="Evidence-based summary" className="mt-6">
    <h3 className="text-base font-bold text-slate-800">Evidence summary</h3>
    <p className="mt-1 text-xs leading-5 text-slate-500">Based on recorded evidence, not assumptions about ability. Open a finding to check its sources.</p>
    <div className="mt-3 grid gap-3 lg:grid-cols-2">{summaryCategories.map(category => <section key={category} aria-label={titles[category]} className={`min-w-0 rounded-2xl border p-4 ${colors[category]}`}>
      <h4 className="text-sm font-semibold text-slate-800">{titles[category]}</h4>
      {value[category]?.length ? <ul className="mt-3 space-y-3">{value[category]!.map((finding, index) => <li key={index} className="min-w-0 text-sm leading-6 text-slate-700">
        <p className="whitespace-pre-wrap break-words">{finding.text}</p>
        <details className="mt-1"><summary className="w-fit cursor-pointer text-xs font-semibold text-blue-700">View supporting evidence</summary><div className="mt-2 break-words rounded-xl border border-white bg-white/80 p-3 text-xs">{evidence(finding)}</div></details>
      </li>)}</ul> : <p className="mt-3 text-xs leading-6 text-slate-500">{empty[category]}</p>}
    </section>)}</div>
  </section>;
}
