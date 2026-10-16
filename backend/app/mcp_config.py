"""Validated, secret-free MCP client registry shared by application integrations."""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.config import Settings, get_settings
from app.environment import ROOT_ENV_FILE


class MCPConfigurationError(RuntimeError):
    pass


class MCPServerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["http"]
    url: str
    local_url: str | None = Field(default=None, alias="localUrl")
    timeout_seconds: float = Field(alias="timeoutSeconds", ge=1, le=600, strict=True, allow_inf_nan=False)

    @field_validator("url", "local_url")
    @classmethod
    def valid_url(cls, value):
        if value is None:
            return value
        parsed = urlsplit(value)
        # No secrets in a tracked file: authentication is injected at runtime.
        if (value != value.strip() or any(char.isspace() for char in value)
            or parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or not parsed.path.startswith("/")):
            raise ValueError("Invalid MCP HTTP endpoint")
        _ = parsed.port  # Reject malformed ports, not just malformed schemes.
        return value


class MCPRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    servers: dict[str, MCPServerEntry] = Field(alias="mcpServers", min_length=1, max_length=32)

    @field_validator("servers")
    @classmethod
    def required_servers(cls, entries):
        if not {"job_posting", "interview_scheduling"}.issubset(entries):
            raise ValueError("Both application MCP servers must be configured")
        return entries


@dataclass(frozen=True)
class MCPConnection:
    name: str
    url: str
    timeout_seconds: float
    transport: str = "http"


def _unique_keys(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate registry key")
        result[name] = value
    return result


def resolve_mcp_server(name: str, *, settings: Settings | None = None) -> MCPConnection:
    settings = settings or get_settings()
    path = Path(settings.mcp_config_file).expanduser()
    if not path.is_absolute():
        path = ROOT_ENV_FILE.parent / path
    try:
        if path.stat().st_size > 65536:
            raise ValueError("Registry too large")
        registry = MCPRegistry.model_validate(json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys))
        entry = registry.servers[name]
    except (OSError, ValueError, KeyError):
        # Do not expose file contents, credentials, or Pydantic input values.
        raise MCPConfigurationError(
            "MCP configuration is unavailable or invalid. Check mcp.json, MCP_CONFIG_FILE and MCP_PROFILE."
        ) from None
    url = (entry.local_url or entry.url) if settings.mcp_profile == "local" else entry.url
    return MCPConnection(name=name, url=url, timeout_seconds=entry.timeout_seconds)
