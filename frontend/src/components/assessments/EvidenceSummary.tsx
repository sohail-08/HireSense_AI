import { useState, type ReactNode } from "react";

export const summaryCategories = ["strengths", "weaknesses", "evidence_gaps", "verification"] as const;
export type SummaryCategory = typeof summaryCategories[number];
type Finding = { text: string; summary_text?: string };
const titles: Record<SummaryCategory, string> = {
  strengths: "Strengths", weaknesses: "Areas to improve", evidence_gaps: "Not yet assessed", verification: "Needs checking",
};
const tones: Record<SummaryCategory, string> = {
  strengths: "bg-emerald-50 text-emerald-700", weaknesses: "bg-amber-50 text-amber-700",
  evidence_gaps: "bg-slate-100 text-slate-500", verification: "bg-blue-50 text-blue-700",
};
const empty: Record<SummaryCategory, string> = {
  strengths: "No strengths recorded yet.", weaknesses: "No confirmed areas to improve.",
  evidence_gaps: "No additional gaps recorded.", verification: "Nothing else flagged.",
};

function shortText(finding: Finding) {
  const text = (finding.summary_text || finding.text).replace(/^Q\d+\s*[·:]\s*/, "")
    .replace(/^(?:(?:relevance|accuracy|completeness|quality)(?:,\s*|:\s*))+/i, "").replace(/\s+/g, " ").trim();
  return text.length <= 150 ? text : text.slice(0, 149).replace(/\s+\S*$/, "").replace(/[,;:]$/, "") + "…";
}

/** Group repeated highlights, retaining every original explanation and source. */
export function performanceHighlights<T extends Finding>(findings: T[]) {
  const grouped = new Map<string, { text: string; findings: T[] }>();
  for (const finding of findings) {
    const text = shortText(finding);
    if (!text) continue;
    // Do not merge unrelated long excerpts just because their visible prefix matches.
    const key = (finding.summary_text || finding.text).trim().toLowerCase().replace(/\s+/g, " ").replace(/[.!]+$/, "");
    const existing = grouped.get(key);
    if (existing) existing.findings.push(finding);
    else grouped.set(key, { text, findings: [finding] });
  }
  return [...grouped.values()].sort((a, b) => b.findings.length - a.findings.length);
}

function Icon({ category }: { category: SummaryCategory }) {
  return <svg aria-hidden="true" className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    {category === "strengths" ? <path d="m5 12 4 4L19 6" /> : category === "weaknesses" ? <path d="M6 17 17 6M7 6h10v10" /> : category === "evidence_gaps" ? <><circle cx="12" cy="12" r="8" /><path d="M12 8v4l3 2" /></> : <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 4 4" /></>}
  </svg>;
}

function Sources<T extends Finding>({ findings, evidence }: { findings: T[]; evidence: (finding: T) => ReactNode }) {
  const [open, setOpen] = useState(false);
  return <details className="group/sources mt-1" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary className="flex min-h-6 w-fit cursor-pointer list-none items-center gap-1 text-xs text-slate-500 hover:text-blue-700 focus-visible:outline-2 focus-visible:outline-blue-500 [&::-webkit-details-marker]:hidden">Sources{findings.length > 1 ? ` (${findings.length})` : ""}<svg aria-hidden="true" className="h-3 w-3 transition-transform group-open/sources:rotate-180" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m6 9 6 6 6-6" /></svg></summary>
    {open ? <div className="mt-2 space-y-3 rounded-xl border border-slate-100 bg-slate-50/70 p-3 text-xs">{findings.map((finding, index) => <div key={index} className="min-w-0 break-words">
      {finding.text !== shortText(finding) ? <p className="mb-2 whitespace-pre-wrap text-xs leading-5 text-slate-600">{finding.text}</p> : null}{evidence(finding)}
    </div>)}</div> : null}
  </details>;
}

export function EvidenceSummary<T extends Finding>({ value, evidence }: {
  value: Partial<Record<SummaryCategory, T[]>>; evidence: (finding: T) => ReactNode;
}) {
  const [expanded, setExpanded] = useState<Partial<Record<SummaryCategory, boolean>>>({});
  function contents(category: SummaryCategory) {
    const highlights = performanceHighlights(value[category] || []);
    const visible = expanded[category] ? highlights : highlights.slice(0, 3);
    return <>
      {visible.length ? <ul className="space-y-3">{visible.map(highlight => <li key={highlight.text + highlight.findings[0].text} className="min-w-0 border-b border-slate-100 pb-3 last:border-0 last:pb-0">
        <p className="break-words text-sm font-medium leading-6 text-slate-700">{highlight.text}</p>
        <Sources findings={highlight.findings} evidence={evidence} />
      </li>)}</ul> : <p className="text-xs leading-6 text-slate-500">{empty[category]}</p>}
      {highlights.length > 3 ? <button type="button" aria-expanded={!!expanded[category]} aria-label={`${expanded[category] ? "Show fewer" : "Show all"} ${titles[category].toLowerCase()}`} onClick={() => setExpanded(previous => ({ ...previous, [category]: !previous[category] }))} className="mt-3 min-h-9 text-xs font-semibold text-blue-700 hover:text-blue-800">{expanded[category] ? "Show less" : `Show all ${highlights.length}`}</button> : null}
    </>;
  }
  return <section aria-label="Candidate performance" className="mt-6 overflow-hidden rounded-2xl border border-slate-200 bg-white">
    <header className="border-b border-slate-100 px-4 py-4 sm:px-5"><h3 className="text-base font-bold tracking-tight text-slate-800">Candidate performance</h3><p className="mt-1 text-xs text-slate-500">Key strengths and next steps, at a glance.</p></header>
    <div className="grid gap-4 p-4 sm:grid-cols-2 sm:p-5">{(["strengths", "weaknesses"] as const).map(category => <section key={category} aria-label={titles[category]} className="min-w-0 rounded-xl border border-slate-100 p-4">
      <div className="mb-4 flex items-center gap-2.5"><span className={`inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${tones[category]}`}><Icon category={category} /></span><h4 className="text-sm font-semibold text-slate-800">{titles[category]}</h4></div>
      {contents(category)}
    </section>)}</div>
    <div className="grid border-t border-slate-100 bg-slate-50/40 sm:grid-cols-2">{(["evidence_gaps", "verification"] as const).map(category => {
      const count = performanceHighlights(value[category] || []).length;
      return <section key={category} aria-label={titles[category]} className="min-w-0 border-b border-slate-100 last:border-0 sm:border-b-0 sm:first:border-r"><details className="group">
        <summary className="flex min-h-14 cursor-pointer list-none items-center gap-2.5 px-4 py-3 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-blue-500 sm:px-5 [&::-webkit-details-marker]:hidden"><span className={`inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${tones[category]}`}><Icon category={category} /></span><h4 className="flex-1 text-xs font-semibold text-slate-600">{titles[category]}</h4><span className="rounded-full bg-white px-2 py-0.5 text-xs tabular-nums text-slate-500">{count}</span><svg aria-hidden="true" className="h-3.5 w-3.5 text-slate-400 transition-transform group-open:rotate-180" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m6 9 6 6 6-6" /></svg></summary>
        <div className="border-t border-slate-100 px-4 py-4 sm:px-5">{contents(category)}</div>
      </details></section>;
    })}</div>
    <p className="border-t border-slate-100 px-4 py-2.5 text-[11px] text-slate-500 sm:px-5">Unassessed topics are not treated as weaknesses.</p>
  </section>;
}
