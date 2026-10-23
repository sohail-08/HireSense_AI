import { type ExerciseTask } from "./workSampleApi";
import { exerciseButton, exerciseInput } from "./WorkSampleShared";

export const emptyExerciseTask: ExerciseTask = {
  title: "", instructions: "", materials: "", deliverables: "", duration_minutes: 15, response_type: "text",
  tools_policy: "Use only the supplied materials. External AI assistance and help from other people are not permitted.",
  criteria: [
    { id: "correctness", title: "Correctness", description: "The response addresses the task accurately using the supplied information.", weight: 50 },
    { id: "constraints", title: "Handling constraints", description: "The response respects the task's requirements and relevant edge cases.", weight: 30 },
    { id: "explanation", title: "Explanation", description: "The candidate explains the reasoning behind their approach.", weight: 20 },
  ],
};

export function WorkSampleTaskEditor({ task, onChange, disabled }: { task: ExerciseTask; onChange: (task: ExerciseTask) => void; disabled: boolean }) {
  const total = task.criteria.reduce((sum, c) => sum + c.weight, 0);
  return <fieldset disabled={disabled} className="min-w-0 space-y-4">
    <label className="block text-sm font-medium text-slate-700">Task title<input className={exerciseInput} value={task.title} maxLength={180} onChange={e => onChange({ ...task, title: e.target.value })} /></label>
    <label className="block text-sm font-medium text-slate-700">Instructions<textarea className={exerciseInput} rows={4} value={task.instructions} maxLength={12000} onChange={e => onChange({ ...task, instructions: e.target.value })} /></label>
    <label className="block text-sm font-medium text-slate-700">Materials or starter code<textarea className={`${exerciseInput} font-mono`} rows={5} value={task.materials} maxLength={20000} onChange={e => onChange({ ...task, materials: e.target.value })} /></label>
    <label className="block text-sm font-medium text-slate-700">Expected deliverables<textarea className={exerciseInput} rows={2} value={task.deliverables} maxLength={2000} onChange={e => onChange({ ...task, deliverables: e.target.value })} /></label>
    <div className="grid gap-3 sm:grid-cols-2"><label className="block text-sm font-medium text-slate-700">Duration (minutes)<input type="number" min={3} max={120} className={exerciseInput} value={task.duration_minutes} onChange={e => onChange({ ...task, duration_minutes: Number(e.target.value) })} /></label><label className="block text-sm font-medium text-slate-700">Response format<select className={exerciseInput} value={task.response_type} onChange={e => onChange({ ...task, response_type: e.target.value as "code" | "text" })}><option value="text">Written response</option><option value="code">Code + explanation</option></select></label></div>
    <label className="block text-sm font-medium text-slate-700">Permitted tools & assistance<textarea className={exerciseInput} rows={2} value={task.tools_policy} maxLength={2000} onChange={e => onChange({ ...task, tools_policy: e.target.value })} /></label>
    <div><h4 className="text-sm font-semibold text-slate-800">Assessment criteria <span className={`ml-2 text-xs ${total === 100 ? "text-emerald-700" : "text-amber-700"}`}>{total}/100%</span></h4><p className="mt-1 text-xs text-slate-500">Visible to the candidate. Locked when you approve and share.</p>
      {task.criteria.map((criterion, i) => <div key={criterion.id} className="mt-3 rounded-xl border border-slate-200 bg-slate-50/60 p-3"><div className="grid grid-cols-[1fr_5rem] gap-2"><label className="text-xs text-slate-500">Criterion title<input aria-label={`Criterion ${i + 1} title`} className={exerciseInput} value={criterion.title} maxLength={100} onChange={e => onChange({ ...task, criteria: task.criteria.map((c, n) => n === i ? { ...c, title: e.target.value } : c) })} /></label><label className="text-xs text-slate-500">Weight %<input aria-label={`Criterion ${i + 1} weight`} type="number" min={1} max={100} className={exerciseInput} value={criterion.weight} onChange={e => onChange({ ...task, criteria: task.criteria.map((c, n) => n === i ? { ...c, weight: Number(e.target.value) } : c) })} /></label></div><label className="mt-2 block text-xs text-slate-500">What this measures<textarea aria-label={`Criterion ${i + 1} description`} rows={2} className={exerciseInput} value={criterion.description} maxLength={1000} onChange={e => onChange({ ...task, criteria: task.criteria.map((c, n) => n === i ? { ...c, description: e.target.value } : c) })} /></label>{task.criteria.length > 1 ? <button type="button" className="mt-2 text-xs text-red-700" onClick={() => onChange({ ...task, criteria: task.criteria.filter((_, n) => n !== i) })}>Remove criterion</button> : null}</div>)}
      {task.criteria.length < 8 ? <button type="button" className={`${exerciseButton} mt-3`} onClick={() => onChange({ ...task, criteria: [...task.criteria, { id: `criterion_${Date.now()}`, title: "", description: "", weight: 10 }] })}>Add criterion</button> : null}
    </div>
  </fieldset>;
}
