import { StyledSelect } from "../common/StyledSelect";

type Job = { id: number; title: string; application_count: number };
type Props = { jobs: Job[]; value?: number; loading: boolean; onChange: (id: number) => void };

export function JobPostingSelect({ jobs, value, loading, onChange }: Props) {
  return <div>
    <label htmlFor="screening-job" className="block text-xs font-semibold text-slate-600">Job posting</label>
    <StyledSelect id="screening-job" label="Job posting" value={value === undefined ? "" : String(value)} disabled={loading}
      placeholder={loading ? "Loading jobs…" : "No job postings available"} className="mt-1.5" minMenuWidth={300}
      options={jobs.map(job => ({ value: String(job.id), label: job.title, description: `Posting #${job.id} · ${job.application_count} ${job.application_count === 1 ? "candidate" : "candidates"}` }))}
      onChange={value => onChange(Number(value))}
      icon={<span aria-hidden="true" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600"><svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="3" y="7" width="18" height="14" rx="3" /><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12a23 23 0 0 0 18 0M12 11v4" /></svg></span>} />
  </div>;
}
