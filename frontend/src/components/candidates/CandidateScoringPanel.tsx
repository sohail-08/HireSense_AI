import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { apiRequest } from "../../api/apiClient";
import { ErrorMessage } from "../common/ErrorMessage";
import { RankingPagination } from "./RankingPagination";
import { displayPercent, scoredEvidenceRequirements, weightUnits } from "./scoringDisplay";
import { RequirementEvidence, type EvidenceRequirement } from "./RequirementEvidence";

type Category = "technical" | "experience" | "qualification";
type Weights = Record<Category, string>;
type Requirement = {
  requirement_id: string; name: string; category: Category | null;
  classification: "required" | "preferred"; weight: string;
  evaluation_criterion: string; requirement_version: string;
};
type ConfigurationSnapshot = { requirement_version: string; category_weights: Weights; requirements: Requirement[]; formula_version: string };
type ApprovedConfiguration = { id: number; snapshot: ConfigurationSnapshot; approved_at: string };
type Proposal = ConfigurationSnapshot & { approved_configuration: ApprovedConfiguration | null };
type Summary = { id: number; requirement_version: string; formula_version: string; status: string; created_at: string };
type BreakdownRequirement = Requirement & EvidenceRequirement & {
  status: string; match_value: string; weighted_contribution: string;
  score_included?: boolean;
  evidence: { block_id: string; locator: string; quote: string }[];
};
type Result = {
  id: number; application_id: number; candidate_name: string; rank: number | null;
  review_state: string; final_score: string; display_score: string;
  breakdown: {
    categories: Record<Category, { score: string | null; category_weight: string; total_requirement_weight: string; earned_requirement_weight: string }>;
    requirements: BreakdownRequirement[]; required_gaps: string[];
    counts: Record<string, number>; review_flags: string[];
  };
};
type Run = Summary & { configuration_id: number; configuration: ConfigurationSnapshot; results: Result[] };

const categoryLabels: Record<Category, string> = { technical: "Technical skills", experience: "Experience", qualification: "Qualifications" };
const categories = Object.keys(categoryLabels) as Category[];

function EvidenceModal({ result, onClose, restoreFocus }: { result: Result; onClose: () => void; restoreFocus: HTMLElement | null }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    const overflow = document.body.style.overflow;
    element?.showModal(); document.body.style.overflow = "hidden";
    return () => {
      element?.close(); document.body.style.overflow = overflow;
      if (restoreFocus?.isConnected) restoreFocus.focus();
      else document.getElementById("screening-job")?.focus();
    };
  }, [restoreFocus]);
  const requirements = scoredEvidenceRequirements(result.breakdown.requirements);
  return createPortal(<dialog id="scoring-evidence" ref={dialog} aria-modal="true" aria-labelledby="evidence-title" aria-describedby="evidence-description"
    onCancel={event => { event.preventDefault(); onClose(); }} onClick={event => { if (event.target === event.currentTarget) onClose(); }}
    className="fixed inset-0 m-auto max-h-[90dvh] w-[94vw] max-w-3xl overflow-hidden rounded-2xl border-0 bg-white p-0 text-slate-900 shadow-2xl backdrop:bg-slate-900/45 backdrop:backdrop-blur-sm">
    <div className="flex max-h-[90dvh] flex-col">
    <header className="flex shrink-0 items-start justify-between gap-4 border-b border-slate-100 bg-slate-50/70 px-5 py-4 sm:px-6">
      <div className="min-w-0"><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">CV evidence · {result.display_score}%</p><h2 id="evidence-title" className="mt-1 break-words text-xl font-bold">{result.candidate_name}</h2>
        <p id="evidence-description" className="mt-1 text-sm text-slate-500">How this CV matches the job requirements.</p>
      </div>
      <button type="button" autoFocus aria-label="Close evidence" onClick={onClose} className="shrink-0 rounded-lg px-3 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-200 focus-visible:outline-2 focus-visible:outline-blue-600">Close</button>
    </header>
    <div className="overflow-y-auto px-5 pb-5 sm:px-6">
    {result.breakdown.review_flags.length ? <p className="mt-4 rounded-xl bg-slate-50 p-3 text-sm text-slate-600">
      Some CV details could not be confirmed. Requirements without supporting evidence are marked Unmet; this does not mean the candidate lacks the skill.
    </p> : null}
    <div className="mt-4 grid gap-3 sm:grid-cols-3">{categories.map((category) =>
      <div key={category} className="rounded-xl bg-slate-50 p-3 text-sm"><p>{categoryLabels[category]}</p>
        <strong className="mt-1 block text-lg">{result.breakdown.categories[category].score === null ? "Not scored" : displayPercent(result.breakdown.categories[category].score)}</strong>
      </div>)}</div>
    <div className="mt-4 space-y-3">{requirements.map((item) =>
      <RequirementEvidence key={item.requirement_id} requirement={item} />)}</div>
    {!requirements.length ? <p className="mt-4 text-sm text-slate-500">No requirement details are available for this result.</p> : null}
    </div></div>
  </dialog>, document.body);
}

