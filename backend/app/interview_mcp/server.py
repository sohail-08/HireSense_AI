from contextvars import ContextVar
from typing import Any
import httpx
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.environment import ROOT_ENV_FILE
from app.schemas.interview import SelectionRequest, PrepareInvites, ConfirmInvites, RescheduleRequest


class MCPSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_ENV_FILE, extra="ignore")
    interview_backend_url: str = "http://localhost:8000"


authorization = ContextVar("interview_mcp_authorization", default="")


async def delegate_identity(ctx, call_next):
    headers = getattr(ctx.request, "headers", {}) if ctx.request else {}
    token = authorization.set(headers.get("authorization", ""))
    try:
        return await call_next(ctx)
    finally:
        authorization.reset(token)


mcp = MCPServer("HireSense interview scheduling", middleware=[delegate_identity], log_level="WARNING")


async def forward(method, path, data=None):
    auth = authorization.get()
    if not auth.startswith("Bearer "):
        raise ValueError("Authenticated interviewer token required")
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.request(method, MCPSettings().interview_backend_url.rstrip("/") + "/api/interviews" + path,
            headers={"Authorization": auth}, json=data)
    result = response.json()
    if response.status_code >= 400:
        detail = result.get("detail")
        raise ValueError(detail if isinstance(detail, str) else "Scheduling request rejected by the authenticated backend")
    return result


READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True)


@mcp.tool(annotations=READ)
async def preview_candidate_selection(data: SelectionRequest) -> dict[str, Any]:
    """Read-only top-N, exact score-threshold or manual selection from a persisted ranking."""
    return await forward("POST", "/selection/preview", data.model_dump(mode="json"))


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False))
async def prepare_interview_invites(data: PrepareInvites) -> dict[str, Any]:
    """Persist a draft and return exact recipients, slots and email preview. Never sends mail."""
    return await forward("POST", "/invitations/prepare", data.model_dump(mode="json"))


@mcp.tool(annotations=WRITE)
async def confirm_and_send_interview_invites(batch_id: int, data: ConfirmInvites) -> dict[str, Any]:
    """Confirm a fresh draft and queue invitations using an explicit confirmation and idempotency key."""
    return await forward("POST", f"/batches/{batch_id}/confirm", data.model_dump(mode="json"))


@mcp.tool(annotations=READ)
async def preview_interview_reschedule(data: RescheduleRequest) -> dict[str, Any]:
    """Read-only version-bound preview of new slots and update emails; no schedule mutation or sending."""
    return await forward("POST", "/reschedule/preview", data.model_dump(mode="json"))


@mcp.tool(annotations=WRITE)
async def confirm_interview_reschedule(data: ConfirmInvites) -> dict[str, Any]:
    """Confirm a fresh rescheduling preview, preserve history, increment calendar sequence and queue updates."""
    return await forward("POST", "/reschedule/confirm", data.model_dump(mode="json"))


@mcp.tool(annotations=READ)
async def list_interview_schedules() -> list[dict[str, Any]]:
    """List only the authenticated interviewer's schedules for safe database identifier resolution."""
    return await forward("GET", "/schedules")


@mcp.tool(annotations=READ)
async def get_interview_invitation_status(batch_id: int) -> dict[str, Any]:
    """Read per-recipient sent, failed, uncertain and pending delivery status."""
    return await forward("GET", f"/batches/{batch_id}")


def main():
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8002, stateless_http=True, json_response=True,
        transport_security=TransportSecuritySettings(allowed_hosts=["interview-mcp", "interview-mcp:*", "localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*"], allowed_origins=[]))


if __name__ == "__main__":
    main()
