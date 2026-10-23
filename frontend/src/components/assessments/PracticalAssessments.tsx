import { Link } from "react-router-dom";
import { type PracticalReport, exerciseLabel } from "../interviews/workSampleApi";
import { ExerciseFindings } from "../interviews/WorkSampleShared";

export function PracticalAssessments({ values }: { values: PracticalReport[] }) {
  if (!values.length) return null;
  return <section aria-label="Practical assessments" className="mt-6"><h3 className="text-lg font-bold">Practical assessment</h3><p className="mt-1 text-xs text-slate-500">AI correctness score, approved by the interviewer · contributes 10% to the current final-score formula. Historical reviews retain their saved assessment method.</p>
    {values.map(value => <section key={value.exercise_id} className="mt-3 rounded-2xl border border-indigo-100 p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><h4 className="font-semibold text-slate-800">{value.title}</h4><p className="mt-1 text-xs text-slate-500">{exerciseLabel(value.status)} · {exerciseLabel(value.review_status)}</p></div>{value.assessment ? <span className="rounded-xl bg-indigo-50 px-3 py-2 text-sm font-bold text-indigo-800">{value.assessment.score === null || value.assessment.score === undefined ? "Needs verification" : `${value.assessment.score}%`}</span> : null}</div>
      {value.assessment ? <ExerciseFindings task={value.task} result={value.assessment} /> : <p className="mt-3 text-sm text-slate-500">No interviewer-approved assessment yet. No practical score has been assigned to this report.</p>}
      <details className="mt-4"><summary className="cursor-pointer text-sm font-medium text-indigo-700">View saved work</summary><pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-slate-50 p-4 text-xs leading-6">{value.content || "No response was saved."}</pre><p className="mt-3 break-all text-xs text-slate-400">Task: {value.task_hash}<br />Submission: {value.submission_hash}</p></details>
      <Link className="mt-4 inline-block text-xs font-medium text-indigo-700" to={`/interviews/${value.interview_id}/console`}>Open interview workspace →</Link>
    </section>)}
  </section>;
}
