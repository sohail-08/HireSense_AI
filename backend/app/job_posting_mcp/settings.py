from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.environment import ROOT_ENV_FILE


class DiscordBotSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_ENV_FILE, extra="ignore")

    discord_bot_token: SecretStr | None = None
    discord_channel_id: str | None = None
    discord_api_base_url: str = "https://discord.com/api/v10"
    discord_bot_timeout_seconds: float = Field(default=15, ge=1, le=60)

    @field_validator("discord_bot_token", "discord_channel_id", mode="before")
    @classmethod
    def empty_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("discord_channel_id")
    @classmethod
    def validate_channel_id(cls, value: str | None) -> str | None:
        if value is not None and (not value.isdigit() or not 15 <= len(value) <= 25):
            raise ValueError("DISCORD_CHANNEL_ID must be a Discord numeric channel ID")
        return value


@lru_cache
def get_server_settings() -> DiscordBotSettings:
    return DiscordBotSettings()
