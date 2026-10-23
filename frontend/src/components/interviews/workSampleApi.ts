import { apiRequest, API_URL, ApiError } from "../../api/apiClient";

export type Criterion = { id: string; title: string; description: string; weight: number };
export type ExerciseTask = { title: string; instructions: string; materials: string; deliverables: string;
  duration_minutes: number; tools_policy: string; response_type: "code" | "text"; criteria: Criterion[] };
export type ExerciseEvidence = { field: "content" | "explanation" | "discussion"; segment_id?: string | null; line_start: number; line_end: number; quote: string };
export type ExerciseFinding = { criterion_id: string; label: "met" | "partially_met" | "unmet" | "needs_verification";
  reason: string; evidence: ExerciseEvidence[] };
export type ExerciseEvaluation = { summary: string; findings: ExerciseFinding[]; score?: number | null; limitation?: string;
  discussion_sources?: { id: string; speaker: string; text: string; start_offset_ms: number; source_hash: string }[] };
export type ExerciseAttempt = { id: number; number: number; status: string; content: string; explanation: string;
  revision: number; remaining_seconds: number; deadline_at: string | null; started_at: string | null;
  saved_at: string | null; finished_at: string | null; submission_hash: string | null };
export type ExerciseAssessment = { id: number; attempt_id: number; status: string; result: ExerciseEvaluation;
  approved_result: ExerciseEvaluation | null; review_reason: string | null; approved_by: number | null;
  approved_at: string | null; error: string | null };
export type Exercise = { id: number; task: ExerciseTask; task_hash: string; status: string; version: number;
  approved_at: string | null; attempt: ExerciseAttempt | null; attempts?: ExerciseAttempt[];
  assessments?: ExerciseAssessment[]; events?: { kind: string; actor: string; reason: string; at: string }[] };
export type ExerciseState = { exercise: Exercise | null; server_now: string };
export type PracticalReport = { interview_id: number; exercise_id: number; title: string; task: ExerciseTask;
  task_hash: string; attempt: number; status: string; content: string; explanation: string; submission_hash: string;
  review_status: string; assessment: ExerciseEvaluation | null; approved_by: number | null; approved_at: string | null };

const base = (id: number) => `/work-samples/interviews/${id}`;
const post = <T,>(path: string, data: object = {}) => apiRequest<T>(path, { method: "POST", body: JSON.stringify(data) });
async function candidate<T>(path = "", data?: object): Promise<T> {
  let response: Response;
  try { response = await fetch(`${API_URL}/interview-rooms/candidate/work-sample${path}`, {
    method: data ? "POST" : "GET", credentials: "include", cache: "no-store",
    headers: data ? { "Content-Type": "application/json" } : undefined,
    body: data ? JSON.stringify(data) : undefined,
  }); } catch { throw new ApiError("Connection lost. Keep this page open and check the save status.", 0); }
  const value = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(typeof value?.detail === "string" ? value.detail : "Exercise access is unavailable.", response.status);
  return value as T;
}
export const workSampleApi = {
  read: (id: number) => apiRequest<ExerciseState>(base(id), { cache: "no-store" }),
  save: (id: number, task: ExerciseTask, version: number) => apiRequest<ExerciseState>(base(id), { method: "PUT", body: JSON.stringify({ task, version }) }),
  action: (id: number, version: number, action: string, reason = "", extra_minutes = 5) => post<ExerciseState>(`${base(id)}/action`, { version, action, reason, extra_minutes }),
  templates: () => apiRequest<{ id: number; task: ExerciseTask }[]>("/work-samples/templates"),
  template: (task: ExerciseTask) => post<{ id: number; task: ExerciseTask }>("/work-samples/templates", task),
  draft: (id: number, brief: string) => post<{ task: ExerciseTask; notice: string; sources: { title: string; excerpt: string }[] }>(`${base(id)}/draft`, { brief }),
  assess: (id: number, discussion_segment_ids: string[] = []) => post<ExerciseState>(`${base(id)}/assess`, { discussion_segment_ids }),
  review: (id: number, assessment_id: number, result: ExerciseEvaluation, reason: string) => post<ExerciseState>(`${base(id)}/review`, {
    assessment_id, result: { summary: result.summary, findings: result.findings }, reason }),
  candidateRead: () => candidate<ExerciseState>(),
  ready: (attempt_id: number) => candidate<ExerciseState>("/ready", { attempt_id }),
  candidateSave: (attempt_id: number, revision: number, content: string, explanation: string, submit = false) => candidate<ExerciseState>("/save", { attempt_id, revision, content, explanation, submit }),
};
export const exerciseFinished = (status: string) => ["submitted", "time_ended", "interview_ended"].includes(status);
export const exerciseLabel = (value: string) => ({ shared: "Read the task", ready: "Ready to start", running: "In progress", paused: "Paused",
  submitted: "Submitted", time_ended: "Time ended", interview_ended: "Interview ended", draft: "Private draft",
  needs_verification: "Needs verification", partially_met: "Partially met", met: "Met", unmet: "Not met" }[value] ?? value.replaceAll("_", " "));
