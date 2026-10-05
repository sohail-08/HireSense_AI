from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.job_description import (
    JobDescriptionModel,
    render_job_description,
)
from app.models.job import (
    JobDescription,
    JobDescriptionStatus,
    RequirementProfile,
    RequirementProfileStatus,
)
from app.rag.service import KnowledgeBaseService
from app.schemas.job import JobDescriptionDraft, JobDescriptionUpdateRequest


class JobDescriptionService:
    def __init__(
        self,
        model: JobDescriptionModel,
        knowledge_base: KnowledgeBaseService | None = None,
    ):
        self.model = model
        self.knowledge_base = knowledge_base or KnowledgeBaseService()

    def generate(
        self,
        db: Session,
        *,
        requirement_profile_id: int,
        interviewer_user_id: int,
    ) -> JobDescription:
        profile = db.get(RequirementProfile, requirement_profile_id)
        if profile is None or profile.created_by_user_id != interviewer_user_id:
            raise LookupError("Requirement profile not found")
        if profile.status != RequirementProfileStatus.CONFIRMED:
            raise ValueError("Requirement profile must be confirmed before JD generation")

        evidence = self.knowledge_base.search(
            db,
            self._retrieval_query(profile),
            top_k=5,
        )
        draft = self.model.generate(
            profile=self._profile_payload(profile),
            evidence=evidence,
        )
        source_references = [
            {
                "document_id": item.document_id,
                "document_title": item.document_title,
                "source_type": item.source_type.value,
                "chunk_id": item.chunk_id,
                "chunk_index": item.chunk_index,
                "score": item.score,
                "source_uri": item.source_uri,
            }
            for item in evidence
        ]

        latest_version = db.scalar(
            select(func.max(JobDescription.version)).where(
                JobDescription.requirement_profile_id == requirement_profile_id
            )
        )
        job_description = JobDescription(
            requirement_profile_id=requirement_profile_id,
            title=draft.title,
            content=render_job_description(draft),
            structured_content=draft.model_dump(mode="json"),
            source_references=source_references,
            version=(latest_version or 0) + 1,
            status=JobDescriptionStatus.DRAFT,
            created_by_user_id=interviewer_user_id,
        )
        db.add(job_description)
        db.commit()
        db.refresh(job_description)
        return job_description

    def get_for_interviewer(
        self,
        db: Session,
        *,
        job_description_id: int,
        interviewer_user_id: int,
    ) -> JobDescription:
        job_description = db.get(JobDescription, job_description_id)
        if (
            job_description is None
            or job_description.created_by_user_id != interviewer_user_id
        ):
            raise LookupError("Job description not found")
        return job_description

    def update_draft(
        self,
        db: Session,
        *,
        job_description_id: int,
        interviewer_user_id: int,
        update: JobDescriptionUpdateRequest,
    ) -> JobDescription:
        job_description = self.get_for_interviewer(
            db,
            job_description_id=job_description_id,
            interviewer_user_id=interviewer_user_id,
        )
        if job_description.status != JobDescriptionStatus.DRAFT:
            raise ValueError("Only draft job descriptions can be edited")

        if update.title is not None:
            job_description.title = update.title
        if update.structured_content is not None:
            job_description.structured_content = update.structured_content.model_dump(
                mode="json"
            )
            job_description.content = render_job_description(update.structured_content)
            job_description.title = update.structured_content.title
        elif update.content is not None:
            job_description.content = update.content

        db.commit()
        db.refresh(job_description)
        return job_description

    def approve(
        self,
        db: Session,
        *,
        job_description_id: int,
        interviewer_user_id: int,
    ) -> JobDescription:
        job_description = self.get_for_interviewer(
            db,
            job_description_id=job_description_id,
            interviewer_user_id=interviewer_user_id,
        )
        if job_description.status != JobDescriptionStatus.DRAFT:
            raise ValueError("Only draft job descriptions can be approved")
        job_description.status = JobDescriptionStatus.APPROVED
        db.commit()
        db.refresh(job_description)
        return job_description

    @staticmethod
    def _profile_payload(profile: RequirementProfile) -> dict[str, Any]:
        return {
            "title": profile.title,
            "summary": profile.summary,
            "required_skills": profile.required_skills,
            "preferred_skills": profile.preferred_skills,
            "qualifications": profile.qualifications,
            "min_years_experience": profile.min_years_experience,
            "selection_criteria": profile.selection_criteria,
        }

    @staticmethod
    def _retrieval_query(profile: RequirementProfile) -> str:
        parts = [profile.title, profile.summary or ""]
        for group in (
            profile.required_skills,
            profile.preferred_skills,
            profile.qualifications,
            profile.selection_criteria,
        ):
            parts.extend(
                str(item.get("name", ""))
                for item in group
                if item.get("name")
            )
        if profile.min_years_experience is not None:
            parts.append(f"{profile.min_years_experience} years experience")
        return " ".join(part for part in parts if part).strip()
