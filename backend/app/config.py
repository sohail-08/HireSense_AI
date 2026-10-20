from datetime import date
from functools import lru_cache
from typing import Literal

from pydantic import EmailStr, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.environment import ROOT_ENV_FILE


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_ENV_FILE, extra="ignore")

    database_url: str
    jwt_secret_key: SecretStr
    access_token_expire_minutes: int = Field(default=60, ge=1, le=1440)

    interviewer_name: str = "HireSense Interviewer"
    interviewer_email: EmailStr
    interviewer_password: SecretStr

    frontend_url: str = "http://localhost:5173"
    mcp_config_file: str = str(ROOT_ENV_FILE.with_name("mcp.json"))
    mcp_profile: Literal["local", "docker"] = "local"
    interview_company_name: str = "BJIT"
    smtp_host: str = ""
    smtp_port: int = Field(default=1025, ge=1, le=65535)
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from_email: str = "interviews@hiresense.test"
    smtp_from_name: str = "HireSense"
    smtp_use_tls: bool = False
    smtp_timeout_seconds: float = Field(default=15, ge=1, le=120)
    interview_reply_to_email: str = "interviews@hiresense.test"
    livekit_cloud_url: str = ""
    livekit_cloud_api_key: str = ""
    livekit_cloud_api_secret: SecretStr = SecretStr("")
    livekit_token_ttl_seconds: int = Field(default=120, ge=30, le=300)
    livekit_api_timeout_seconds: int = Field(default=5, ge=1, le=30)
    interview_join_base_url: str = "http://localhost:5173"
    interview_link_secret: SecretStr | None = None
    interview_link_max_days: int = Field(default=30, ge=1, le=365)
    candidate_session_minutes: int = Field(default=120, ge=5, le=480)
    candidate_cookie_secure: bool = True
    candidate_public_rate_limit: int = Field(default=20, ge=1, le=1000)
    candidate_waiting_heartbeat_seconds: int = Field(default=45, ge=10, le=300)

    transcription_enabled: bool = False
    transcription_worker_secret: SecretStr = SecretStr("")
    transcription_agent_name: str = "hiresense-transcriber"
    transcription_interim_results: bool = True
    transcription_retention_days: int = Field(default=30, ge=1, le=3650)
    transcription_start_timeout_seconds: int = Field(default=45, ge=10, le=180)
    transcription_lease_seconds: int = Field(default=20, ge=10, le=120)
    deepgram_model: Literal["nova-3"] = "nova-3"
    deepgram_language: str = Field(default="en-US", pattern=r"^en(?:-[A-Za-z]{2})?$")
    deepgram_endpointing_ms: int = Field(default=300, ge=10, le=3000)
    deepgram_utterance_end_ms: int = Field(default=1000, ge=1000, le=5000)

    storage_root: str = "storage"
    cv_max_file_size_mb: int = Field(default=10, ge=1, le=100)
    cv_max_pages: int = Field(default=40, ge=1, le=500)
    cv_max_characters: int = Field(default=150_000, ge=1_000, le=2_000_000)
    cv_min_extract_characters: int = Field(default=80, ge=1, le=10_000)
    screening_batch_max_applications: int = Field(default=50, ge=1, le=500)
    screening_evidence_top_k: int = Field(default=6, ge=2, le=12)
    screening_engine_revision: str = "semantic-evidence-v1"
    screening_request_interval_seconds: float = Field(default=4.1, ge=0, le=10)
    knowledge_pdf_max_file_size_mb: int = Field(default=15, ge=1, le=100)
    knowledge_pdf_max_pages: int = Field(default=100, ge=1, le=500)

    google_service_account_file: str = "secrets/google-service-account.json"
    google_form_url: str | None = None
    google_forms_spreadsheet_id: str | None = None
    google_forms_sheet_name: str = "Form Responses 1"
    google_forms_timestamp_column: str = "Timestamp"
    google_forms_name_column: str = "Name"
    google_forms_email_column: str = "Email Address"
    google_forms_phone_column: str = "Phone"
    google_forms_linkedin_column: str = "LinkedIn"
    google_forms_portfolio_column: str = "Portfolio"
    google_forms_location_column: str = "Location"
    google_forms_cv_column: str = "Upload CV"
    google_forms_job_column: str = "Job Posting"

    ollama_base_url: str = "http://localhost:11434"
    ollama_embedding_model: str = "nomic-embed-text:latest"
    ollama_timeout_seconds: float = Field(default=60, ge=1, le=600)

    gemini_api_key: SecretStr | None = None
    gemini_api_base_url: str = (
        "https://generativelanguage.googleapis.com/v1beta"
    )
    gemini_chat_model: str = "gemini-3.5-flash-lite"
    gemini_timeout_seconds: float = Field(default=60, ge=1, le=300)

    discord_default_heading: str = Field(
        default="BJIT is Hiring!",
        min_length=1,
        max_length=2000,
    )
    job_post_default_application_url: str | None = None
    job_post_default_contact_email: EmailStr | None = None
    job_post_default_location: str | None = Field(
        default=None,
        max_length=500,
    )
    job_post_default_application_deadline: date | None = None
    job_post_default_instructions: str | None = Field(
        default=None,
        max_length=1024,
    )

    @field_validator(
        "job_post_default_application_url",
        "job_post_default_contact_email",
        "job_post_default_location",
        "job_post_default_application_deadline",
        "job_post_default_instructions",
        "google_form_url",
        "google_forms_spreadsheet_id",
        mode="before",
    )
    @classmethod
    def empty_optional_value(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("google_forms_job_column", mode="before")
    @classmethod
    def default_google_forms_job_column(cls, value):
        if not isinstance(value, str) or not value.strip():
            return "Job Posting"
        return value.strip()

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError(
                "JWT_SECRET_KEY must contain at least 32 characters"
            )
        return value

    @field_validator("interview_link_secret")
    @classmethod
    def validate_interview_link_secret(cls, value):
        if value is not None and len(value.get_secret_value()) < 32:
            raise ValueError("INTERVIEW_LINK_SECRET must contain at least 32 characters")
        return value

    @field_validator("interviewer_password")
    @classmethod
    def validate_password(cls, value: SecretStr) -> SecretStr:
        if not 10 <= len(value.get_secret_value()) <= 128:
            raise ValueError(
                "INTERVIEWER_PASSWORD must be 10–128 characters"
            )
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