type Props = {
  jobId: number; refreshToken: string; applicationCount: number; pendingCount: number;
  processing: boolean; ready: boolean; progress?: string; processingError?: string;
  onScreenPending: () => Promise<boolean>;
  jobSelector: ReactNode;
};

export function CandidateScoringPanel({ jobId, refreshToken, applicationCount, pendingCount, processing, ready, progress, processingError, onScreenPending, jobSelector }: Props) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [proposal, setProposal] = useState<Proposal>();
  const [weights, setWeights] = useState<Weights>({ technical: "50", experience: "30", qualification: "20" });
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [run, setRun] = useState<Run>();
  const [evidence, setEvidence] = useState<Result>();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const draftChanged = useRef(false);
  const draftVersion = useRef<string | undefined>(undefined);
  const requestVersion = useRef(0);
  const actionBusy = useRef(false);
  const waitingForConfiguration = useRef<number | undefined>(undefined);
  const evidenceTrigger = useRef<HTMLElement | null>(null);

  useEffect(() => {
    let active = true;
    const request = ++requestVersion.current;
    if (!proposal) setLoading(true);
    void Promise.all([
      apiRequest<Proposal>("/scoring/jobs/" + jobId + "/configuration"),
      apiRequest<Summary[]>("/scoring/jobs/" + jobId + "/runs"),
    ]).then(async ([value, history]) => {
      if (!active || request !== requestVersion.current) return;
      setProposal(value);
      const configuration = value.approved_configuration?.snapshot ?? value;
      if (!draftChanged.current || draftVersion.current !== value.requirement_version) {
        setWeights(configuration.category_weights);
        setRequirements(configuration.requirements);
        draftChanged.current = false;
      }
      draftVersion.current = value.requirement_version;
      if (history[0]) {
        const saved = await apiRequest<Run>("/scoring/runs/" + history[0].id);
        if (active && request === requestVersion.current) {
          setRun(saved); setEvidence(undefined);
          if (!processing && waitingForConfiguration.current !== undefined) {
            setNotice(!processingError && saved.configuration_id === waitingForConfiguration.current ? "Ranking updated." : undefined);
            if (saved.configuration_id !== waitingForConfiguration.current && !processingError) {
              setError("CV processing finished, but the new ranking is not available. Please try again.");
            }
            waitingForConfiguration.current = undefined;
          }
        }
      } else {
        setRun(undefined); setEvidence(undefined);
        if (!processing && waitingForConfiguration.current !== undefined) {
          waitingForConfiguration.current = undefined;
          setNotice(undefined);
          if (!processingError) setError("The ranking could not be prepared. Please try again.");
        }
      }
    }).catch((failure: unknown) => {
      if (active && request === requestVersion.current) setError(failure instanceof Error ? failure.message : "Could not load the ranking.");
    }).finally(() => { if (active && request === requestVersion.current) setLoading(false); });
    return () => { active = false; };
  }, [jobId, refreshToken, processing, processingError]);

  const totalUnits = categories.reduce((sum, category) => sum + (weightUnits(weights[category]) ?? 0n), 0n);
  const total = Number(totalUnits) / 1000000;
  const missingCategories = categories.filter((category) => Number(weights[category]) > 0 &&
    !requirements.some((item) => item.category === category && Number(item.weight) > 0));
  const valid = totalUnits === 100000000n && categories.every((category) => weightUnits(weights[category]) !== null) &&
    requirements.every((item) => weightUnits(item.weight) !== null && Number(item.weight) <= 10000) && !missingCategories.length;

  async function saveAndRank() {
    if (!proposal || !valid || !ready || !applicationCount || actionBusy.current || processing) return;
    actionBusy.current = true;
    ++requestVersion.current; // Older refresh responses must not replace this action.
    setBusy(true); setError(undefined); setNotice(undefined); setEvidence(undefined);
    try {
      const approved = await apiRequest<ApprovedConfiguration>("/scoring/jobs/" + jobId + "/configuration", {
        method: "POST", body: JSON.stringify({
          confirmed: true, requirement_version: proposal.requirement_version, category_weights: weights,
          requirements: requirements.map(({ requirement_id, category, classification, weight }) => ({ requirement_id, category, classification, weight })),
        }),
      });
      setProposal({ ...proposal, approved_configuration: approved });
      draftChanged.current = false;
      let queued = false;
      if (pendingCount > 0) {
        waitingForConfiguration.current = approved.id;
        setNotice("Preparing candidate CVs. Your ranking will appear when processing finishes.");
        queued = await onScreenPending();
      }
      if (!queued) {
        waitingForConfiguration.current = undefined;
        const saved = await apiRequest<Run>("/scoring/jobs/" + jobId + "/runs", {
          method: "POST", body: JSON.stringify({ configuration_id: approved.id }),
        });
        setRun(saved);
        setNotice("Ranking updated.");
      }
    } catch (failure) {
      waitingForConfiguration.current = undefined;
      setNotice(undefined);
      setError(failure instanceof Error ? failure.message : "Could not update the ranking. Please try again.");
    }
    finally { actionBusy.current = false; setBusy(false); }
  }

  const closeEvidence = useCallback(() => setEvidence(undefined), []);

  const ranked = run?.results.slice()
    .sort((left, right) => (left.rank ?? Infinity) - (right.rank ?? Infinity) || left.application_id - right.application_id) ?? [];
  const pages = Math.max(1, Math.ceil(ranked.length / pageSize));
  const currentPage = Math.min(page, pages);
  const start = (currentPage - 1) * pageSize;
  const visibleResults = ranked.slice(start, start + pageSize);
  useEffect(() => { setPage(1); }, [run?.id, jobId]);
  useEffect(() => { setPage(value => Math.min(value, pages)); }, [pages]);

  return <>
    <section aria-labelledby="ranking-title" className="mt-5 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-100 px-4 py-4 sm:px-5">
        <div><h2 id="ranking-title" className="text-lg font-semibold text-slate-900">Candidate ranking</h2>
          <p className="mt-1 text-sm text-slate-500">See how closely each CV matches the job.</p></div>
        <div className="w-full sm:w-80">{jobSelector}</div>
      </div>
      <div className="px-4 pb-4 sm:px-5">
      <ErrorMessage message={error ?? processingError} />
      {loading ? <p className="mt-4 text-sm text-slate-500">Loading scoring weights…</p> : proposal ? <>
        <div className="mt-4 flex flex-wrap items-end gap-3 rounded-xl bg-slate-50 p-3">
          <div className="self-center"><h3 className="text-sm font-semibold text-slate-800">Scoring weights</h3>
            <p aria-live="polite" className={"mt-1 text-xs " + (valid ? "text-emerald-700" : "text-red-700")}>{"Total: " + total + "%"}</p></div>
          <div className="grid min-w-0 flex-1 basis-64 grid-cols-3 gap-2">{categories.map((category) =>
          <label key={category} className="flex flex-col justify-end text-xs font-medium text-slate-600">{categoryLabels[category]} (%)
            <input type="number" min="0" max="100" step="0.01" value={weights[category]} disabled={busy || processing}
              onChange={(event) => { draftChanged.current = true; setNotice(undefined); setWeights({ ...weights, [category]: event.target.value }); }}
              className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm text-slate-900 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100" />
          </label>)}</div>
          <button type="button" onClick={() => void saveAndRank()} disabled={!valid || !ready || !applicationCount || busy || processing}
            className="shrink-0 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300">
            {busy || processing ? "Ranking…" : "Rank candidates"}
          </button>
        </div>
        {!valid && !missingCategories.length ? <p className="mt-2 text-sm text-red-700">Enter percentages from 0 to 100 that add up to 100%.</p> : null}
        {missingCategories.length ? <p className="mt-2 text-sm text-amber-800">{missingCategories.map((category) => categoryLabels[category]).join(", ") + ": no matching job requirements. Set this weight to 0% and add the difference to the other categories."}</p> : null}
        {!applicationCount ? <p className="mt-3 text-sm text-slate-500">No candidates have applied for this job yet.</p> : null}
      </> : null}
      {processing ? <p role="status" className="mt-4 rounded-xl bg-blue-50 p-3 text-sm text-blue-800">{progress ?? "Preparing candidate CVs and ranking…"}</p>
        : notice ? <p role="status" className="mt-4 rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p> : null}
      {run && pendingCount > 0 && !processing ? <p className="mt-3 text-sm text-amber-800">New or updated CVs are waiting. Select “Rank candidates” to include them.</p> : null}
      {run && categories.some(category => weightUnits(weights[category]) !== weightUnits(run.configuration.category_weights[category])) ? <p className="mt-3 text-sm text-amber-800">Select “Rank candidates” to apply your changes. Current results use {categories.map(category => categoryLabels[category].toLowerCase() + " " + run.configuration.category_weights[category] + "%").join(", ")}.</p> : null}
      {run && proposal && (run.requirement_version !== proposal.requirement_version || run.formula_version !== proposal.formula_version) ? <p className="mt-3 text-sm text-amber-800">The job requirements or scoring rules have changed. Rank candidates again to update these results.</p> : null}
      {ranked.length ? <div className="mt-4 overflow-x-auto"><table className="w-full text-left text-sm">
        <thead className="border-b border-slate-200 text-slate-500"><tr><th className="px-2 py-3">Rank</th><th className="px-2 py-3">Candidate</th><th className="px-2 py-3">Score</th><th className="px-2 py-3"><span className="sr-only">Evidence</span></th></tr></thead>
        <tbody>{visibleResults.map((result) => <tr key={result.id} className="border-b border-slate-100 last:border-0">
          <td className="px-2 py-4 font-semibold">{result.rank ?? "—"}</td><td className="px-2 py-4 font-medium">{result.candidate_name}</td>
          <td className="whitespace-nowrap px-2 py-4 font-semibold text-blue-700">{result.display_score + "%"}</td>
          <td className="px-2 py-4 text-right"><button type="button" id={"inspect-score-" + result.id} onClick={event => { evidenceTrigger.current = event.currentTarget; setEvidence(result); }}
            aria-label={`Inspect evidence for ${result.candidate_name}`} aria-haspopup="dialog" className="rounded-lg border border-blue-100 bg-blue-50/50 px-3 py-2 text-xs font-semibold text-blue-700 hover:bg-blue-100">Inspect evidence</button></td>
        </tr>)}</tbody>
      </table></div> : <p className="mt-4 rounded-xl bg-slate-50 p-4 text-sm text-slate-500">
        {loading ? "Loading candidate ranking…" : processing ? "Your ranking is being prepared." : !applicationCount ? "Candidates will appear here after their applications are collected." : "Choose your weights, then select “Rank candidates” to see the results."}
      </p>}
      <RankingPagination count={ranked.length} page={currentPage} pageSize={pageSize} loading={loading} onPage={setPage} onPageSize={size => { setPageSize(size); setPage(1); }} />
      {run ? <p className="mt-3 text-xs text-slate-400">Last updated {new Date(run.created_at).toLocaleString()} · Scores reflect the CV, not a final hiring decision.</p> : null}
      </div>
    </section>
    {evidence ? <EvidenceModal key={evidence.id} result={evidence} restoreFocus={evidenceTrigger.current} onClose={closeEvidence} /> : null}
  </>;
}
