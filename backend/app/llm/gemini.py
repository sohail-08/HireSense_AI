import json
from collections.abc import Callable
from typing import Any

import httpx

from app.config import get_settings


PostFunction = Callable[..., httpx.Response]


class GeminiStructuredClient:
    """Minimal Gemini REST client for JSON-schema constrained generation."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        post: PostFunction | None = None,
    ):
        settings = get_settings()
        configured_key = (
            settings.gemini_api_key.get_secret_value()
            if settings.gemini_api_key is not None
            else ""
        )
        self.api_key = api_key if api_key is not None else configured_key
        self.base_url = (
            base_url or settings.gemini_api_base_url
        ).rstrip("/")
        self.timeout_seconds = (
            timeout_seconds or settings.gemini_timeout_seconds
        )
        self._post = post or httpx.post
        self.last_model_version = None

    def generate_json(
        self,
        *,
        model: str,
        system_instruction: str,
        prompt: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.api_key.strip():
            raise RuntimeError(
                "GEMINI_API_KEY is not configured in the backend environment"
            )

        payload = {
            "systemInstruction": {
                "parts": [{"text": system_instruction}],
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseJsonSchema": schema,
            },
        }
        model_name = model.removeprefix("models/")

        try:
            response = self._post(
                f"{self.base_url}/models/{model_name}:generateContent",
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": self.api_key,
                },
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            response_data = response.json()
            self.last_model_version = response_data.get("modelVersion")
            text = self._response_text(response_data)
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                raise ValueError("Gemini JSON response must be an object")
            return parsed
        except httpx.TimeoutException as exc:
            raise RuntimeError("Gemini API request timed out") from exc
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code in {401, 403}:
                message = "Gemini API authentication failed; check GEMINI_API_KEY"
            elif status_code == 429:
                message = "Gemini API quota was exceeded; retry after the quota resets"
            else:
                message = f"Gemini API request failed with status {status_code}"
            raise RuntimeError(message) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError("Gemini API is unavailable") from exc
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "Gemini returned an invalid structured response"
            ) from exc

    @staticmethod
    def _response_text(response_data: dict[str, Any]) -> str:
        candidates = response_data.get("candidates") or []
        if not candidates:
            block_reason = (
                response_data.get("promptFeedback", {}).get("blockReason")
            )
            if block_reason:
                raise ValueError(f"Gemini blocked the request: {block_reason}")
            raise ValueError("Gemini returned no candidates")

        parts = candidates[0].get("content", {}).get("parts", [])
        text_parts = [
            part["text"]
            for part in parts
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        ]
        if not text_parts:
            raise ValueError("Gemini returned no text content")
        return "".join(text_parts)
