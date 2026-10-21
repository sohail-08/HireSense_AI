type Citation = { block_id: string; locator: string; quote: string };
type Excerpt = Citation & { omitted_before?: boolean; omitted_after?: boolean };

export type EvidenceRequirement = {
  name: string; status: string; reason?: string;
  evidence: Citation[]; evidence_preview?: Excerpt[];
};

const labels: Record<string, string> = {
  met: "Met", partially_met: "Partially met", unmet: "Unmet", unable_to_determine: "Unmet",
};

export function RequirementEvidence({ requirement: item }: { requirement: EvidenceRequirement }) {
  const excerpts = item.evidence_preview ?? [];
  const fallback = item.status === "met" ? "The CV examples support this requirement."
    : item.status === "partially_met" ? "The CV supports part of this requirement, but does not demonstrate it fully."
    : "The CV does not provide enough evidence for this requirement.";

  return <article className="rounded-xl border border-slate-200 p-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h4 className="font-semibold text-slate-900">{item.name}</h4>
      <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">{labels[item.status] ?? item.status}</span>
    </div>
    <p className="mt-2 text-sm leading-6 text-slate-700">{item.reason || fallback}</p>
    {excerpts.map((citation, index) => <blockquote key={index}
      className="mt-3 whitespace-pre-line break-words border-l-4 border-blue-200 bg-blue-50/50 px-3 py-2 text-sm leading-6 text-slate-700">
      {citation.omitted_before ? "… " : ""}{"“" + citation.quote + "”"}{citation.omitted_after ? " …" : ""}
      <footer className="mt-1 text-xs font-medium text-blue-700">{citation.locator}</footer>
    </blockquote>)}
    {item.evidence.length ? <details className="mt-3 text-sm">
      <summary className="cursor-pointer font-medium text-blue-700">View full source passages ({item.evidence.length})</summary>
      <div className="mt-2 max-h-80 space-y-3 overflow-y-auto">{item.evidence.map((citation, index) =>
        <blockquote key={index} className="whitespace-pre-line break-words border-l-4 border-slate-200 bg-slate-50 px-3 py-2 text-sm leading-6 text-slate-600">
          {"“" + citation.quote + "”"}<footer className="mt-1 text-xs font-medium text-slate-500">{citation.locator}</footer>
        </blockquote>)}</div>
    </details> : <p className="mt-2 text-sm text-slate-500">No verified supporting evidence was found in this CV.</p>}
  </article>;
}
