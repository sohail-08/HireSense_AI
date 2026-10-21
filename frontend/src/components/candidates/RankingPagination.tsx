type Props = { count: number; page: number; pageSize: number; loading?: boolean; selectedCount?: number;
  onPage: (page: number) => void; onPageSize: (size: number) => void };

export function RankingPagination({ count, page, pageSize, loading = false, selectedCount = 0, onPage, onPageSize }: Props) {
  const pages = Math.max(1, Math.ceil(count / pageSize));
  const current = Math.min(page, pages);
  const start = (current - 1) * pageSize;
  const numbers = pages <= 7 ? Array.from({ length: pages }, (_, index) => index + 1)
    : [1, ...Array.from({ length: 3 }, (_, index) => Math.max(2, Math.min(current - 1, pages - 3)) + index), pages];
  return <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-3 text-xs text-slate-500">
    <p aria-live="polite">{count ? `${start + 1}–${Math.min(start + pageSize, count)} of ${count} candidates` : "0 candidates"}{selectedCount ? ` · ${selectedCount} selected` : ""}</p>
    <label htmlFor="ranking-page-size" className="flex items-center gap-2 text-slate-600">Candidates per page
      <select id="ranking-page-size" value={pageSize} disabled={loading} onChange={event => onPageSize(Number(event.target.value))} className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 font-medium outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100">
        {[5, 10, 20, 50].map(size => <option key={size} value={size}>{size}</option>)}
      </select>
    </label>
    <nav aria-label="Ranking pages" className="flex flex-wrap items-center gap-2">
      <span className="mr-1">Page {current} of {pages}</span>
      <button type="button" disabled={loading || current === 1} onClick={() => onPage(current - 1)} className="rounded-lg border border-slate-200 bg-white px-3 py-2 font-medium text-slate-600 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40">Previous</button>
      {numbers.map((number, index) => <span key={number} className="hidden items-center gap-2 sm:inline-flex">
        {index > 0 && number - numbers[index - 1] > 1 ? <span aria-hidden="true" className="px-1">…</span> : null}
        <button type="button" aria-label={`Go to ranking page ${number}`} aria-current={number === current ? "page" : undefined} disabled={loading} onClick={() => onPage(number)}
          className={`min-w-8 rounded-lg border px-2 py-2 font-semibold ${number === current ? "border-blue-600 bg-blue-600 text-white" : "border-slate-200 bg-white text-slate-600 hover:bg-slate-100"}`}>{number}</button>
      </span>)}
      <button type="button" disabled={loading || current === pages} onClick={() => onPage(current + 1)} className="rounded-lg border border-slate-200 bg-white px-3 py-2 font-medium text-slate-600 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40">Next</button>
    </nav>
  </div>;
}
