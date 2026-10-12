import { useEffect, useRef, useState } from "react";

import { apiRequest } from "../../api/apiClient";
import { ErrorMessage } from "../common/ErrorMessage";
import { displayPercent, scoredEvidenceRequirements, weightUnits } from "./scoringDisplay";

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
type BreakdownRequirement = Requirement & {
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
const outcomeLabels: Record<string, string> = {
  met: "Met", partially_met: "Partially met", unmet: "Unmet", unable_to_determine: "Unmet",
};

function EvidencePanel({ result, onClose }: { result: Result; onClose: () => void }) {
  const panelRef = useRef<HTMLElement>(null);
  useEffect(() => {
    panelRef.current?.focus({ preventScroll: true });
    panelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [result.id]);
  const requirements = scoredEvidenceRequirements(result.breakdown.requirements);
  const unmetRequirements = requirements.filter((item) =>
    item.classification === "required" && ["unmet", "unable_to_determine"].includes(item.status));
  return <section id="scoring-evidence" ref={panelRef} tabIndex={-1} aria-labelledby="evidence-title"
    className="mt-5 scroll-mt-5 rounded-2xl border border-blue-200 bg-white p-5 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500">
    <div className="flex items-start justify-between gap-3">
      <div><h3 id="evidence-title" className="text-lg font-semibold">{result.candidate_name + " — evidence"}</h3>
        <p className="mt-1 text-sm text-slate-500">See which job requirements are supported by this CV. Missing or rejected evidence receives zero credit.</p>
      </div>
      <button type="button" onClick={onClose} className="rounded-lg px-3 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-100">Close</button>
    </div>
    {result.breakdown.review_flags.length ? <p className="mt-4 rounded-xl bg-slate-50 p-3 text-sm text-slate-600">
      Some CV content or evidence could not be used. Unsupported requirements are scored as Unmet (0); this is not proof the candidate lacks those capabilities.
    </p> : null}
    <div className="mt-4 grid gap-3 sm:grid-cols-3">{categories.map((category) =>
      <div key={category} className="rounded-xl bg-slate-50 p-3 text-sm"><p>{categoryLabels[category]}</p>
        <strong className="mt-1 block text-lg">{displayPercent(result.breakdown.categories[category].score)}</strong>
      </div>)}</div>
    {unmetRequirements.length ? <p className="mt-4 rounded-xl bg-red-50 p-3 text-sm text-red-800">
      Unmet requirements: {unmetRequirements.map((item) => item.name).join(", ")}.
    </p> : null}
    <div className="mt-4 space-y-3">{requirements.map((item) =>
      <article key={item.requirement_id} className="rounded-xl border border-slate-200 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h4 className="font-semibold text-slate-900">{item.name}</h4>
          <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">{outcomeLabels[item.status] ?? item.status}</span>
        </div>
        {item.evidence.length ? item.evidence.map((citation, index) =>
          <blockquote key={index} className="mt-3 border-l-4 border-blue-200 bg-blue-50/50 px-3 py-2 text-sm leading-6 text-slate-700">
            {"“" + citation.quote + "”"}<footer className="mt-1 text-xs font-medium text-blue-700">{citation.locator}</footer>
          </blockquote>) : <p className="mt-2 text-sm text-slate-500">No verified supporting evidence was found in this CV.</p>}
      </article>)}</div>
    {!requirements.length ? <p className="mt-4 text-sm text-slate-500">No scored requirements to display.</p> : null}
  </section>;
}

type Props = {
  jobId: number; refreshToken: string; applicationCount: number; pendingCount: number;
  processing: boolean; ready: boolean; progress?: string; processingError?: string;
  onScreenPending: () => Promise<boolean>;
};

export function CandidateScoringPanel({ jobId, refreshToken, applicationCount, pendingCount, processing, ready, progress, processingError, onScreenPending }: Props) {
  const [proposal, setProposal] = useState<Proposal>();
  const [weights, setWeights] = useState<Weights>({ technical: "50", experience: "30", qualification: "20" });
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [runs, setRuns] = useState<Summary[]>([]);
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
      setRuns(history);
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
        setRuns(await apiRequest<Summary[]>("/scoring/jobs/" + jobId + "/runs"));
        setNotice("Ranking updated.");
      }
    } catch (failure) {
      waitingForConfiguration.current = undefined;
      setNotice(undefined);
      setError(failure instanceof Error ? failure.message : "Could not update the ranking. Please try again.");
    }
    finally { actionBusy.current = false; setBusy(false); }
  }

  async function selectRun(id: number) {
    if (actionBusy.current) return;
    actionBusy.current = true;
    ++requestVersion.current;
    setBusy(true); setError(undefined); setEvidence(undefined); setNotice(undefined);
    try { setRun(await apiRequest<Run>("/scoring/runs/" + id)); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "Could not load the previous ranking."); }
    finally { actionBusy.current = false; setBusy(false); }
  }

  function closeEvidence() {
    const id = evidence?.id;
    setEvidence(undefined);
    if (id) document.getElementById("inspect-score-" + id)?.focus();
  }

  const ranked = run?.results.slice()
    .sort((left, right) => (left.rank ?? Infinity) - (right.rank ?? Infinity) || left.application_id - right.application_id) ?? [];

  return <>
    <section className="mt-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="font-semibold text-slate-900">Scoring weights</h2>
      <p className="mt-1 text-sm text-slate-500">Choose how much each category matters. The total must be 100%.</p>
      <ErrorMessage message={error ?? processingError} />
      {loading ? <p className="mt-4 text-sm text-slate-500">Loading scoring weights…</p> : proposal ? <>
        <div className="mt-4 grid gap-4 sm:grid-cols-3">{categories.map((category) =>
          <label key={category} className="text-sm font-medium text-slate-800">{categoryLabels[category]} (%)
            <input type="number" min="0" max="100" step="0.01" value={weights[category]} disabled={busy || processing}
              onChange={(event) => { draftChanged.current = true; setNotice(undefined); setWeights({ ...weights, [category]: event.target.value }); }}
              className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-2.5 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100" />
          </label>)}</div>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <p className={"text-sm " + (valid ? "text-emerald-700" : "text-red-700")}>{"Total: " + total + "%"}</p>
          <button type="button" onClick={() => void saveAndRank()} disabled={!valid || !ready || !applicationCount || busy || processing}
            className="rounded-xl bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300">
            {busy || processing ? "Preparing ranking…" : "Save weights & rank candidates"}
          </button>
        </div>
        {missingCategories.length ? <p className="mt-2 text-sm text-amber-800">{missingCategories.map((category) => categoryLabels[category]).join(", ") + ": this job has no scored requirements in this category. Set its weight to 0% and redistribute the percentage."}</p> : null}
        {!applicationCount ? <p className="mt-3 text-sm text-slate-500">No applications have been collected for this job yet.</p> : null}
      </> : null}
      {processing ? <p role="status" className="mt-4 rounded-xl bg-blue-50 p-3 text-sm text-blue-800">{progress ?? "Preparing candidate CVs and ranking…"}</p>
        : notice ? <p role="status" className="mt-4 rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p> : null}
    </section>

    <section className="mt-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-lg font-semibold text-slate-900">Candidate ranking</h2>
        {run ? <span className="text-xs text-slate-500">{new Date(run.created_at).toLocaleString()}</span> : null}
      </div>
      <p className="mt-1 text-sm text-slate-500">Scores show job-requirement coverage, not hiring-success probability.</p>
      {run ? <p className="mt-2 text-xs text-slate-500">{"Saved ranking weights: " + categories.map((category) => categoryLabels[category] + " " + run.configuration.category_weights[category] + "%").join(" · ")}</p> : null}
      {draftChanged.current && run ? <p className="mt-2 text-sm text-amber-800">Update the ranking to apply your changed weights.</p> : null}
      {run && proposal && run.requirement_version !== proposal.requirement_version ? <p className="mt-2 text-sm text-amber-800">This is an earlier ranking. Update it for the current job requirements.</p> : null}
      {run && proposal && run.formula_version !== proposal.formula_version ? <p className="mt-2 text-sm text-slate-600">This result uses an earlier scoring policy. Save weights and rank candidates to apply the current three-outcome policy.</p> : null}
      {ranked.length ? <div className="mt-4 overflow-x-auto"><table className="w-full text-left text-sm">
        <thead className="border-b border-slate-200 text-slate-500"><tr><th className="px-2 py-3">Rank</th><th className="px-2 py-3">Candidate</th><th className="px-2 py-3">Score</th><th className="px-2 py-3"><span className="sr-only">Evidence</span></th></tr></thead>
        <tbody>{ranked.map((result) => <tr key={result.id} className="border-b border-slate-100 last:border-0">
          <td className="px-2 py-4 font-semibold">{result.rank ?? "—"}</td><td className="px-2 py-4 font-medium">{result.candidate_name}</td>
          <td className="whitespace-nowrap px-2 py-4 font-semibold text-blue-700">{result.display_score + "%"}</td>
          <td className="px-2 py-4 text-right"><button type="button" id={"inspect-score-" + result.id} onClick={() => setEvidence(result)}
            aria-expanded={evidence?.id === result.id} aria-controls="scoring-evidence" className="rounded-lg px-2 py-1.5 font-semibold text-blue-700 hover:bg-blue-50">Inspect evidence</button></td>
        </tr>)}</tbody>
      </table></div> : <p className="mt-4 rounded-xl bg-slate-50 p-4 text-sm text-slate-500">
        {processing ? "Your ranking is being prepared." : "Set your weights and select “Save weights & rank candidates” to see the results."}
      </p>}
      {runs.length > 1 ? <details className="mt-5 border-t border-slate-200 pt-4">
        <summary className="cursor-pointer text-sm font-medium text-slate-600">Previous rankings</summary>
        <label className="mt-3 block text-sm text-slate-600">View an earlier result
          <select aria-label="Previous ranking" value={run?.id ?? ""} disabled={busy || processing} onChange={(event) => void selectRun(Number(event.target.value))}
            className="mt-2 w-full rounded-xl border border-slate-300 p-2.5">
            {runs.map((saved) => <option key={saved.id} value={saved.id}>{new Date(saved.created_at).toLocaleString()}</option>)}
          </select>
        </label>
      </details> : null}
    </section>
    {evidence ? <EvidencePanel result={evidence} onClose={closeEvidence} /> : null}
  </>;
}
