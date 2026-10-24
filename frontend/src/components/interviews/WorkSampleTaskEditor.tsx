import { type ExerciseTask } from "./workSampleApi";
import { exerciseInput } from "./WorkSampleShared";
export const emptyExerciseTask: ExerciseTask = {
  title: "", instructions: "", materials: "", deliverables: "", duration_minutes: 15, response_type: "text",
  tools_policy: "Use only the supplied materials. External AI assistance and help from other people are not permitted.",
};
export function WorkSampleTaskEditor({ task, onChange, disabled }: { task: ExerciseTask; onChange: (task: ExerciseTask) => void; disabled: boolean }) {
  return <fieldset disabled={disabled} className="min-w-0 space-y-4">
    <label className="block text-sm font-medium text-slate-700">Task title<input className={exerciseInput} value={task.title} maxLength={180} onChange={e => onChange({ ...task, title: e.target.value })} /></label>
    <label className="block text-sm font-medium text-slate-700">Instructions<textarea className={exerciseInput} rows={4} value={task.instructions} maxLength={12000} onChange={e => onChange({ ...task, instructions: e.target.value })} /></label>
    <label className="block text-sm font-medium text-slate-700">Materials or starter code<textarea className={`${exerciseInput} font-mono`} rows={5} value={task.materials} maxLength={20000} onChange={e => onChange({ ...task, materials: e.target.value })} /></label>
    <label className="block text-sm font-medium text-slate-700">What the candidate should submit<textarea className={exerciseInput} rows={2} value={task.deliverables} maxLength={2000} onChange={e => onChange({ ...task, deliverables: e.target.value })} /></label>
    <div className="grid gap-3 sm:grid-cols-2"><label className="block text-sm font-medium text-slate-700">Duration (1–15 minutes)<input type="number" min={1} max={15} className={exerciseInput} value={task.duration_minutes} onChange={e => onChange({ ...task, duration_minutes: Number(e.target.value) })} /></label><label className="block text-sm font-medium text-slate-700">Response format<select className={exerciseInput} value={task.response_type} onChange={e => onChange({ ...task, response_type: e.target.value as "code" | "text" })}><option value="text">Written response</option><option value="code">Code</option></select></label></div>
    <label className="block text-sm font-medium text-slate-700">Permitted tools & assistance<textarea className={exerciseInput} rows={2} value={task.tools_policy} maxLength={2000} onChange={e => onChange({ ...task, tools_policy: e.target.value })} /></label>
  </fieldset>;
}
