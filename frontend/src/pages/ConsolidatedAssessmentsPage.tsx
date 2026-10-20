import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { apiRequest } from "../api/apiClient";
import { useSupervisor } from "../components/assistant/SupervisorProvider";
import { assessmentApi, type ApplicationAssessments, type Assessment, type Comparison } from "../components/assessments/assessmentApi";
import { AssessmentView, ComparisonView, reportButton, text } from "../components/assessments/AssessmentView";
import type { ScreeningJobOption } from "../types";

export function ConsolidatedAssessmentsPage() {
  const [params, setParams] = useSearchParams();
  const { setSelectedJobPostingId, setSelectedApplicationIds, refreshVersion } = useSupervisor();
  const [jobs, setJobs] = useState<ScreeningJobOption[]>([]);
  const [job, setJob] = useState<number>();
  const [applications, setApplications] = useState<ApplicationAssessments[]>([]);
  const [selected, setSelected] = useState<ApplicationAssessments>();
  const [report, setReport] = useState<Assessment>();
  const [comparison, setComparison] = useState<Comparison>();
  const [cohort, setCohort] = useState<number[]>([]);
  const [interviews, setInterviews] = useState<number[] | undefined>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const ids = applications.filter(app => app.versions.some(v => cohort.includes(v.id))).map(app => app.application_id);
    setSelectedApplicationIds(ids.length ? ids : selected ? [selected.application_id] : []);
  }, [cohort, selected?.application_id, applications, setSelectedApplicationIds]);
  useEffect(() => {
    let active = true;
    void apiRequest<ScreeningJobOption[]>("/screening/jobs").then(async values => {
      if (!active) return;
      setJobs(values);
      const appId = Number(params.get("application"));
      const initial = appId ? await assessmentApi.application(appId) : undefined;
      if (active) setJob(current => initial?.job_posting_id ?? current ?? values[0]?.id);
    }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    setSelectedJobPostingId(job);
    setCohort([]);
    return () => { setSelectedJobPostingId(undefined); setSelectedApplicationIds([]); };
  }, [job, setSelectedJobPostingId, setSelectedApplicationIds]);
  useEffect(() => {
    if (!job) return;
    let active = true;
    setError(""); setApplications([]);
    void assessmentApi.list(job).then(async values => {
      if (!active) return;
      const requestedApp = Number(params.get("application"));
      if (requestedApp && !values.some(a => a.application_id === requestedApp)) {
        const target = await assessmentApi.application(requestedApp);
        if (active && target.job_posting_id !== job) { setJob(target.job_posting_id); return; }
      }
      if (!active) return;
      setApplications(values);
      const app = values.find(a => a.application_id === Number(params.get("application"))) ?? values[0];
      setSelected(app); setInterviews(undefined);
      setSelectedApplicationIds(app ? [app.application_id] : []);
      const id = Number(params.get("run")) || app?.versions[0]?.id;
      if (id && app?.versions.some(v => v.id === id)) void assessmentApi.read(id).then(r => { if (active) setReport(r); }).catch(e => { if (active) setError(e.message); });
      else setReport(undefined);
    }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [job, refreshVersion, params.get("application"), params.get("run")]);
  useEffect(() => {
    const id = Number(params.get("comparison"));
    if (id) void assessmentApi.comparison(id).then(value => { setComparison(value); setJob(value.snapshot.assessments[0]?.job_posting_id); }).catch(e => setError(e.message));
  }, [params.get("comparison")]);
  useEffect(() => {
    if (!report || !["queued", "processing"].includes(report.status)) return;
    let active = true, polling = false;
    const timer = window.setInterval(() => {
      if (polling) return;
      polling = true;
      void assessmentApi.read(report.id).then(async value => {
        if (!active) return;
        setReport(value);
        if (!["queued", "processing"].includes(value.status) && job) {
          const items = await assessmentApi.list(job);
          if (active) { setApplications(items); setSelected(items.find(a => a.application_id === value.application_id)); }
        }
      }).catch(e => { if (active) setError(e.message); }).finally(() => { polling = false; });
    }, 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, [report?.id, report?.status, job]);
  async function select(app: ApplicationAssessments) {
    setSelected(app); setReport(undefined); setInterviews(undefined); setError("");
    setSelectedApplicationIds([app.application_id]);
    setParams({ application: String(app.application_id) });
    try { if (app.versions[0]) setReport(await assessmentApi.read(app.versions[0].id)); }
    catch (e) { setError(e instanceof Error ? e.message : "Report could not load."); }
  }
  async function generate() {
    if (!selected) return;
    setBusy(true); setError("");
    try {
      const value = await assessmentApi.generate(selected.application_id, Boolean(report), interviews);
      setReport(await assessmentApi.read(value.id));
      setParams({ application: String(selected.application_id), run: String(value.id) });
    } catch (e) { setError(e instanceof Error ? e.message : "Generation request failed."); }
    finally { setBusy(false); }
  }
  return <div className="mx-auto max-w-7xl p-4 sm:p-6">
    <h1 className="text-3xl font-bold">Candidate assessment reports</h1>
    <p className="mt-2 text-sm text-slate-600">Consolidate saved CV and interview evidence. Generating a report does not re-screen CVs or re-analyze interviews.</p>
    {error ? <p role="alert" className="my-3 rounded bg-red-50 p-3 text-red-700">{error}</p> : null}
    <section className="my-5 rounded-xl border bg-white p-4">
      <label className="block text-sm font-semibold">Job posting<select className="mt-2 block w-full rounded border p-2" value={job ?? ""} onChange={e => { setJob(Number(e.target.value)); setSelected(undefined); setReport(undefined); setComparison(undefined); setParams({}); }}><option value="" disabled>Select a job</option>{jobs.map(j => <option key={j.id} value={j.id}>{j.title}</option>)}</select></label>
      <div className="mt-4 grid gap-2 sm:grid-cols-2">{applications.map(app => {
        const latest = app.versions.find(v => v.status === "completed");
        return <div key={app.application_id} className={`flex items-center gap-3 rounded-lg border p-3 ${selected?.application_id === app.application_id ? "border-blue-500 bg-blue-50" : ""}`}>
          <input type="checkbox" aria-label={`Compare application ${app.application_id}`} disabled={!latest || (!cohort.includes(latest.id) && cohort.length >= 4)} checked={Boolean(latest && cohort.includes(latest.id))} onChange={e => { if (latest) setCohort(ids => e.target.checked ? [...ids, latest.id] : ids.filter(id => id !== latest.id)); }} />
          <button className="min-w-0 flex-1 text-left" onClick={() => void select(app)}><p className="font-semibold">{app.identification.candidate_name}</p><p className="text-xs">Application #{app.application_id} · {app.versions[0] ? `Version ${app.versions[0].version}: ${text(app.versions[0].status)}` : "Not generated"}</p></button>
        </div>;
      })}</div>
      {!applications.length ? <p className="mt-3 text-sm">No collected applications for this job.</p> : null}
      <button className={`${reportButton} mt-4`} disabled={busy || cohort.length < 2} onClick={() => { setBusy(true); setError(""); void assessmentApi.compare(cohort).then(value => { setComparison(value); setParams({ comparison: String(value.id) }); }).catch(e => setError(e.message)).finally(() => setBusy(false)); }}>Compare selected reports ({cohort.length}/4)</button>
      <p className="mt-2 text-xs text-slate-500">Comparison selects the latest completed report for each checked application. Exact versions and the cohort are saved.</p>
    </section>
    {selected ? <section className="rounded-xl border bg-white p-4"><h2 className="font-bold">Report sources · {selected.identification.candidate_name}</h2>
      <p className="mt-2 text-sm">Default: latest completed interview, identified by scheduled start time. Optionally select specific interviews below.</p>
      <details className="mt-3"><summary className="cursor-pointer">Choose interview sessions</summary><label className="mt-2 block text-sm"><input type="checkbox" checked={interviews === undefined} onChange={e => setInterviews(e.target.checked ? undefined : [])} /> Use latest completed interview automatically</label>{selected.interviews.map(i => <label key={i.id} className="mt-2 block text-sm"><input type="checkbox" checked={interviews?.includes(i.id) ?? false} disabled={interviews === undefined || (!interviews.includes(i.id) && interviews.length >= 5)} onChange={e => setInterviews(ids => e.target.checked ? [...(ids ?? []), i.id] : ids?.filter(id => id !== i.id))} /> Interview #{i.id} · {new Date(i.date).toLocaleString()} · {i.status}</label>)}</details>
      <p className="my-3 text-sm">{selected.missing.length ? `Sources missing or incomplete: ${selected.missing.join("; ")}. A clearly labelled partial report can still be generated.` : "Saved source readiness checks passed."}</p>
      <div className="flex flex-wrap gap-3"><button className={`${reportButton} bg-blue-600 text-white`} disabled={busy || Boolean(report && ["queued", "processing"].includes(report.status))} onClick={() => void generate()}>{report ? "Generate new version" : "Generate assessment"}</button>
        {selected.versions.length ? <label className="text-sm">Saved version <select className="rounded border p-2" value={report?.id ?? ""} onChange={e => { const id = Number(e.target.value); void assessmentApi.read(id).then(setReport).catch(e => setError(e.message)); setParams({ application: String(selected.application_id), run: String(id) }); }}><option value="" disabled>Select version</option>{selected.versions.map(v => <option key={v.id} value={v.id}>v{v.version} · {v.status} · {v.completeness}</option>)}</select></label> : null}</div>
    </section> : null}
    {comparison ? <ComparisonView key={comparison.id} value={comparison} /> : null}
    {report ? <AssessmentView key={report.id} report={report} onReviewed={setReport} /> : null}
  </div>;
}
