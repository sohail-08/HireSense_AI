type Citation = { block_id: string; locator: string; quote: string };
type Excerpt = Citation & { omitted_before?: boolean; omitted_after?: boolean };

export type EvidenceRequirement = {
  name: string; status: string; reason?: string;
  evidence: Citation[]; evidence_preview?: Excerpt[];
};

const labels: Record<string, string> = {
  met: "Met", partially_met: "Partially met", unmet: "Unmet", unable_to_determine: "Unmet",
};
const statusColors: Record<string, string> = {
  met: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  partially_met: "bg-amber-50 text-amber-900 ring-amber-200",
  unmet: "bg-rose-50 text-rose-800 ring-rose-200",
};

export function RequirementEvidence({ requirement: item }: { requirement: EvidenceRequirement }) {
  // Older saved results may not have prepared excerpts. Keep their citations
  // useful without reintroducing entire CV pages in the modal.
  const excerpts: Excerpt[] = item.evidence_preview?.length ? item.evidence_preview : item.evidence.slice(0, 2).map(citation => ({
    ...citation, quote: citation.quote.length > 240 ? citation.quote.slice(0, 240).trimEnd() : citation.quote,
    omitted_after: citation.quote.length > 240,
  }));
  const fallback = item.status === "met" ? "The CV examples support this requirement."
    : item.status === "partially_met" ? "The CV supports part of this requirement, but does not demonstrate it fully."
    : "The CV does not provide enough evidence for this requirement.";

  return <article className="rounded-xl border border-slate-200 p-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h4 className="font-semibold text-slate-900">{item.name}</h4>
      <span className={`rounded-full px-3 py-1 text-xs font-semibold ring-1 ring-inset ${statusColors[item.status] ?? statusColors.unmet}`}>{labels[item.status] ?? "Unmet"}</span>
    </div>
    <p className="mt-2 text-sm leading-6 text-slate-700">{item.reason || fallback}</p>
    {excerpts.map((citation, index) => <blockquote key={index}
      className="mt-3 whitespace-pre-line break-words border-l-4 border-blue-200 bg-blue-50/50 px-3 py-2 text-sm leading-6 text-slate-700">
      {citation.omitted_before ? "… " : ""}{"“" + citation.quote + "”"}{citation.omitted_after ? " …" : ""}
      <footer className="mt-1 text-xs font-medium text-blue-700">{citation.locator}</footer>
    </blockquote>)}
    {!excerpts.length ? <p className="mt-2 text-sm text-slate-500">No supporting CV example found.</p> : null}
  </article>;
}
