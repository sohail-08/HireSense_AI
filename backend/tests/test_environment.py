from pathlib import Path

import pytest

from app.config import Settings
from app.environment import ROOT_ENV_FILE
from app.job_posting_mcp.settings import DiscordBotSettings


def test_services_share_the_repository_root_environment_file():
    repository = Path(__file__).resolve().parents[2]
    assert ROOT_ENV_FILE == repository / ".env"
    assert ROOT_ENV_FILE.is_absolute()
    assert Settings.model_config["env_file"] == ROOT_ENV_FILE
    assert DiscordBotSettings.model_config["env_file"] == ROOT_ENV_FILE


@pytest.fixture
def root_env(tmp_path, monkeypatch):
    for name in {*Settings.model_fields, *DiscordBotSettings.model_fields}:
        monkeypatch.delenv(name.upper(), raising=False)
        monkeypatch.delenv(name, raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text(
        "DATABASE_URL=sqlite://\n"
        "JWT_SECRET_KEY=test-only-secret-key-at-least-32-characters\n"
        "INTERVIEWER_EMAIL=interviewer@example.com\n"
        "INTERVIEWER_PASSWORD=TestPassword123!\n"
        "GEMINI_API_KEY=test-root-api-key\n"
        "DISCORD_BOT_TOKEN=test-root-bot-token\n"
        "DISCORD_CHANNEL_ID=123456789012345678\n",
        encoding="utf-8",
    )
    for settings in (Settings, DiscordBotSettings):
        monkeypatch.setitem(settings.model_config, "env_file", env_file)

    # A stale working-directory .env must not override the shared root file.
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / ".env").write_text(
        "GEMINI_API_KEY=wrong-working-directory-key\n"
        "DISCORD_BOT_TOKEN=wrong-working-directory-token\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(backend)
    return env_file


def test_backend_and_mcp_load_shared_file_from_another_directory(root_env):
    backend = Settings()
    discord = DiscordBotSettings()
    assert backend.database_url == "sqlite://"
    assert backend.gemini_api_key.get_secret_value() == "test-root-api-key"
    assert discord.discord_bot_token.get_secret_value() == "test-root-bot-token"
    assert discord.discord_channel_id == "123456789012345678"


def test_process_environment_overrides_root_file(root_env, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///process-test.db")
    monkeypatch.setenv("GEMINI_API_KEY", "test-process-api-key")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-process-bot-token")
    assert Settings().database_url == "sqlite:///process-test.db"
    assert Settings().gemini_api_key.get_secret_value() == "test-process-api-key"
    assert DiscordBotSettings().discord_bot_token.get_secret_value() == "test-process-bot-token"
