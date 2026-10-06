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

export interface RegisterRequest extends LoginRequest {
  name: string;
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

export type RequirementChatStatus =
  | "active"
  | "awaiting_changes"
  | "awaiting_confirmation"
  | "confirmed"
  | "error";

export interface RequirementChatResponse {
  session_id: string;
  status: RequirementChatStatus;
  assistant_message: string;
  profile: RequirementProfileDraft;
  missing_fields: string[];
  requirement_profile_id: number | null;
  error: string | null;
  error_code: string | null;
  knowledge_status: "not_searched" | "found" | "empty" | "error";
  proposal_ready: boolean;
  source_references: JobDescriptionEvidence[];
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
  heading: string;
  application_url: string | null;
  contact_email: string | null;
  location: string | null;
  application_deadline: string | null;
  additional_instructions: string | null;
  webhook_configured: boolean;
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
