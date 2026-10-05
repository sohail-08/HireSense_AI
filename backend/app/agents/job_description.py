import json
from typing import Protocol

import httpx

from app.config import get_settings
from app.rag.service import RetrievedKnowledgeChunk
from app.schemas.job import JobDescriptionDraft
from app.schemas.requirements import OllamaMessage


class JobDescriptionModel(Protocol):
    def generate(
        self,
        *,
        profile: dict,
        evidence: list[RetrievedKnowledgeChunk],
    ) -> JobDescriptionDraft:
        ...


class OllamaJobDescriptionModel:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ):
        settings = get_settings()
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_chat_model
        self.timeout_seconds = timeout_seconds or settings.ollama_timeout_seconds

    def generate(
        self,
        *,
        profile: dict,
        evidence: list[RetrievedKnowledgeChunk],
    ) -> JobDescriptionDraft:
        evidence_text = "\n\n".join(
            (
                f"[Source {index}] {item.document_title} "
                f"(chunk {item.chunk_index}, score {item.score:.3f})\n"
                f"{item.content}"
            )
            for index, item in enumerate(evidence, start=1)
        )
        if not evidence_text:
            evidence_text = "No policy or previous-JD context was retrieved."

        system_prompt = """You are HireSense's job-description writer.
Generate a professional job-description draft from the structured requirement profile.
Use the retrieved source context only as supporting company guidance. Do not invent
requirements, benefits, compensation, legal claims, or policies that are not present
in the profile or context. Required skills and qualifications must remain required;
preferred skills must remain preferred. Return only JSON matching the requested schema.
"""
        user_prompt = (
            "Requirement profile:\n"
            + json.dumps(profile, ensure_ascii=False)
            + "\n\nRetrieved source context:\n"
            + evidence_text
        )
        payload = {
            "model": self.model,
            "messages": [
                OllamaMessage(role="system", content=system_prompt).model_dump(),
                OllamaMessage(role="user", content=user_prompt).model_dump(),
            ],
            "stream": False,
            "format": JobDescriptionDraft.model_json_schema(),
            "options": {"temperature": 0},
        }

        try:
            response = httpx.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            response_data = response.json()
            content = response_data.get("message", {}).get("content", "")
            return JobDescriptionDraft.model_validate(json.loads(content))
        except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(
                "Ollama could not return a valid job-description draft"
            ) from exc


def render_job_description(draft: JobDescriptionDraft) -> str:
    """Render a stable human-readable JD from the validated structured draft."""
    lines = [
        f"# {draft.title}",
        "",
        draft.summary,
        "",
        "## Responsibilities",
        *[f"- {item}" for item in draft.responsibilities],
        "",
        "## Required Skills",
        *[f"- {item.name}: {item.details}" if item.details else f"- {item.name}"
          for item in draft.required_skills],
        "",
        "## Preferred Skills",
        *[f"- {item.name}: {item.details}" if item.details else f"- {item.name}"
          for item in draft.preferred_skills],
        "",
        "## Qualifications",
        *[f"- {item.name}: {item.details}" if item.details else f"- {item.name}"
          for item in draft.qualifications],
        "",
        "## Experience",
        draft.experience_requirement,
        "",
        "## Selection Process",
        *[f"- {item}" for item in draft.selection_criteria],
    ]
    return "\n".join(lines).strip() + "\n"
