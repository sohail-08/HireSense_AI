// Candidate is retained only to safely reject historical web-account sessions.
export type UserRole = "interviewer" | "candidate";

export interface User {
  id: number;
  name: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface RequirementItem {
  name: string;
  details: string | null;
}

export interface RequirementProfileDraft {
  title: string | null;
  summary: string | null;
  required_skills: RequirementItem[];
  preferred_skills: RequirementItem[];
  qualifications: RequirementItem[];
  min_years_experience: number | null;
  selection_criteria: RequirementItem[];
}

export type KnowledgeSourceType = "previous_job_description";

export interface KnowledgeDocumentResponse {
  id: number;
  title: string;
  source_type: KnowledgeSourceType;
  source_uri: string | null;
  content_hash: string;
  metadata_json: Record<string, unknown>;
  created_by_user_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface JobDescriptionDraft {
  title: string;
  summary: string;
  responsibilities: string[];
  required_skills: RequirementItem[];
  preferred_skills: RequirementItem[];
  qualifications: RequirementItem[];
  experience_requirement: string;
  selection_criteria: string[];
}

export interface JobDescriptionEvidence {
  document_id: number;
  document_title: string;
  source_type: KnowledgeSourceType;
  chunk_id: number;
  chunk_index: number;
  score: number;
  source_uri: string | null;
}

export type JobDescriptionStatus =
  | "draft"
  | "approved"
  | "archived";

export interface JobDescriptionResponse {
  id: number;
  requirement_profile_id: number;
  title: string;
  content: string;
  structured_content: JobDescriptionDraft;
  source_references: JobDescriptionEvidence[];
  version: number;
  status: JobDescriptionStatus;
  created_by_user_id: number | null;
  created_at: string;
  updated_at: string;
}

export type JobPostingStatus =
  | "draft"
  | "publishing"
  | "published"
  | "closed"
  | "failed"
  | "uncertain";

export interface DiscordPostDefaults {
  job_description_content?: string | null;
  heading: string;
  application_url: string | null;
  contact_email: string | null;
  location: string | null;
  application_deadline: string | null;
  additional_instructions: string | null;
  mcp_configured: boolean;
}

export interface DiscordJobPost {
  id: number;
  job_description_id: number;
  platform: "discord";
  heading: string | null;
  application_url: string | null;
  contact_email: string | null;
  location: string | null;
  application_deadline: string | null;
  additional_instructions: string | null;
  reviewed_content: string | null;
  discord_payload: Record<string, unknown> | null;
  job_description_version: number | null;
  status: JobPostingStatus;
  external_post_id: string | null;
  external_server_id: string | null;
  external_channel_id: string | null;
  external_url: string | null;
  error_code: string | null;
  error_message: string | null;
  attempt_started_at: string | null;
  published_at: string | null;
  created_at: string;
  updated_at: string;
}

export type SupervisorPhase =
  | "job_details"
  | "requirements"
  | "requirement_confirmation"
  | "requirement_confirmed"
  | "job_description_draft"
  | "job_description_approved"
  | "posting_details"
  | "posting_approval"
  | "published"
  | "error"
  | "interview_selection" | "interview_schedule" | "interview_approval" | "interview_sent" | "interview_reschedule";

export interface SupervisorMessage {
  role: "user" | "assistant";
  content: string;
  outcome: "info" | "success" | "failure";
}

export interface SupervisorRequirementState {
  profile: RequirementProfileDraft;
  missing_fields: string[];
  knowledge_status: "not_searched" | "found" | "empty" | "error";
  proposal_ready: boolean;
  source_references: JobDescriptionEvidence[];
}

export interface SupervisorChatResponse {
  session_id: string;
  phase: SupervisorPhase;
  route: string;
  assistant_message: string;
  outcome: "info" | "success" | "failure";
  messages: SupervisorMessage[];
  requirement_profile_id: number | null;
  requirement_state: SupervisorRequirementState;
  job_description: JobDescriptionResponse | null;
  job_posting: DiscordJobPost | null;
  refresh_required: boolean;
  sync_result: GoogleFormsSyncResult | null;
  screening_batch: ScreeningBatch | null;
  interview_batch_id?: number | null;
  interview_selection?: { job_posting_id: number; application_ids: number[] } | null;
  assessment_links?: { label: string; path: string }[];
}

export type ApplicationSource = "direct_upload" | "google_form" | "import";
export type ApplicationStatus =
  | "received"
  | "screening"
  | "reviewed"
  | "shortlisted"
  | "rejected"
  | "withdrawn";

export interface CandidateProfile {
  id: number;
  name: string | null;
  email: string | null;
  phone: string | null;
  linkedin_url: string | null;
  portfolio_url: string | null;
  location: string | null;
  created_at: string;
  updated_at: string;
}

export interface CandidateCVDocument {
  id: number;
  application_id: number | null;
  candidate_id: number | null;
  original_filename: string;
  storage_path: string;
  mime_type: string;
  file_size_bytes: number;
  sha256: string;
  source: ApplicationSource;
  status:
    | "received"
    | "validated"
    | "processing"
    | "processed"
    | "rejected"
    | "failed";
  extracted_text: string | null;
  extraction_data: Record<string, unknown> | null;
  extraction_warnings: string[];
  error_message: string | null;
  processed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CandidateApplicationSummary {
  id: number;
  job_posting_id: number;
  job_title: string;
  source: ApplicationSource;
  source_reference: string | null;
  status: ApplicationStatus;
  submitted_at: string;
  response_data: Record<string, unknown>;
  candidate: CandidateProfile;
  cv_documents: CandidateCVDocument[];
}

export interface CandidateJobPostingOption {
  id: number;
  job_description_id: number;
  title: string;
  status: JobPostingStatus;
  published_at: string | null;
}

export interface GoogleFormsConfiguration {
  configured: boolean;
  form_url: string | null;
  sheet_name: string;
  job_column: string;
  missing_settings: string[];
}

export interface GoogleFormsSyncResult {
  imported_applications: number;
  reassigned_applications: number;
  skipped_existing: number;
  skipped_deleted: number;
  unmatched_responses: number;
  downloaded_cvs: number;
  issues: { row_number: number; message: string }[];
}

export type ScreeningRunStatus =
  | "pending"
  | "queued"
  | "processing"
  | "completed"
  | "review_required"
  | "failed";

export interface ScreeningJobOption {
  id: number;
  title: string;
  posting_status: JobPostingStatus;
  application_count: number;
  pending_count: number;
}

export interface ScreeningApplicationItem {
  id: number;
  candidate_name: string;
  candidate_email: string | null;
  submitted_at: string;
  cv_filename: string | null;
  screening_status: ScreeningRunStatus;
  screening_run_id: number | null;
  requirement_coverage: number | null;
  error_message: string | null;
}

export interface RankingItem {
  application_id: number;
  screening_run_id: number;
  candidate_name: string;
  candidate_email: string | null;
  rank: number | null;
  disposition: "ranked" | "review";
  requirement_coverage: number | null;
  met_count: number;
  partially_met_count: number;
  unmet_count: number;
  uncertain_count: number;
  suitability_summary: string | null;
  strengths: { requirement_key: string; text: string }[];
  gaps: { requirement_key: string; text: string }[];
  points_to_verify: { requirement_key: string; text: string }[];
}

export interface ScreeningDashboard {
  job_posting_id: number;
  job_title: string;
  requirement_profile_id: number;
  applications: ScreeningApplicationItem[];
  ranking: {
    snapshot_id: number | null;
    created_at: string | null;
    calculation_version: string;
    ranked: RankingItem[];
    review: RankingItem[];
  };
}

export interface ScreeningBatch {
  id: number;
  job_posting_id: number;
  status:
    | "queued"
    | "processing"
    | "completed"
    | "completed_with_errors"
    | "failed";
  application_ids: number[];
  total_applications: number;
  processed_applications: number;
  successful_applications: number;
  review_applications: number;
  failed_applications: number;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  items: {
    id: number;
    application_id: number;
    screening_run_id: number | null;
    status: Exclude<ScreeningRunStatus, "pending">;
    error_message: string | null;
  }[];
}
