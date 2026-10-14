import asyncio
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
import httpx2
from app.mcp_config import resolve_mcp_server
from app.security import create_access_token


class InterviewMCPClient:
    def __init__(self, user_id, url=None, timeout_seconds=None):
        self.user_id = user_id
        if url is None or timeout_seconds is None:
            connection = resolve_mcp_server("interview_scheduling")
            if url is None:
                url = connection.url
            if timeout_seconds is None:
                timeout_seconds = connection.timeout_seconds
        self.url = url
        self.timeout_seconds = timeout_seconds

    def call(self, name, arguments):
        try:
            return asyncio.run(asyncio.wait_for(self.call_async(name, arguments), self.timeout_seconds))
        except TimeoutError:
            raise RuntimeError("Interview tool timed out. Check invitation status before retrying confirmation.") from None
        except (ValueError, RuntimeError):
            raise
        except Exception:
            raise RuntimeError("Interview MCP server is unavailable. Check its configuration and invitation status before retrying.") from None

    async def call_async(self, name, arguments):
        # The identity is bound by the authenticated application, never an LLM argument.
        async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + create_access_token(self.user_id)}, timeout=self.timeout_seconds) as http:
            async with Client(streamable_http_client(self.url, http_client=http), cache=None) as client:
                result = await client.call_tool(name, arguments)
        if result.is_error:
            text = next((item.text for item in result.content if getattr(item, "type", None) == "text"), "Interview tool rejected this request")
            raise ValueError(text)
        if isinstance(result.structured_content, (dict, list)):
            value = result.structured_content
            return value.get("result", value) if isinstance(value, dict) else value
        import json
        return json.loads(next(item.text for item in result.content if item.type == "text"))
