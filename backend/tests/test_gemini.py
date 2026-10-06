import json

import httpx
import pytest

from app.llm.gemini import GeminiStructuredClient


def test_gemini_client_requests_json_schema_output():
    captured: dict = {}

    def fake_post(url, **kwargs):  # noqa: ANN001
        captured["url"] = url
        captured.update(kwargs)
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": json.dumps({"title": "Backend Engineer"})}
                            ]
                        }
                    }
                ]
            },
        )

    schema = {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
    }
    client = GeminiStructuredClient(
        api_key="test-api-key",
        base_url="https://gemini.example/v1beta",
        timeout_seconds=12,
        post=fake_post,
    )

    result = client.generate_json(
        model="models/gemini-test",
        system_instruction="Return a title.",
        prompt="Backend role",
        schema=schema,
    )

    assert result == {"title": "Backend Engineer"}
    assert captured["url"].endswith(
        "/models/gemini-test:generateContent"
    )
    assert captured["headers"]["x-goog-api-key"] == "test-api-key"
    assert captured["timeout"] == 12
    assert captured["json"]["generationConfig"] == {
        "temperature": 0,
        "responseMimeType": "application/json",
        "responseJsonSchema": schema,
    }


def test_gemini_client_requires_backend_api_key():
    client = GeminiStructuredClient(
        api_key="",
        post=lambda *_args, **_kwargs: pytest.fail("request should not run"),
    )

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY is not configured"):
        client.generate_json(
            model="gemini-test",
            system_instruction="System",
            prompt="Prompt",
            schema={"type": "object"},
        )


def test_gemini_client_reports_free_tier_quota_error():
    def quota_response(url, **_kwargs):  # noqa: ANN001
        return httpx.Response(
            429,
            request=httpx.Request("POST", url),
            json={"error": {"message": "quota exceeded"}},
        )

    client = GeminiStructuredClient(
        api_key="test-api-key",
        post=quota_response,
    )

    with pytest.raises(RuntimeError, match="quota was exceeded"):
        client.generate_json(
            model="gemini-test",
            system_instruction="System",
            prompt="Prompt",
            schema={"type": "object"},
        )
