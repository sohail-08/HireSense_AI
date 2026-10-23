import { apiRequest, API_URL, TOKEN_KEY, ApiError } from "../../api/apiClient";

export type Fact = { id: string; text: string; evidence_ids: string[] };
export type Evidence = { id: string; kind: string; quote: string; locator: string; source_version: string; source_text?: string };
export type MatrixRow = { requirement_id: string; name: string; classification: string; version: string; weight: string | number;
  cv_status: string; cv_score_outcome?: string; cv_evidence_ids: string[]; interview_statuses: string[]; interview_coverage: string;
  questions_asked: { pair_id: string; interview_id: number; state: string }[];
  interview_evidence: { pair_id: string; interview_id: number; status: string; conclusion: string; evidence_ids: string[] }[];
  conflict: boolean; uncertainty: string[]; verification: string };
export type CV = { final_score: string | null; categories: Record<string, string | null>; scoring_run_id: number; screening_run_id: number;
  document_id: number; original_cv_rank: number | null; original_cohort: number[]; configuration_id: number; formula_version: string;
  written_justification: string; configuration: { category_weights: Record<string, string> }; breakdown: { counts: Record<string, number> } };
export type ReportData = { identification: { application_id: number; job_posting_id: number; candidate_name: string; job_title: string; requirement_version: string };
  score_summary?: { cv_score: string | null; interview_score: string | null; final_score: string | null; cv_weight?: number; interview_weight?: number; formula_version?: string; ready: boolean; reason: string; question_count: number; unanswered_count: number };
  simple_summary?: { strengths: { text: string; evidence_ids: string[] }[]; improvements: { text: string; evidence_ids: string[] }[] };
  evidence_summary?: Record<"strengths" | "weaknesses" | "evidence_gaps" | "verification", { text: string; summary_text?: string; evidence_ids: string[] }[]>;
  cv: CV | null; completeness: string; missing: string[]; flags: string[]; policy: string; evidence: Record<string, Evidence>; matrix: MatrixRow[];
  summary: { position: Fact[]; strengths: Fact[]; limitations: Fact[]; verification: Fact[]; basis: string };
  interviews: { id: number; date: string; analysis_id: number | null; analysis_version: number | null; rubric_version: string | null;
    limitations: string[]; pairs: { id: string; question: string; answer: string; state: string; evidence_ids: string[]; score?: { percentage: number };
    score_unavailable_reason?: string; interpretation?: { status: string; meaning: string; notes: { interpreted_as: string; reason: string; original: { quote: string } }[] };
    dimensions: Record<string, { label: string; finding: string; simple_reason?: string; evidence_ids: string[]; gaps: string[] }> }[] }[] };
export type Assessment = { id: number; version: number; application_id: number; job_posting_id: number; status: string; stage: string;
  completeness: string; review_status: string; stale: boolean; missing: string[]; error?: string; created_at: string; completed_at?: string;
  selection_policy: string; result: ReportData; comparison_cv_rank?: number; final_rank?: number;
  notes: { id: number; note: string; reviewed: boolean; author_id: number; created_at: string }[] };
export type ApplicationAssessments = { application_id: number; job_posting_id: number; identification: ReportData["identification"];
  missing: string[]; selection_policy: string; versions: { id: number; version: number; status: string; completeness: string }[];
  interviews: { id: number; date: string; status: string }[] };
export type Comparison = { id: number; created_at: string; stale_source_assessment_ids?: number[]; snapshot: { basis: string; policy: string; cv_order_compatible: boolean;
  combined_ranking_available: boolean; incompatibilities: string[]; interview_incompatibilities: string[]; assessments: Assessment[];
  selected_cohort_application_ids: number[]; cohort_policy: string } };
export type Artifact = { id: number; status: string; format: "html" | "pdf"; error?: string; sha256?: string };
export type FinalRanking = { id: number | null; status: string; stage: string; policy: string; stale: boolean; error?: string;
  incompatibilities: string[]; candidates: { application_id: number; candidate_name: string; cv_score: string | null;
  interview_score: string | null; final_score: string | null; final_rank: number | null; assessment_id: number | null; reason: string }[] };
export const assessmentApi = {
  ranking: (job: number) => apiRequest<FinalRanking>(`/assessments/jobs/${job}/ranking`),
  calculate: (job: number) => apiRequest<FinalRanking>(`/assessments/jobs/${job}/ranking`, { method: "POST", body: JSON.stringify({ confirmed: true }) }),
  list: (job: number) => apiRequest<ApplicationAssessments[]>(`/assessments/applications?job_posting_id=${job}`),
  application: (id: number) => apiRequest<ApplicationAssessments>(`/assessments/applications/${id}`),
  read: (id: number) => apiRequest<Assessment>(`/assessments/runs/${id}`),
  generate: (id: number, newVersion: boolean, interviews?: number[]) => apiRequest<{ id: number }>(`/assessments/applications/${id}`, {
    method: "POST", body: JSON.stringify({ new_version: newVersion, interview_ids: interviews ?? null }) }),
  review: (id: number, note: string, reviewed: boolean) => apiRequest<Assessment>(`/assessments/runs/${id}/reviews`, {
    method: "POST", body: JSON.stringify({ note, reviewed }) }),
  compare: (ids: number[]) => apiRequest<Comparison>("/assessments/comparisons", { method: "POST", body: JSON.stringify({ assessment_ids: ids }) }),
  comparison: (id: number) => apiRequest<Comparison>(`/assessments/comparisons/${id}`),
  export: (id: number, format: "html" | "pdf", comparison = false) => apiRequest<Artifact>(`/assessments/${comparison ? "comparisons" : "runs"}/${id}/exports`, {
    method: "POST", body: JSON.stringify({ format, retry: true }) }),
  artifact: (id: number) => apiRequest<Artifact>(`/assessments/exports/${id}`),
  blob: async (id: number) => {
    const response = await fetch(`${API_URL}/assessments/exports/${id}/download`, {
      headers: { Authorization: `Bearer ${sessionStorage.getItem(TOKEN_KEY) || ""}` } });
    if (!response.ok) throw new ApiError("The private report could not be downloaded. Refresh your login and retry.", response.status);
    return response.blob();
  },
};
