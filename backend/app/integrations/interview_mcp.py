import asyncio
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
import httpx2
from app.config import get_settings
from app.security import create_access_token


class InterviewMCPClient:
    def __init__(self, user_id, url=None):
        self.user_id = user_id
        self.url = url or get_settings().interview_mcp_url

    def call(self, name, arguments):
        try:
            return asyncio.run(asyncio.wait_for(self.call_async(name, arguments), get_settings().interview_mcp_timeout_seconds))
        except TimeoutError:
            raise RuntimeError("Interview tool timed out. Check invitation status before retrying confirmation.") from None
        except (ValueError, RuntimeError):
            raise
        except Exception:
            raise RuntimeError("Interview MCP server is unavailable. Check its configuration and invitation status before retrying.") from None

    async def call_async(self, name, arguments):
        # The identity is bound by the authenticated application, never an LLM argument.
        async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + create_access_token(self.user_id)}, timeout=120) as http:
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
