import { apiRequest } from "../../api/apiClient";

export type Citation = { interview_id: number; segment_id: string; session_id: string; revision: string; quote: string;
  char_start: number; char_end: number; speaker: string; start_at: string; end_at: string; start_offset_ms: number; end_offset_ms: number };
export type Segment = { id: string; text: string; speaker: string; start_offset_ms: number; end_offset_ms: number; hash: string };
export type Dimension = { label: string; justification: string; citations: Citation[]; references: { reference_id: string; quote: string; version: string; title: string }[];
  evidence_gaps: string[]; flags: string[]; support_status?: string };
export type Mapping = { requirement_id: string; requirement_version: string; pair_id: string; status: string; explanation: string; citations: Citation[]; flags: string[] };
export type Suggestion = { id: string; question: string; reason: string; requirement_ids: string[]; citations: Citation[];
  expected_clarification: string; priority: string; priority_reason: string };
export type PairEdit = { id: string; question_ids: string[]; answer_ids: string[]; context_ids: string[]; subparts: string[]; excluded: boolean; unanswered: boolean };
export type AnswerScore = { percentage: number; earned: number; possible: number; rubric_version: string;
  breakdown: Record<"relevance" | "accuracy" | "completeness" | "quality", { value: number; weight: number; status: "met" | "partially_met" | "unmet"; reason: string }> };
export type Pair = PairEdit & { state: string; flags: string[]; pairing_confidence: string; pairing_reasons: string[];
  score?: AnswerScore;
  score_unavailable_reason?: string;
  analysis_error?: string; assessment?: Record<"relevance" | "accuracy" | "completeness" | "quality", Dimension> & { expected_elements: string[]; expected_elements_basis: string;
    interpretation?: { status: string; meaning: string; support_status?: string; notes: { original: Citation; interpreted_as: string; reason: string; context: Citation[] }[] } };
  mappings?: Mapping[]; suggestions?: Suggestion[] };
export type InterviewSummaryFinding = { id: string; text: string; summary_text?: string; rule: string; pair_id: string | null; citations: Citation[];
  references: Dimension["references"]; source: { kind?: string; requirement_id?: string; version?: string; state?: string } };
export type Reference = { id: string; title: string; kind: "answer_guide" | "technical_reference"; content: string; requirement_ids: string[]; version?: string };
export type AnalysisRun = { id: number; version: number; status: string; stage: string; stale: boolean; error?: string; created_at: string;
  snapshot: { segments: Segment[]; requirements: { requirements: { key: string; name: string }[] }; references: Reference[]; requirement_version: string };
  result: { pairs?: Pair[]; coverage?: { requirement_id: string; name: string; statuses: string[]; evidence: Mapping[]; coverage_status?: string; question_pair_ids?: string[] }[]; gaps?: string[];
    evidence_summary?: Record<"strengths" | "weaknesses" | "evidence_gaps" | "verification", InterviewSummaryFinding[]>;
    unpaired?: {segment_id: string; kind: string}[]; reconciled?: boolean };
  reviews: { id: number; kind: string; target_id: string; payload: { note?: string; segment_ids?: string[] }; created_at: string }[] };
export type AnalysisState = { run: AnalysisRun | null; automatic: boolean; reference_revision: number; references: Reference[];
  versions: { id: number; version: number; status: string; created_at: string }[] };
const base = (id: number) => `/interview-rooms/${id}/analysis`;
export const analysisApi = {
  read: (id: number, runId?: number) => apiRequest<AnalysisState>(base(id) + (runId ? `?run_id=${runId}` : "")),
  start: (id: number, automatic: boolean, finalizeLast = false, reanalyze = false) => apiRequest(base(id), {
    method: "POST", body: JSON.stringify({ automatic, finalize_last: finalizeLast, reanalyze }) }),
};
