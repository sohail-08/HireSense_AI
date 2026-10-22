import { formatDate } from "../../utils/dateTime";
import { JobDescriptionContent } from "./JobDescriptionPreview";

function applicationLink(value: string) {
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) ? url.href : undefined;
  } catch { return undefined; }
}

export function DiscordPostPreview({ heading, title, content, fields }: {
  heading: string; title: string; content: string; fields: string[][];
}) {
  return <article aria-label="Discord post preview" className="mt-2 min-w-0 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
    <header className="border-t-4 border-indigo-500 bg-slate-900 px-5 py-6 sm:px-6">
      <div className="mb-4 flex items-center gap-3">
        <span aria-hidden="true" className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-indigo-500/20 text-indigo-200">
          <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="3" y="7" width="18" height="14" rx="3" /><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12a24 24 0 0 0 18 0M10 13h4" /></svg>
        </span>
        <p className="min-w-0 whitespace-pre-wrap text-sm font-medium leading-6 text-indigo-200 [overflow-wrap:anywhere]">{heading || "Heading required"}</p>
      </div>
      <h4 className="break-words text-2xl font-bold leading-tight tracking-tight text-white">{title}</h4>
    </header>
    <div className="px-5 py-6 sm:px-6"><JobDescriptionContent title={title} content={content} /></div>
    {fields.length ? <section aria-label="Application details" className="border-t border-slate-100 bg-slate-50/80 px-5 py-5 sm:px-6">
      <h5 className="mb-4 text-xs font-bold uppercase tracking-wider text-indigo-700">How to apply</h5>
      <dl className="grid min-w-0 gap-3 sm:grid-cols-2">
        {fields.map(([label, value]) => {
          const href = label === "Application link" ? applicationLink(value) : undefined;
          const date = label === "Application deadline" ? formatDate(value) : undefined;
          return <div key={label} className={`min-w-0 rounded-xl border border-slate-200/80 bg-white px-3.5 py-3 ${label === "Application link" || label === "Additional application instructions" ? "sm:col-span-2" : ""}`}>
            <dt className="mb-1 text-xs font-medium text-slate-500">{label}</dt>
            <dd className="whitespace-pre-wrap text-sm font-medium leading-6 text-slate-800 [overflow-wrap:anywhere]">
              {href ? <a href={href} target="_blank" rel="noopener noreferrer" className="rounded text-indigo-700 underline decoration-indigo-200 underline-offset-4 hover:text-indigo-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600">{value}</a>
                : date && date !== "Not provided" ? date : value}
            </dd>
          </div>;
        })}
      </dl>
    </section> : null}
  </article>;
}
