from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.agents.job_description import (
    JobDescriptionModel,
    render_job_description,
)
from app.config import get_settings
from app.models.candidate import CandidateApplication
from app.models.job import (
    JobDescription,
    JobDescriptionStatus,
    JobPosting,
    RequirementProfile,
    RequirementProfileStatus,
)
from app.models.supervisor import SupervisorSession
from app.rag.service import KnowledgeBaseService
from app.schemas.job import JobDescriptionManualCreate, JobDescriptionUpdateRequest
from app.services.candidate_application_service import CandidateApplicationService


class JobDescriptionService:
    @staticmethod
    def create_manual(
        db: Session,
        *,
        data: JobDescriptionManualCreate,
        interviewer_user_id: int,
    ) -> JobDescription:
        """Save the interviewer's text and explicit requirements without AI/RAG."""
        required = [item.model_dump(mode="json") for item in data.required_skills]
        preferred = [item.model_dump(mode="json") for item in data.preferred_skills]
        qualifications = [item.model_dump(mode="json") for item in data.qualifications]
        profile = RequirementProfile(
            title=data.title,
            summary=data.content,
            required_skills=required,
            preferred_skills=preferred,
            qualifications=qualifications,
            min_years_experience=data.min_years_experience,
            selection_criteria=[],
            source_references=[],
            generation_metadata={"source": "manual", "model_used": False},
            status=RequirementProfileStatus.CONFIRMED,
            created_by_user_id=interviewer_user_id,
        )
        try:
            db.add(profile)
            db.flush()
            job = JobDescription(
                requirement_profile_id=profile.id,
                title=data.title,
                content=data.content,
                structured_content={
                    "title": data.title, "summary": data.content,
                    "responsibilities": [], "required_skills": required,
                    "preferred_skills": preferred, "qualifications": qualifications,
                    "experience_requirement": (
                        f"At least {data.min_years_experience} years of relevant experience."
                        if data.min_years_experience is not None else "Not specified."
                    ),
                    "selection_criteria": [],
                },
                source_references=[],
                version=1,
                status=JobDescriptionStatus.DRAFT,
                created_by_user_id=interviewer_user_id,
            )
            db.add(job)
            db.commit()
            db.refresh(job)
            return job
        except Exception:
            db.rollback()
            raise

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

    @staticmethod
    def list_for_interviewer(
        db: Session,
        *,
        interviewer_user_id: int,
    ) -> list[JobDescription]:
        return list(
            db.scalars(
                select(JobDescription)
                .where(
                    JobDescription.created_by_user_id == interviewer_user_id,
                    JobDescription.status != JobDescriptionStatus.ARCHIVED,
                )
                .order_by(
                    JobDescription.updated_at.desc(),
                    JobDescription.id.desc(),
                )
            )
        )

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

    def revise(
        self,
        db: Session,
        *,
        job_description_id: int,
        interviewer_user_id: int,
    ) -> JobDescription:
        approved = self.get_for_interviewer(
            db,
            job_description_id=job_description_id,
            interviewer_user_id=interviewer_user_id,
        )
        if approved.status != JobDescriptionStatus.APPROVED:
            raise ValueError(
                "Only approved job descriptions need an editable revision"
            )

        latest_version = db.scalar(
            select(func.max(JobDescription.version)).where(
                JobDescription.requirement_profile_id
                == approved.requirement_profile_id
            )
        )
        revision = JobDescription(
            requirement_profile_id=approved.requirement_profile_id,
            title=approved.title,
            content=approved.content,
            structured_content=dict(approved.structured_content),
            source_references=list(approved.source_references),
            version=(latest_version or approved.version) + 1,
            status=JobDescriptionStatus.DRAFT,
            created_by_user_id=interviewer_user_id,
        )
        db.add(revision)
        db.commit()
        db.refresh(revision)
        return revision

    def delete(
        self,
        db: Session,
        *,
        job_description_id: int,
        interviewer_user_id: int,
    ) -> None:
        job_description = self.get_for_interviewer(
            db,
            job_description_id=job_description_id,
            interviewer_user_id=interviewer_user_id,
        )
        posting_ids = list(
            db.scalars(
                select(JobPosting.id).where(
                    JobPosting.job_description_id == job_description.id
                )
            )
        )
        session_reference_filter = (
            SupervisorSession.job_description_id == job_description.id
        )
        if posting_ids:
            session_reference_filter = or_(
                session_reference_filter,
                SupervisorSession.job_posting_id.in_(posting_ids),
            )
        supervisor_sessions = list(
            db.scalars(
                select(SupervisorSession).where(session_reference_filter)
            )
        )
        for supervisor in supervisor_sessions:
            supervisor.job_description_id = None
            supervisor.job_posting_id = None
            supervisor.phase = (
                "requirement_confirmed"
                if supervisor.requirement_profile_id is not None
                else "requirements"
            )

        application_service = CandidateApplicationService(get_settings())
        stored_paths = []
        candidate_ids: set[int] = set()
        if posting_ids:
            applications = list(
                db.scalars(
                    select(CandidateApplication).where(
                        CandidateApplication.job_posting_id.in_(posting_ids)
                    )
                )
            )
            for application in applications:
                paths, candidate_id = application_service.delete_record(
                    db,
                    application=application,
                    interviewer_user_id=interviewer_user_id,
                    remember_import=False,
                )
                stored_paths.extend(paths)
                if candidate_id is not None:
                    candidate_ids.add(candidate_id)
            db.flush()
            for candidate_id in candidate_ids:
                application_service.delete_orphan_candidate(db, candidate_id)
            postings = list(
                db.scalars(
                    select(JobPosting).where(JobPosting.id.in_(posting_ids))
                )
            )
            for posting in postings:
                db.delete(posting)
            db.flush()

        db.delete(job_description)
        db.commit()
        application_service.cleanup_cv_files(stored_paths)

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
