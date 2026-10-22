from app.agents.direct_job_description import GroundedJobDraft, JobDraftPlan
from app.models.knowledge import KnowledgeSourceType
from app.rag.service import RetrievedKnowledgeChunk


def reference(chunk_id=41):
    return RetrievedKnowledgeChunk(document_id=7, document_title="Backend Engineer reference",
        source_type=KnowledgeSourceType.PREVIOUS_JOB_DESCRIPTION, chunk_id=chunk_id, chunk_index=0,
        content="Backend Engineer. Build and test APIs using Python. At least 3 years of experience.",
        score=0.7, source_uri=None)


def grounded_draft():
    return GroundedJobDraft(title="Backend Engineer", summary="Build reliable backend services.",
        responsibilities=["Build and test APIs"], required_skills=[{"name": "Python"}],
        experience_requirement="At least 3 years of backend experience.", min_years_experience=3)


class FakeDirectModel:
    def __init__(self, plans=None, draft=None):
        self.plans = list(plans or [JobDraftPlan(role_title="Backend Engineer", relevant_chunk_ids=[41])])
        self.draft = draft or grounded_draft()
        self.plan_calls = []
        self.generate_calls = []

    def plan(self, **kwargs):
        self.plan_calls.append(kwargs)
        return self.plans.pop(0)

    def generate(self, **kwargs):
        self.generate_calls.append(kwargs)
        if isinstance(self.draft, Exception):
            raise self.draft
        return self.draft


class FakeKnowledgeBase:
    def __init__(self, evidence=None, error=None):
        self.evidence = [reference()] if evidence is None else evidence
        self.error = error
        self.calls = []

    def search(self, db, query, **kwargs):
        self.calls.append({"query": query, **kwargs})
        if self.error:
            raise self.error
        return self.evidence
