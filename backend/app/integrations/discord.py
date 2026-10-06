import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import get_settings


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


class DiscordWebhookPublisher:
    def __init__(
        self,
        *,
        webhook_url: str | None = None,
        client: httpx.Client | None = None,
        timeout_seconds: float | None = None,
        max_rate_limit_wait_seconds: float | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        settings = get_settings()
        configured_url = settings.discord_webhook_url
        self.webhook_url = webhook_url or (
            configured_url.get_secret_value() if configured_url else None
        )
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.discord_timeout_seconds
        )
        self.max_rate_limit_wait_seconds = (
            max_rate_limit_wait_seconds
            if max_rate_limit_wait_seconds is not None
            else settings.discord_rate_limit_max_wait_seconds
        )
        self.client = client
        self.sleeper = sleeper

    def publish(self, payload: dict[str, Any]) -> DiscordPublishResult:
        webhook_url = self._validated_webhook_url()
        owned_client = self.client is None
        client = self.client or httpx.Client(timeout=self.timeout_seconds)
        try:
            response = self._post_with_bounded_rate_limit(
                client,
                webhook_url,
                payload,
            )
        finally:
            if owned_client:
                client.close()

        if response.status_code in {401, 403, 404}:
            raise DiscordPublishError(
                "discord_webhook_invalid",
                "Discord rejected the configured webhook. Check whether it is valid and still exists.",
            )
        if response.status_code == 429:
            raise DiscordPublishError(
                "discord_rate_limited",
                "Discord is rate limiting this webhook. Create a new preview and try again later.",
            )
        if response.status_code >= 500:
            raise DiscordPublishError(
                "discord_unavailable",
                "Discord is temporarily unavailable. Create a new preview and try again later.",
            )
        if not 200 <= response.status_code < 300:
            raise DiscordPublishError(
                "discord_rejected_message",
                "Discord rejected the job post. Review the post and webhook configuration.",
            )

        try:
            message = response.json()
            message_id = str(message["id"])
            channel_id = str(message["channel_id"])
            guild_id = message.get("guild_id")
        except (KeyError, TypeError, ValueError) as exc:
            raise DiscordDeliveryUncertainError(
                "discord_confirmation_invalid",
                "Discord may have accepted the post, but its delivery confirmation was invalid.",
            ) from exc

        return DiscordPublishResult(
            message_id=message_id,
            channel_id=channel_id,
            guild_id=str(guild_id) if guild_id is not None else None,
        )

    def _post_with_bounded_rate_limit(
        self,
        client: httpx.Client,
        webhook_url: str,
        payload: dict[str, Any],
    ) -> httpx.Response:
        for attempt in range(2):
            try:
                response = client.post(
                    webhook_url,
                    params={"wait": "true"},
                    json=payload,
                    timeout=self.timeout_seconds,
                )
            except httpx.RequestError as exc:
                raise DiscordDeliveryUncertainError(
                    "discord_delivery_uncertain",
                    "Discord may have accepted the post, but delivery could not be confirmed.",
                ) from exc

            if response.status_code != 429 or attempt == 1:
                return response

            retry_after = self._retry_after_seconds(response)
            if retry_after > self.max_rate_limit_wait_seconds:
                return response
            self.sleeper(retry_after)

        return response

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float:
        try:
            value = response.json().get("retry_after", 1)
            return max(0.0, float(value))
        except (AttributeError, TypeError, ValueError):
            return 1.0

    def _validated_webhook_url(self) -> str:
        if not self.webhook_url:
            raise DiscordConfigurationError(
                "discord_webhook_not_configured",
                "Discord publishing is not configured. Set DISCORD_WEBHOOK_URL on the backend.",
            )

        parsed = urlparse(self.webhook_url)
        hostname = (parsed.hostname or "").lower()
        valid_host = hostname in {"discord.com", "discordapp.com"} or (
            hostname.endswith(".discord.com")
            or hostname.endswith(".discordapp.com")
        )
        if (
            parsed.scheme != "https"
            or not valid_host
            or "/api/webhooks/" not in parsed.path
        ):
            raise DiscordConfigurationError(
                "discord_webhook_invalid",
                "DISCORD_WEBHOOK_URL must be a valid HTTPS Discord incoming-webhook URL.",
            )
        return self.webhook_url
