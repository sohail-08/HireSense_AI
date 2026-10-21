import { useState } from "react";
import type { FinalRanking } from "./assessmentApi";
import { ReportExports, score } from "./AssessmentView";
import { RankingPagination } from "../candidates/RankingPagination";

function ScoreCell({ value, interview = false }: { value: string | null; interview?: boolean }) {
  const numeric = value === null ? NaN : Number(value);
  return <div className="min-w-20"><span className="font-medium tabular-nums text-slate-700">{score(value)}</span>{Number.isFinite(numeric) ? <div aria-hidden="true" className="mt-1.5 h-1.5 w-20 overflow-hidden rounded-full bg-slate-100"><div className={`h-full rounded-full ${interview ? "bg-violet-400" : "bg-teal-500"}`} style={{ width: `${Math.max(0, Math.min(100, numeric))}%` }} /></div> : null}</div>;
}

export function FinalRankingTable({ ranking, onDetails }: { ranking: FinalRanking; onDetails: (applicationId: number, assessmentId: number) => void }) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const filtered = ranking.candidates.filter(candidate => candidate.candidate_name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  const currentPage = Math.min(page, Math.max(1, Math.ceil(filtered.length / pageSize)));
  const visible = filtered.slice((currentPage - 1) * pageSize, currentPage * pageSize);
  const ranked = ranking.candidates.filter(candidate => candidate.final_rank !== null).length;
  const processing = ranking.status === "processing";
  return <section aria-label="Final candidate ranking" className="min-w-0 rounded-2xl border border-slate-200 bg-white shadow-sm">
    <header className="border-b border-slate-100 px-5 py-4">
      <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-base font-bold text-slate-800">Final ranking</h2><p className="mt-1 text-xs text-slate-500">{ranking.candidates.length} {ranking.candidates.length === 1 ? "candidate" : "candidates"}<span aria-hidden="true"> · </span>{ranked} ranked{ranking.candidates.length > ranked ? ` · ${ranking.candidates.length - ranked} not ranked` : ""}</p></div>
        {ranking.status === "completed" && ranking.id ? <details className="relative"><summary className="inline-flex min-h-10 cursor-pointer list-none items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-50"><svg aria-hidden="true" className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3v12m-4-4 4 4 4-4M4 16v4h16v-4"/></svg>Download ranking</summary><div className="absolute right-0 z-20 mt-2 w-72 max-w-[calc(100vw-3rem)] rounded-2xl border border-slate-200 bg-white px-4 shadow-xl"><ReportExports key={ranking.id} id={ranking.id} comparison /></div></details> : null}
      </div>
      {ranking.candidates.length ? <div className="relative mt-4 max-w-sm"><svg aria-hidden="true" className="pointer-events-none absolute top-3 left-3 h-4 w-4 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/></svg><label className="sr-only" htmlFor="assessment-candidate-search">Search candidates</label><input id="assessment-candidate-search" type="search" value={search} onChange={event => { setSearch(event.target.value); setPage(1); }} placeholder="Search candidates…" className="min-h-10 w-full rounded-xl border border-slate-200 bg-slate-50/60 py-2 pr-3 pl-9 text-sm text-slate-700 placeholder:text-slate-400 focus:border-blue-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-blue-100" /></div> : null}
    </header>
    <div className="px-5">
      {processing ? <p role="status" className="my-4 rounded-xl border border-blue-100 bg-blue-50 px-3 py-2 text-sm text-blue-800">{ranking.stage === "scoring_answers" ? "Scoring interview answers…" : "Calculating final scores…"} You can leave this page and return later.</p> : null}
      {ranking.error ? <p role="alert" className="my-4 rounded-xl bg-rose-50 p-3 text-sm text-rose-800">{ranking.error}</p> : null}
      {ranking.stale ? <p role="status" className="my-4 rounded-xl border border-amber-100 bg-amber-50 p-3 text-sm text-amber-900">Candidates or scores have changed. Calculate the final ranking again to update these saved results.</p> : null}
      {[...new Set(ranking.incompatibilities)].map(message => <p key={message} className="my-3 rounded-xl bg-amber-50 p-3 text-sm text-amber-900">{message}</p>)}
    </div>
    {!ranking.candidates.length ? <div className="px-5 py-12 text-center"><div aria-hidden="true" className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-blue-50 text-blue-500"><svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"><circle cx="9" cy="8" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M16 5a3 3 0 0 1 0 6m3 10v-3a6 6 0 0 0-3-5"/></svg></div><h3 className="text-sm font-semibold text-slate-700">No candidates have applied for this job yet.</h3><p className="mt-1 text-xs leading-6 text-slate-500">Collected applications will appear here.</p></div> : !filtered.length ? <div className="px-5 py-10 text-center"><p className="text-sm font-medium text-slate-600">No matching candidates.</p><button type="button" onClick={() => { setSearch(""); setPage(1); }} className="mt-2 text-sm font-semibold text-blue-700 hover:underline">Clear search</button></div> : <div className="overflow-x-auto"><table className="w-full min-w-[640px] text-left text-sm"><caption className="sr-only">Candidates ordered by their saved final rank. Final scores combine CV and interview scores equally.</caption>
      <thead className="border-y border-slate-100 bg-slate-50/80 text-xs text-slate-500"><tr>{["Rank", "Candidate", "CV score", "Interview score", "Final score", "Actions"].map(heading => <th scope="col" key={heading} className={`px-5 py-3 font-semibold ${heading === "Actions" ? "text-right" : ""}`}>{heading}</th>)}</tr></thead>
      <tbody className="divide-y divide-slate-100">{visible.map(candidate => <tr key={candidate.application_id} className="transition-colors hover:bg-blue-50/30">
        <td className="px-5 py-4"><span className={`inline-flex h-8 min-w-8 items-center justify-center rounded-xl px-1 text-xs font-bold tabular-nums ${candidate.final_rank === 1 ? "bg-blue-600 text-white" : "bg-slate-100 text-slate-600"}`}>{candidate.final_rank ?? "—"}</span></td>
        <td className="min-w-40 px-5 py-4"><p className="font-semibold text-slate-800">{candidate.candidate_name}</p>{candidate.final_rank === null ? <p className="mt-1 max-w-60 text-xs leading-5 text-slate-500">{candidate.reason}</p> : null}</td>
        <td className="px-5 py-4"><ScoreCell value={candidate.cv_score} /></td><td className="px-5 py-4"><ScoreCell value={candidate.interview_score} interview /></td>
        <td className="px-5 py-4"><span className={`inline-flex min-w-20 items-center justify-center rounded-xl border px-2.5 py-2 text-sm font-bold tabular-nums ${candidate.final_score === null ? "border-slate-100 bg-slate-50 text-slate-400" : "border-blue-100 bg-blue-50 text-blue-700"}`}>{score(candidate.final_score)}</span></td>
        <td className="px-5 py-4 text-right"><button type="button" disabled={!candidate.assessment_id || ranking.status !== "completed"} onClick={() => { if (candidate.assessment_id) onDetails(candidate.application_id, candidate.assessment_id); }} className="inline-flex min-h-10 items-center justify-center gap-1 whitespace-nowrap rounded-xl border border-blue-200 bg-white px-3 py-2 text-xs font-semibold text-blue-700 hover:bg-blue-50 focus-visible:outline-2 focus-visible:outline-blue-500 disabled:cursor-not-allowed disabled:border-slate-200 disabled:text-slate-400">View details<span className="sr-only"> for {candidate.candidate_name}</span><svg aria-hidden="true" className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="m9 5 7 7-7 7"/></svg></button></td>
      </tr>)}</tbody>
    </table></div>}
    {ranking.candidates.length ? <div className="px-5 pb-4"><RankingPagination count={filtered.length} page={currentPage} pageSize={pageSize} loading={processing} onPage={setPage} onPageSize={size => { setPageSize(size); setPage(1); }} /></div> : null}
  </section>;
}
