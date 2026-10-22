from sqlalchemy.orm import Session

from app.agents.direct_job_description import DirectJobDescriptionModel
from app.agents.job_description import render_job_description
from app.models.job import JobDescription, JobDescriptionStatus, RequirementProfile, RequirementProfileStatus
from app.models.knowledge import KnowledgeSourceType
from app.rag.service import KnowledgeBaseService


class DirectJobDescriptionService:
    def __init__(self, model: DirectJobDescriptionModel, knowledge_base: KnowledgeBaseService):
        self.model = model
        self.knowledge_base = knowledge_base

    def draft(self, db: Session, *, interviewer_user_id: int, messages: list[dict],
              role_title: str | None = None) -> dict:
        """The caller commits the draft, internal screening profile and session together."""
        # Only authentic human input may supply missing job details. Old assistant
        # requirement proposals are not evidence, including in restored sessions.
        conversation = [{"role": "user", "content": item["content"]}
                        for item in messages if item.get("role") == "user"][-30:]
        if not conversation:
            raise ValueError("Tell me the role you want to hire for.")
        # Keep the requested role on follow-ups such as 'continue' or 'retry',
        # including sessions saved before direct drafting was introduced.
        query = "\n".join([role_title or conversation[0]["content"],
                            *[item["content"] for item in conversation[-2:]]])[-10_000:]
        try:
            evidence = self.knowledge_base.search(db, query, top_k=8, min_score=0.1,
                source_type=KnowledgeSourceType.PREVIOUS_JOB_DESCRIPTION)
        except (RuntimeError, ValueError) as exc:
            # An unavailable embedding/KB service is not a missing role.
            raise RuntimeError("The knowledge base could not be checked. Please try again.") from exc
        plan = self.model.plan(messages=conversation, evidence=evidence)
        available_ids = {item.chunk_id for item in evidence}
        if not set(plan.relevant_chunk_ids).issubset(available_ids):
            raise RuntimeError("The draft referenced an unknown knowledge source. Please retry.")
        relevant = [item for item in evidence if item.chunk_id in plan.relevant_chunk_ids]
        verified_details = bool(plan.detail_quotes) and all(
            quote.strip() and any(quote in item["content"] for item in conversation)
            for quote in plan.detail_quotes
        )
        if not relevant and not (plan.user_details_sufficient and verified_details):
            return {"job": None, "role_title": plan.role_title, "assistant_message": (
                "I couldn't find enough information for this role in the knowledge base. "
                + (plan.follow_up_question or "What skills should the person have, and what will they do?")
            )}

        draft = self.model.generate(messages=conversation, role_title=plan.role_title, evidence=relevant)
        if not draft.required_skills or not all(item.strip() for item in draft.responsibilities):
            raise RuntimeError("The draft is missing skills or responsibilities. Please add those details and try again.")
        references = [{"document_id": item.document_id, "document_title": item.document_title,
            "source_type": item.source_type.value, "chunk_id": item.chunk_id,
            "chunk_index": item.chunk_index, "score": item.score, "source_uri": item.source_uri}
            for item in relevant]
        structured = draft.model_dump(mode="json", exclude={"min_years_experience"})
        # A savepoint prevents an orphan profile if saving the JD fails. No
        # approval/posting mutation is possible from this service.
        with db.begin_nested():
            profile = RequirementProfile(
                title=draft.title, summary=draft.summary,
                required_skills=structured["required_skills"], preferred_skills=structured["preferred_skills"],
                qualifications=structured["qualifications"], min_years_experience=draft.min_years_experience,
                selection_criteria=[{"name": item, "details": None} for item in draft.selection_criteria],
                source_references=references,
                generation_metadata={"source": "direct_job_description", "knowledge_status": "found" if relevant else "empty"},
                status=RequirementProfileStatus.CONFIRMED, created_by_user_id=interviewer_user_id,
            )
            db.add(profile)
            db.flush()
            job = JobDescription(requirement_profile_id=profile.id, title=draft.title,
                content=render_job_description(draft), structured_content=structured,
                source_references=references, version=1, status=JobDescriptionStatus.DRAFT,
                created_by_user_id=interviewer_user_id)
            db.add(job)
            db.flush()
        return {"job": job, "role_title": plan.role_title,
            "assistant_message": f'I drafted “{job.title}”. Review it, ask for changes, or approve it when you are ready.'}
