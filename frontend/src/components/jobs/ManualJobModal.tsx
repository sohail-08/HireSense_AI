import { useRef, useState, type FormEvent } from "react";
import { apiRequest } from "../../api/apiClient";
import type { JobDescriptionResponse } from "../../types";
import { PreviewModal } from "../common/PreviewModal";

const inputStyle = "mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100 disabled:opacity-60";
const requirements = (value: string) => [...new Set(value.split("\n").map(line => line.trim()).filter(Boolean))].map(name => ({ name, details: null }));

export function ManualJobModal({ onClose, onCreated }: { onClose: () => void; onCreated: (job: JobDescriptionResponse) => void }) {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [skills, setSkills] = useState("");
  const [preferred, setPreferred] = useState("");
  const [qualifications, setQualifications] = useState("");
  const [experience, setExperience] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const lock = useRef(false);
  const dirty = [title, content, skills, preferred, qualifications, experience].some(value => value.trim());
  const valid = title.trim().length >= 2 && !!content.trim() && requirements(skills).length > 0 &&
    (experience === "" || Number.isInteger(Number(experience)) && Number(experience) >= 0 && Number(experience) <= 100);
  function close() {
    if (!lock.current && (!dirty || window.confirm("Discard this unsaved job draft?"))) onClose();
  }
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!valid || lock.current) return;
    lock.current = true; setBusy(true); setError("");
    try {
      const job = await apiRequest<JobDescriptionResponse>("/job-descriptions/manual", {
        method: "POST", body: JSON.stringify({ title: title.trim(), content: content.trim(), required_skills: requirements(skills),
          preferred_skills: requirements(preferred), qualifications: requirements(qualifications), min_years_experience: experience === "" ? null : Number(experience) }),
      });
      onCreated(job);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "The draft could not be saved. Please try again."); }
    finally { lock.current = false; setBusy(false); }
  }
  return <PreviewModal title="Create job manually" onClose={close} busy={busy} wide>
    <p className="text-sm leading-6 text-slate-500">Write your own description and add the requirements used for CV screening. No chatbot is needed.</p>
    <form onSubmit={event => void save(event)} className="mt-5 space-y-4">
      <div><label htmlFor="manual-job-title" className="text-sm font-semibold text-slate-700">Job title <span className="text-rose-600">*</span></label><input id="manual-job-title" required minLength={2} maxLength={200} value={title} disabled={busy} onChange={event => setTitle(event.target.value)} placeholder="For example, Frontend Engineer" className={inputStyle} /></div>
      <div><label htmlFor="manual-job-content" className="text-sm font-semibold text-slate-700">Job description <span className="text-rose-600">*</span></label><textarea id="manual-job-content" required maxLength={50000} rows={7} value={content} disabled={busy} onChange={event => setContent(event.target.value)} placeholder="Describe the role, responsibilities, and what the candidate should know…" className={`${inputStyle} leading-7`} /></div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div><label htmlFor="manual-job-skills" className="text-sm font-semibold text-slate-700">Required skills <span className="text-rose-600">*</span></label><textarea id="manual-job-skills" required rows={3} value={skills} disabled={busy} onChange={event => setSkills(event.target.value)} placeholder={"React\nTypeScript\nREST APIs"} className={inputStyle} /><p className="mt-1.5 text-xs text-slate-500">One skill per line.</p></div>
        <div><label htmlFor="manual-job-qualifications" className="text-sm font-semibold text-slate-700">Qualifications <span className="font-normal text-slate-500">(optional)</span></label><textarea id="manual-job-qualifications" rows={3} value={qualifications} disabled={busy} onChange={event => setQualifications(event.target.value)} placeholder="One qualification per line" className={inputStyle} /></div>
        <div><label htmlFor="manual-job-experience" className="text-sm font-semibold text-slate-700">Minimum experience (years) <span className="font-normal text-slate-500">(optional)</span></label><input id="manual-job-experience" type="number" min={0} max={100} step={1} value={experience} disabled={busy} onChange={event => setExperience(event.target.value)} placeholder="For example, 3" className={inputStyle} /></div>
        <div><label htmlFor="manual-job-preferred" className="text-sm font-semibold text-slate-700">Preferred skills <span className="font-normal text-slate-500">(optional)</span></label><textarea id="manual-job-preferred" rows={2} value={preferred} disabled={busy} onChange={event => setPreferred(event.target.value)} placeholder="One skill per line" className={inputStyle} /></div>
      </div>
      {error ? <p role="alert" className="rounded-xl bg-rose-50 p-3 text-sm text-rose-800">{error}</p> : null}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4"><p className="text-xs text-slate-500">Saved as a draft. Review and approve it before publishing.</p><div className="flex gap-2"><button type="button" disabled={busy} onClick={close} className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-600 hover:bg-slate-50 disabled:opacity-50">Cancel</button><button type="submit" disabled={!valid || busy} className="rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50">{busy ? "Saving draft…" : "Save draft"}</button></div></div>
    </form>
  </PreviewModal>;
}
