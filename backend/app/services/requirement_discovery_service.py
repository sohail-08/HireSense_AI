from typing import Any

from sqlalchemy.orm import Session

from app.agents.requirement_discovery import RequirementDiscoveryGraph, RequirementModel
from app.config import get_settings
from app.models.job import RequirementProfile, RequirementProfileStatus
from app.models.knowledge import KnowledgeSourceType
from app.models.requirement_session import (
    RequirementDiscoverySession,
    RequirementDiscoveryStatus,
)
from app.rag.service import KnowledgeBaseService, RetrievedKnowledgeChunk
from app.schemas.requirements import RequirementProfileDraft


class RequirementDiscoveryService:
    def __init__(
        self,
        model: RequirementModel,
        knowledge_base: KnowledgeBaseService | None = None,
    ):
        self.model = model
        self.knowledge_base = knowledge_base or KnowledgeBaseService()

    def chat(
        self,
        db: Session,
        *,
        interviewer_user_id: int,
        message: str,
        session_id: str | None = None,
    ) -> tuple[RequirementDiscoverySession, dict[str, Any]]:
        session = (
            db.get(RequirementDiscoverySession, session_id)
            if session_id
            else None
        )
        if session is not None and session.interviewer_user_id != interviewer_user_id:
            raise PermissionError("Requirement session belongs to another interviewer")

        if session is None:
            session = RequirementDiscoverySession(
                interviewer_user_id=interviewer_user_id,
                state_json={},
            )
            db.add(session)
            db.flush()

        if session.status == RequirementDiscoveryStatus.CONFIRMED:
            state = session.state_json
        else:
            graph = RequirementDiscoveryGraph(
                self.model,
                knowledge_retriever=lambda profile: self._retrieve_knowledge(
                    db, profile
                ),
            )
            state = graph.invoke(
                message,
                state=(session.state_json or None),
            )
            session.state_json = dict(state)
            session.status = self._session_status(state.get("status", "active"))

            if state.get("confirmed") and session.requirement_profile_id is None:
                profile = RequirementProfileDraft.model_validate(
                    state.get("profile", {})
                )
                if not profile.title:
                    raise ValueError("A confirmed profile must include a title")
                requirement_profile = RequirementProfile(
                    title=profile.title,
                    summary=profile.summary,
                    required_skills=[
                        item.model_dump(mode="json")
                        for item in profile.required_skills
                    ],
                    preferred_skills=[
                        item.model_dump(mode="json")
                        for item in profile.preferred_skills
                    ],
                    qualifications=[
                        item.model_dump(mode="json")
                        for item in profile.qualifications
                    ],
                    min_years_experience=profile.min_years_experience,
                    selection_criteria=[
                        item.model_dump(mode="json")
                        for item in profile.selection_criteria
                    ],
                    source_references=state.get("source_references", []),
                    generation_metadata={
                        "chat_model": get_settings().ollama_chat_model,
                        "embedding_model": get_settings().ollama_embedding_model,
                        "prompt_version": "requirement-discovery-v2",
                        "knowledge_status": state.get(
                            "knowledge_status", "not_searched"
                        ),
                    },
                    interviewer_overrides={
                        "messages": state.get("interviewer_overrides", [])
                    },
                    status=RequirementProfileStatus.CONFIRMED,
                    created_by_user_id=interviewer_user_id,
                )
                db.add(requirement_profile)
                db.flush()
                session.requirement_profile_id = requirement_profile.id

            db.commit()
            db.refresh(session)
            state = session.state_json

        return session, self._response_state(state)

    @staticmethod
    def _session_status(status: str) -> RequirementDiscoveryStatus:
        if status == "awaiting_changes":
            return RequirementDiscoveryStatus.ACTIVE
        try:
            return RequirementDiscoveryStatus(status)
        except ValueError:
            return RequirementDiscoveryStatus.ERROR

    @staticmethod
    def _response_state(state: dict[str, Any]) -> dict[str, Any]:
        profile = RequirementProfileDraft.model_validate(state.get("profile", {}))
        return {
            "status": state.get("status", "active"),
            "assistant_message": state.get("assistant_message", ""),
            "profile": profile,
            "missing_fields": state.get("missing_fields", []),
            "error": state.get("error"),
            "error_code": state.get("error_code"),
            "knowledge_status": state.get(
                "knowledge_status", "not_searched"
            ),
            "proposal_ready": state.get("proposal_ready", False),
            "source_references": state.get("source_references", []),
        }

    def _retrieve_knowledge(
        self,
        db: Session,
        profile: RequirementProfileDraft,
    ) -> list[RetrievedKnowledgeChunk]:
        query = " ".join(
            part for part in [profile.title or "", profile.summary or ""] if part
        )
        previous_jds = self.knowledge_base.search(
            db,
            query,
            top_k=2,
            min_score=0.1,
            source_type=KnowledgeSourceType.PREVIOUS_JOB_DESCRIPTION,
        )
        policies = self.knowledge_base.search(
            db,
            query,
            top_k=2,
            min_score=0.1,
            source_type=KnowledgeSourceType.COMPANY_POLICY,
        )
        return previous_jds + policies
