import asyncio
from dataclasses import dataclass
from typing import Any

from mcp import Client

from app.mcp_config import resolve_mcp_server


class DiscordPublishError(RuntimeError):
    def __init__(self, code: str, safe_message: str):
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


class DiscordConfigurationError(DiscordPublishError):
    pass


class DiscordDeliveryUncertainError(DiscordPublishError):
    pass


@dataclass(frozen=True)
class DiscordPublishResult:
    message_id: str
    channel_id: str
    guild_id: str | None


class DiscordMCPPublisher:
    def __init__(
        self,
        *,
        mcp_url: str | None = None,
        timeout_seconds: float | None = None,
    ):
        if mcp_url is None or timeout_seconds is None:
            connection = resolve_mcp_server("job_posting")
            if mcp_url is None:
                mcp_url = connection.url
            if timeout_seconds is None:
                timeout_seconds = connection.timeout_seconds
        self.mcp_url = mcp_url
        self.timeout_seconds = timeout_seconds

    def is_configured(self) -> bool:
        try:
            result = self._call_tool("get_discord_posting_status", {})
            return result.get("configured") is True
        except DiscordPublishError:
            return False

    def publish(self, payload: dict[str, Any]) -> DiscordPublishResult:
        try:
            embed = payload["embeds"][0]
            arguments = {
                "content": payload["content"],
                "title": embed["title"],
                "description": embed["description"],
                "fields": embed.get("fields", []),
            }
        except (IndexError, KeyError, TypeError) as exc:
            raise DiscordPublishError(
                "discord_payload_invalid",
                "The reviewed Discord job post is invalid.",
            ) from exc

        result = self._call_tool("publish_job_post", arguments)
        if not result.get("ok"):
            error_type = (
                DiscordDeliveryUncertainError
                if result.get("delivery_uncertain")
                else DiscordConfigurationError
                if result.get("error_code") == "discord_bot_not_configured"
                else DiscordPublishError
            )
            raise error_type(
                str(result.get("error_code") or "discord_mcp_publish_failed"),
                str(
                    result.get("error_message")
                    or "The Discord MCP server could not publish the job post."
                ),
            )
        try:
            return DiscordPublishResult(
                message_id=str(result["message_id"]),
                channel_id=str(result["channel_id"]),
                guild_id=(
                    str(result["guild_id"])
                    if result.get("guild_id") is not None
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise DiscordDeliveryUncertainError(
                "discord_mcp_confirmation_invalid",
                "Discord may have accepted the post, but the MCP confirmation was invalid.",
            ) from exc

    def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            return asyncio.run(
                asyncio.wait_for(
                    self._call_tool_async(name, arguments),
                    timeout=self.timeout_seconds,
                )
            )
        except TimeoutError as exc:
            raise DiscordDeliveryUncertainError(
                "discord_mcp_timeout",
                "The Discord MCP server timed out; delivery could not be confirmed.",
            ) from exc
        except DiscordPublishError:
            raise
        except Exception as exc:
            raise DiscordPublishError(
                "discord_mcp_unavailable",
                "The Discord job-posting MCP server is unavailable.",
            ) from exc

    async def _call_tool_async(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        async with Client(self.mcp_url) as client:
            response = await client.call_tool(name, arguments)
        if response.is_error:
            raise DiscordPublishError(
                "discord_mcp_tool_error",
                "The Discord MCP server rejected the job-posting tool call.",
            )
        structured = response.structured_content
        if not isinstance(structured, dict):
            raise DiscordPublishError(
                "discord_mcp_response_invalid",
                "The Discord MCP server returned an invalid response.",
            )
        return structured
