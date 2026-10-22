import { useCallback, useEffect, useRef, useState } from "react";
import { apiRequest } from "../api/apiClient";
import { useSupervisor } from "../components/assistant/SupervisorProvider";
import { PreviewModal } from "../components/common/PreviewModal";
import { SavedJobsCards } from "../components/jobs/SavedJobsCards";
import { ManualJobModal } from "../components/jobs/ManualJobModal";
import { JobDescriptionEditor } from "../components/jobs/JobDescriptionEditor";
import { JobRequirementsPanel } from "../components/jobs/JobRequirementsPanel";
import { JobKnowledgeModal } from "../components/jobs/JobKnowledgeModal";
import type { JobDescriptionResponse, RequirementProfileDraft } from "../types";

const message = (failure: unknown) => failure instanceof Error ? failure.message : "Something went wrong. Please try again.";

export function JobDescriptionPage() {
  const { response, loading: chatLoading, open: chatPanelOpen, setOpen, startNewWorkflow, sendMessage,
    addTaskMessage, setSelectedJobDescriptionId, refreshVersion } = useSupervisor();
  const [jobs, setJobs] = useState<JobDescriptionResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState("");
  const [reload, setReload] = useState(0);
  const [job, setJob] = useState<JobDescriptionResponse>();
  const [profile, setProfile] = useState<RequirementProfileDraft>();
  const [profileId, setProfileId] = useState<number>();
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [creating, setCreating] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [knowledgeOpen, setKnowledgeOpen] = useState(false);
  const [manualOpen, setManualOpen] = useState(false);
  const [approving, setApproving] = useState(false);
  const [postingRefresh, setPostingRefresh] = useState(0);
  const mutation = useRef(false);
  const listRequest = useRef(0);
  const workspace = useRef<HTMLElement>(null);
  const dirty = Boolean(job?.status === "draft" && (title !== job.title || content !== job.content));

  const loadJobs = useCallback(async () => {
    const request = ++listRequest.current;
    setLoading(true); setListError("");
    try {
      const items = await apiRequest<JobDescriptionResponse[]>("/job-descriptions");
      if (request === listRequest.current) setJobs(items);
    } catch (failure) { if (request === listRequest.current) setListError(message(failure)); }
    finally { if (request === listRequest.current) setLoading(false); }
  }, []);
  useEffect(() => {
    void loadJobs();
    return () => { listRequest.current++; };
  }, [loadJobs, reload, refreshVersion]);
  useEffect(() => {
    setSelectedJobDescriptionId(job?.id);
    return () => setSelectedJobDescriptionId(undefined);
  }, [job?.id, setSelectedJobDescriptionId]);
  useEffect(() => {
    if (!response) {
      setProfile(undefined); setProfileId(undefined); setJob(undefined); setTitle(""); setContent("");
      return;
    }
    setProfile(response.requirement_state.profile);
    setProfileId(response.requirement_profile_id ?? undefined);
    if (response.job_description) {
      const next = response.job_description;
      setJob(next); setTitle(next.title); setContent(next.content);
      setJobs(items => [next, ...items.filter(item => item.id !== next.id)]);
    } else { setJob(undefined); setTitle(""); setContent(""); }
    if (!detailsOpen) setCreating(true);
    if (response.job_posting || response.refresh_required) setPostingRefresh(value => value + 1);
  }, [response]);

  function allowDiscard() {
    return !dirty || window.confirm("Discard your unsaved changes? The last saved version will be kept.");
  }
  function showJob(next: JobDescriptionResponse) {
    setJob(next); setTitle(next.title); setContent(next.content); setError(""); setNotice("");
  }
  function openJob(next: JobDescriptionResponse) {
    if (mutation.current || !allowDiscard()) return;
    showJob(next); setCreating(false); setDetailsOpen(true);
  }
  function closeDetails() {
    if (mutation.current || chatLoading || !allowDiscard()) return;
    if (job) { setTitle(job.title); setContent(job.content); }
    setDetailsOpen(false);
  }
  function openAssistant() {
    setOpen(true);
    window.requestAnimationFrame(() => document.getElementById("supervisor-message")?.focus());
  }
  function createJob() {
    if (mutation.current || chatLoading || !allowDiscard()) return;
    if (response && !window.confirm("Start a new job? This resets the assistant conversation. Your saved jobs will not be deleted.")) return;
    startNewWorkflow(); setJob(undefined); setTitle(""); setContent(""); setProfile(undefined); setProfileId(undefined);
    setDetailsOpen(false); setCreating(true); setError(""); setNotice(""); openAssistant();
    window.requestAnimationFrame(() => workspace.current?.scrollIntoView?.({ block: "nearest", behavior: "smooth" }));
  }
  function createManually() {
    if (mutation.current || chatLoading || !allowDiscard()) return;
    setManualOpen(true);
  }
  function upsert(next: JobDescriptionResponse) {
    setJobs(items => [next, ...items.filter(item => item.id !== next.id)]);
    showJob(next);
  }
  async function saveJob() {
    if (!job || job.status !== "draft" || !dirty || mutation.current || chatLoading || !title.trim() || !content.trim()) return;
    mutation.current = true; setBusy(true); setError(""); setNotice("");
    try {
      const saved = await apiRequest<JobDescriptionResponse>(`/job-descriptions/${job.id}`, {
        method: "PATCH", body: JSON.stringify({ title, content }),
      });
      upsert(saved); setNotice("Changes saved."); addTaskMessage("success", "Job-description edits were saved.");
    } catch (failure) { setError(message(failure)); }
    finally { mutation.current = false; setBusy(false); }
  }
  async function reviseJob(source: JobDescriptionResponse) {
    if (mutation.current || chatLoading || !allowDiscard()) return;
    mutation.current = true; setBusy(true); setError(""); setNotice("");
    try {
      const draft = await apiRequest<JobDescriptionResponse>(`/job-descriptions/${source.id}/revise`, { method: "POST" });
      upsert(draft); setCreating(false); setDetailsOpen(true);
      addTaskMessage("success", `Created editable version ${draft.version} of “${draft.title}”.`);
    } catch (failure) { setError(message(failure)); }
    finally { mutation.current = false; setBusy(false); }
  }
  async function approveJob() {
    if (!job || job.status !== "draft" || dirty || mutation.current || chatLoading) return;
    mutation.current = true; setBusy(true); setApproving(true); setError(""); setNotice("");
    try {
      const approved = await apiRequest<JobDescriptionResponse>(`/job-descriptions/${job.id}/approve`, { method: "POST" });
      upsert(approved); setNotice("Job description approved.");
      addTaskMessage("success", `Approved “${approved.title}”.`);
    } catch (failure) { setError(message(failure)); }
    finally { mutation.current = false; setBusy(false); setApproving(false); }
  }
  async function deleteJob(source: JobDescriptionResponse) {
    if (mutation.current || chatLoading || !window.confirm(`Delete “${source.title}” version ${source.version}? Any job post already published to Discord will remain there.`)) return;
    mutation.current = true; setBusy(true); setError(""); setNotice("");
    try {
      await apiRequest(`/job-descriptions/${source.id}`, { method: "DELETE" });
      listRequest.current++; setLoading(false);
      setJobs(items => items.filter(item => item.id !== source.id));
      if (job?.id === source.id) { setJob(undefined); setTitle(""); setContent(""); setDetailsOpen(false); }
      setNotice(`Deleted “${source.title}”.`); addTaskMessage("success", `Deleted “${source.title}” version ${source.version}.`);
    } catch (failure) { setError(message(failure)); }
    finally { mutation.current = false; setBusy(false); }
  }
  const editor = job ? <JobDescriptionEditor job={job} title={title} content={content} busy={busy || chatLoading} approving={approving}
    onTitle={setTitle} onContent={setContent} onSave={() => void saveJob()}
    onApprove={() => void approveJob()}
    onRevise={() => void reviseJob(job)} refreshKey={postingRefresh} /> : null;
  const feedback = <>{error ? <p role="alert" className="mt-4 rounded-xl bg-rose-50 p-3 text-sm text-rose-800">{error}</p> : null}{notice ? <p role="status" className="mt-4 rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p> : null}</>;

  return <section className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6">
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div><h1 className="text-3xl font-bold tracking-tight text-slate-900">Jobs</h1><p className="mt-2 text-sm text-slate-500">Create job descriptions, review drafts, and prepare approved jobs for publishing.</p></div>
      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={busy} onClick={() => setKnowledgeOpen(true)} className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-600 hover:bg-slate-50 disabled:opacity-50"><svg aria-hidden="true" className="h-4 w-4 text-sky-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M4 4h6a3 3 0 0 1 3 3v14a4 4 0 0 0-4-3H4ZM20 4h-4a3 3 0 0 0-3 3v14a4 4 0 0 1 4-3h3Z" /></svg>Reference documents</button>
        <button type="button" disabled={busy || chatLoading} onClick={createJob} className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-blue-200 bg-white px-4 py-2.5 text-sm font-semibold text-blue-700 hover:bg-blue-50 disabled:opacity-50">Create with assistant</button>
        <button type="button" disabled={busy || chatLoading} onClick={createManually} className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:opacity-50"><span aria-hidden="true" className="text-lg leading-none">+</span>Create manually</button>
      </div>
    </header>
    {!detailsOpen ? feedback : null}
    <SavedJobsCards jobs={jobs} loading={loading} error={listError} busy={busy || chatLoading} onRetry={() => setReload(value => value + 1)}
      onOpen={openJob} onRevise={source => void reviseJob(source)} onDelete={source => void deleteJob(source)} onCreate={createManually} />
    {creating && !detailsOpen ? <section ref={workspace} aria-label="Current job workspace" className="mt-6 scroll-mt-24 rounded-2xl border border-blue-100 bg-blue-50/30 p-4 sm:p-5">
      <header className="mb-4 flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold text-slate-800">{job ? "Review your job description" : "Create a job"}</h2><p className="mt-1 text-sm text-slate-500">{job ? "Save any changes, then approve it when you are ready." : "Tell the assistant the role, skills, and experience you need."}</p></div><button type="button" disabled={chatLoading} aria-controls="supervisor-chat-panel" aria-expanded={chatPanelOpen} onClick={openAssistant} className="rounded-xl border border-blue-200 bg-white px-3 py-2 text-sm font-semibold text-blue-700 hover:bg-blue-50">{chatPanelOpen ? "Continue with assistant" : "Open assistant"}</button></header>
      {profile ? <JobRequirementsPanel profile={profile} confirmed={Boolean(profileId)} canConfirm={response?.phase === "requirement_confirmation" && response.requirement_state.proposal_ready && !profileId} busy={chatLoading} onConfirm={() => void sendMessage("Use it.")} /> : <p className="rounded-xl bg-white p-4 text-sm leading-6 text-slate-600">For example: “I need a frontend engineer with React skills and 3 years of experience.”</p>}
      {profileId && !job ? <button type="button" disabled={chatLoading} onClick={() => void sendMessage("Generate the job description.")} className="mt-4 rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50">{chatLoading ? "Working…" : "Generate job description"}</button> : null}
      {editor ? <div className="mt-4 rounded-2xl border border-slate-200 bg-white p-5">{editor}</div> : null}
    </section> : null}
    {detailsOpen && job ? <PreviewModal title={job.status === "draft" ? "Edit job draft" : "Job details"} onClose={closeDetails} busy={busy || chatLoading} wide>{editor}{feedback}</PreviewModal> : null}
    {knowledgeOpen ? <JobKnowledgeModal onClose={() => setKnowledgeOpen(false)} /> : null}
    {manualOpen ? <ManualJobModal onClose={() => setManualOpen(false)} onCreated={saved => { setManualOpen(false); upsert(saved); setCreating(false); setDetailsOpen(true); setNotice("Draft saved. Review it and approve when ready."); }} /> : null}
  </section>;
}
