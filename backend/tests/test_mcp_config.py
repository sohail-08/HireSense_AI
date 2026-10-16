import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.config import Settings
from app import mcp_config
from app.mcp_config import MCPConfigurationError, resolve_mcp_server
from app.integrations.discord_mcp import DiscordMCPPublisher
from app.integrations.interview_mcp import InterviewMCPClient


def registry():
    return {"mcpServers": {
        "job_posting": {"type": "http", "url": "http://job-posting-mcp:8001/mcp",
            "localUrl": "http://localhost:8001/mcp", "timeoutSeconds": 30},
        "interview_scheduling": {"type": "http", "url": "http://interview-mcp:8002/mcp",
            "localUrl": "http://localhost:8002/mcp", "timeoutSeconds": 120},
    }}


@pytest.fixture
def config(tmp_path, monkeypatch):
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps(registry()), encoding="utf-8")
    settings = Settings(_env_file=None, database_url="sqlite://",
        jwt_secret_key="test-only-mcp-config-secret-not-for-production",
        interviewer_email="test@example.com", interviewer_password="test-only-password",
        mcp_config_file=str(path), mcp_profile="local")
    monkeypatch.setattr(mcp_config, "get_settings", lambda: settings)
    return path, settings


def test_both_clients_use_one_registry_for_local_and_docker_profiles(config):
    _, settings = config
    assert DiscordMCPPublisher().mcp_url == "http://localhost:8001/mcp"
    assert InterviewMCPClient(1).url == "http://localhost:8002/mcp"
    assert DiscordMCPPublisher().timeout_seconds == 30
    assert InterviewMCPClient(1).timeout_seconds == 120
    settings.mcp_profile = "docker"
    assert DiscordMCPPublisher().mcp_url == "http://job-posting-mcp:8001/mcp"
    assert InterviewMCPClient(1).url == "http://interview-mcp:8002/mcp"


def test_edited_registry_is_used_and_old_environment_urls_are_not_fallbacks(config, monkeypatch):
    path, _ = config
    data = registry()
    data["mcpServers"]["job_posting"].update(localUrl="http://localhost:9001/mcp", timeoutSeconds=17)
    data["mcpServers"]["interview_scheduling"].update(localUrl="http://localhost:9002/mcp", timeoutSeconds=44)
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("JOB_POSTING_MCP_URL", "http://obsolete:1/mcp")
    monkeypatch.setenv("INTERVIEW_MCP_URL", "http://obsolete:2/mcp")
    assert DiscordMCPPublisher().mcp_url == "http://localhost:9001/mcp"
    assert DiscordMCPPublisher().timeout_seconds == 17
    assert InterviewMCPClient(1).url == "http://localhost:9002/mcp"
    assert InterviewMCPClient(1).timeout_seconds == 44
    path.unlink()
    with pytest.raises(MCPConfigurationError):
        DiscordMCPPublisher()


def test_relative_registry_path_is_repository_relative_not_cwd(config, tmp_path, monkeypatch):
    _, settings = config
    monkeypatch.setattr(mcp_config, "ROOT_ENV_FILE", tmp_path / ".env")
    settings.mcp_config_file = "mcp.json"
    nested = tmp_path / "backend"
    nested.mkdir()
    (nested / "mcp.json").write_text("not the registry", encoding="utf-8")
    monkeypatch.chdir(nested)
    assert resolve_mcp_server("job_posting").timeout_seconds == 30


@pytest.mark.parametrize("field,value", [
    ("url", "file:///private/secret"), ("url", "https://user:private-secret@example.com/mcp"),
    ("url", "https://example.com/mcp?token=private-secret"), ("url", "https://example.com/mcp#private-secret"),
    ("url", "http://localhost:bad-port/mcp"), ("url", "/relative/mcp"),
    ("type", "stdio"), ("headers", {"Authorization": "private-secret"}),
    ("timeoutSeconds", 0), ("timeoutSeconds", 601), ("timeoutSeconds", True),
    ("timeoutSeconds", "30"), ("timeoutSeconds", float("nan")),
])
def test_invalid_or_secret_bearing_entries_fail_without_echoing_values(config, field, value):
    path, _ = config
    data = registry()
    data["mcpServers"]["job_posting"][field] = value
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(MCPConfigurationError) as error:
        resolve_mcp_server("job_posting")
    assert "private-secret" not in str(error.value)


@pytest.mark.parametrize("content", ["not-json", "{}", '{"mcpServers":{},"mcpServers":{}}', "x" * 65537])
def test_missing_malformed_duplicate_or_oversized_registry_fails_closed(config, content):
    path, _ = config
    path.write_text(content, encoding="utf-8")
    with pytest.raises(MCPConfigurationError):
        resolve_mcp_server("interview_scheduling")


def test_missing_server_entry_and_unknown_server_name_are_rejected(config):
    path, _ = config
    with pytest.raises(MCPConfigurationError):
        resolve_mcp_server("invented_server")
    data = registry()
    del data["mcpServers"]["interview_scheduling"]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(MCPConfigurationError):
        resolve_mcp_server("job_posting")


def test_interview_auth_is_dynamic_and_registry_timeout_reaches_http_transport(config, monkeypatch):
    from app.integrations import interview_mcp as integration
    path, _ = config
    data = registry()
    data["mcpServers"]["interview_scheduling"]["timeoutSeconds"] = 44
    path.write_text(json.dumps(data), encoding="utf-8")
    seen = []

    class FakeHTTP:
        def __init__(self, **kwargs): seen.append(kwargs)
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass

    class FakeClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def call_tool(self, *args):
            return SimpleNamespace(is_error=False, structured_content={"result": {"ok": True}})

    monkeypatch.setattr(integration.httpx2, "AsyncClient", FakeHTTP)
    monkeypatch.setattr(integration, "Client", FakeClient)
    monkeypatch.setattr(integration, "streamable_http_client", lambda url, **kwargs: url)
    monkeypatch.setattr(integration, "create_access_token", lambda user_id: f"dynamic-test-token-{user_id}")
    for user_id in (10, 20):
        assert asyncio.run(InterviewMCPClient(user_id).call_async("list_interview_schedules", {})) == {"ok": True}
    assert [item["timeout"] for item in seen] == [44, 44]
    assert [item["headers"]["Authorization"] for item in seen] == ["Bearer dynamic-test-token-10", "Bearer dynamic-test-token-20"]


def test_explicit_test_connections_do_not_require_a_registry(config):
    path, _ = config
    path.unlink()
    assert DiscordMCPPublisher(mcp_url="http://localhost:9001/mcp", timeout_seconds=5).timeout_seconds == 5
    assert InterviewMCPClient(1, url="http://localhost:9002/mcp", timeout_seconds=6).timeout_seconds == 6


def test_invalid_registry_stops_startup_before_business_initialization(config, monkeypatch):
    from app import main
    path, _ = config
    path.write_text("invalid registry", encoding="utf-8")
    def unexpected_initialization():
        raise AssertionError("Business initialization must not run with invalid MCP configuration")
    monkeypatch.setattr(main, "ensure_storage_root", unexpected_initialization)
    with pytest.raises(MCPConfigurationError):
        asyncio.run(main.lifespan(main.app).__aenter__())
