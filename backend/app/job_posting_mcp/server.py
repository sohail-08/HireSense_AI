from functools import lru_cache
from typing import Any

import httpx
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DiscordBotSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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


class DiscordEmbedField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=256)
    value: str = Field(min_length=1, max_length=1024)
    inline: bool = False


class DiscordPublishOutcome(BaseModel):
    ok: bool
    message_id: str | None = None
    channel_id: str | None = None
    guild_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    delivery_uncertain: bool = False


class DiscordBotPublisher:
    def __init__(
        self,
        settings: DiscordBotSettings,
        *,
        client: httpx.AsyncClient | None = None,
    ):
        self.settings = settings
        self.client = client

    def configured(self) -> bool:
        return bool(
            self.settings.discord_bot_token
            and self.settings.discord_channel_id
        )

    async def publish(
        self,
        *,
        content: str,
        title: str,
        description: str,
        fields: list[DiscordEmbedField],
    ) -> DiscordPublishOutcome:
        if not self.configured():
            return DiscordPublishOutcome(
                ok=False,
                error_code="discord_bot_not_configured",
                error_message=(
                    "Discord bot publishing is not configured. Set "
                    "DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID on the MCP server."
                ),
            )

        token = self.settings.discord_bot_token
        channel_id = self.settings.discord_channel_id
        assert token is not None and channel_id is not None
        payload: dict[str, Any] = {
            "content": content,
            "embeds": [
                {
                    "title": title,
                    "description": description,
                    "fields": [field.model_dump() for field in fields],
                }
            ],
            "allowed_mentions": {"parse": []},
        }
        url = (
            self.settings.discord_api_base_url.rstrip("/")
            + f"/channels/{channel_id}/messages"
        )
        owned_client = self.client is None
        client = self.client or httpx.AsyncClient(
            timeout=self.settings.discord_bot_timeout_seconds
        )
        try:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bot {token.get_secret_value()}",
                    "Content-Type": "application/json",
                    "User-Agent": "HireSense-JobPosting-MCP/1.0",
                },
                json=payload,
            )
        except httpx.RequestError:
            return DiscordPublishOutcome(
                ok=False,
                error_code="discord_delivery_uncertain",
                error_message=(
                    "Discord delivery could not be confirmed. Check the configured "
                    "channel before preparing another publication."
                ),
                delivery_uncertain=True,
            )
        finally:
            if owned_client:
                await client.aclose()

        if response.status_code in {401, 403}:
            return DiscordPublishOutcome(
                ok=False,
                error_code="discord_bot_unauthorized",
                error_message=(
                    "Discord rejected the bot credentials or the bot lacks "
                    "permission to send messages in the configured channel."
                ),
            )
        if response.status_code == 404:
            return DiscordPublishOutcome(
                ok=False,
                error_code="discord_channel_not_found",
                error_message=(
                    "The configured Discord channel was not found or is not "
                    "accessible to the bot."
                ),
            )
        if response.status_code == 429:
            return DiscordPublishOutcome(
                ok=False,
                error_code="discord_rate_limited",
                error_message="Discord is rate limiting the job-posting bot. Try again later.",
            )
        if response.status_code >= 500:
            return DiscordPublishOutcome(
                ok=False,
                error_code="discord_unavailable",
                error_message="Discord is temporarily unavailable. Try again later.",
            )
        if not 200 <= response.status_code < 300:
            return DiscordPublishOutcome(
                ok=False,
                error_code="discord_rejected_message",
                error_message="Discord rejected the reviewed job post.",
            )

        try:
            message = response.json()
            return DiscordPublishOutcome(
                ok=True,
                message_id=str(message["id"]),
                channel_id=str(message.get("channel_id") or channel_id),
                guild_id=(
                    str(message["guild_id"])
                    if message.get("guild_id") is not None
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError):
            return DiscordPublishOutcome(
                ok=False,
                error_code="discord_confirmation_invalid",
                error_message=(
                    "Discord may have accepted the post, but its delivery "
                    "confirmation was invalid."
                ),
                delivery_uncertain=True,
            )


mcp = MCPServer(
    "hiresense-discord-job-posting",
    instructions=(
        "Publishes an already-reviewed HireSense job post to one configured "
        "Discord channel. It cannot select another channel or perform other "
        "Discord operations."
    ),
)


@mcp.tool()
def get_discord_posting_status() -> dict[str, bool]:
    """Report whether the fixed Discord bot destination is configured."""
    return {"configured": DiscordBotPublisher(get_server_settings()).configured()}


@mcp.tool()
async def publish_job_post(
    content: str,
    title: str,
    description: str,
    fields: list[DiscordEmbedField] | None = None,
) -> dict[str, Any]:
    """Publish one reviewed job post to the fixed Discord channel."""
    outcome = await DiscordBotPublisher(get_server_settings()).publish(
        content=content,
        title=title,
        description=description,
        fields=fields or [],
    )
    return outcome.model_dump(mode="json")


def main() -> None:
    security = TransportSecuritySettings(
        allowed_hosts=[
            "job-posting-mcp",
            "job-posting-mcp:*",
            "localhost",
            "localhost:*",
            "127.0.0.1",
            "127.0.0.1:*",
        ],
        allowed_origins=[],
    )
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=8001,
        json_response=True,
        stateless_http=True,
        transport_security=security,
    )


if __name__ == "__main__":
    main()
