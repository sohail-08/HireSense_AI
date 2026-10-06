from datetime import date
from functools import lru_cache

from pydantic import EmailStr, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    jwt_secret_key: SecretStr
    access_token_expire_minutes: int = Field(default=60, ge=1, le=1440)

    interviewer_name: str = "HireSense Interviewer"
    interviewer_email: EmailStr
    interviewer_password: SecretStr

    frontend_url: str = "http://localhost:5173"

    storage_root: str = "storage"
    cv_max_file_size_mb: int = Field(default=10, ge=1, le=100)

    ollama_base_url: str = "http://localhost:11434"
    ollama_embedding_model: str = "nomic-embed-text:latest"
    ollama_timeout_seconds: float = Field(default=60, ge=1, le=600)

    gemini_api_key: SecretStr | None = None
    gemini_api_base_url: str = (
        "https://generativelanguage.googleapis.com/v1beta"
    )
    gemini_chat_model: str = "gemini-3.5-flash-lite"
    gemini_timeout_seconds: float = Field(default=60, ge=1, le=300)

    discord_webhook_url: SecretStr | None = None
    discord_timeout_seconds: float = Field(default=15, ge=1, le=60)
    discord_rate_limit_max_wait_seconds: float = Field(
        default=5,
        ge=0,
        le=30,
    )
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
        "discord_webhook_url",
        "job_post_default_application_url",
        "job_post_default_contact_email",
        "job_post_default_location",
        "job_post_default_application_deadline",
        "job_post_default_instructions",
        mode="before",
    )
    @classmethod
    def empty_optional_value(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError(
                "JWT_SECRET_KEY must contain at least 32 characters"
            )
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
