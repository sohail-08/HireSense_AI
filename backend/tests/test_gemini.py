import json

import httpx
import pytest

from app.llm.gemini import GeminiStructuredClient
from app.llm.errors import ProviderError, failure_detail


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


@pytest.mark.parametrize("status,code", [(401, "authentication"), (403, "authentication"), (429, "quota"), (400, "request_rejected"), (503, "unavailable")])
def test_provider_failure_category_never_exposes_remote_error_payload(status, code):
    def rejected(url, **_kwargs):
        return httpx.Response(status, request=httpx.Request("POST", url), json={"error": {"message": "PRIVATE source content and credential"}})
    client = GeminiStructuredClient(api_key="test-api-key", post=rejected)
    with pytest.raises(ProviderError) as caught:
        client.generate_json(model="test-model", system_instruction="Test", prompt="Synthetic", schema={"type": "object"})
    assert caught.value.code == code
    assert failure_detail(caught.value)["code"] == code
    assert "PRIVATE" not in str(caught.value) and "PRIVATE" not in failure_detail(caught.value)["message"]
