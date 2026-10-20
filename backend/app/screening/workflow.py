from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.models.candidate import CVDocument
from app.models.screening import ScreeningRun
from app.screening.ai import ScreeningAI, experience_years, ScreeningAssessment
from datetime import date
from app.screening.parsing import CVParser


class ScreeningGraphState(TypedDict, total=False):
    run_id: int
    document_id: int
    text: str
    blocks: list[dict[str, str]]
    parser_metadata: dict[str, Any]
    profile: dict[str, Any]
    assessment: dict[str, Any]
    evidence_validation: dict[str, Any]
    validated_result: dict[str, Any]
    requirements: list[dict]


class ScreeningWorkflow:
    """One application's auditable parse → extract → match workflow."""

    def __init__(
        self,
        *,
        db: Session,
        parser: CVParser,
        ai: ScreeningAI,
        validate_result,
        persist_result,
        retriever=None,
        parsed=None,
    ):
        self.db = db
        self.parser = parser
        self.ai = ai
        self.validate_result = validate_result
        self.persist_result = persist_result
        self.retriever = retriever
        self.parsed = parsed

        graph = StateGraph(ScreeningGraphState)
        graph.add_node("retrieve_validate_extract_text", self._parse)
        graph.add_node("extract_structured_profile", self._extract_profile)
        graph.add_node("match_requirements", self._match)
        graph.add_node("validate_evidence", self._validate)
        graph.add_node("persist_result", self._persist)
        graph.add_edge(START, "retrieve_validate_extract_text")
        graph.add_edge("retrieve_validate_extract_text", "extract_structured_profile")
        graph.add_edge("extract_structured_profile", "match_requirements")
        graph.add_edge("match_requirements", "validate_evidence")
        graph.add_edge("validate_evidence", "persist_result")
        graph.add_edge("persist_result", END)
        self._compiled = graph.compile()

    def invoke(self, *, run_id: int, document_id: int) -> ScreeningGraphState:
        result = self._compiled.invoke(
            {"run_id": run_id, "document_id": document_id}
        )
        return ScreeningGraphState(**result)

    def _parse(self, state: ScreeningGraphState) -> dict[str, Any]:
        document = self.db.get(CVDocument, state["document_id"])
        if document is None:
            raise ValueError("The CV record no longer exists")
        parsed = self.parsed or self.parser.parse(document)
        blocks = [block.as_dict() for block in parsed.blocks]
        run = self.db.get(ScreeningRun, state["run_id"])
        requirements = run.requirement_snapshot["requirements"]
        retrieval = {}
        if self.retriever:
            blocks, requirements, retrieval = self.retriever.prepare(self.db, document, blocks, requirements)
        return {
            "text": parsed.text,
            "blocks": blocks,
            "requirements": requirements,
            "parser_metadata": {
                "parser": parsed.parser,
                "page_count": parsed.page_count,
                "warnings": parsed.warnings,
                "semantic_retrieval": retrieval,
            },
        }

    def _extract_profile(self, state: ScreeningGraphState) -> dict[str, Any]:
        profile = self.ai.extract_profile(blocks=state["blocks"])
        run = self.db.get(ScreeningRun, state["run_id"])
        as_of = (run.processing_metadata or {}).get("as_of", date.today().isoformat())
        years, warnings = experience_years(profile, date.fromisoformat(as_of))
        data = profile.model_dump(mode="json")
        data["calculated_total_experience_years"] = years
        data["experience_calculation_warnings"] = warnings
        data["evaluation_as_of"] = as_of
        return {"profile": data}

    def _match(self, state: ScreeningGraphState) -> dict[str, Any]:
        run = self.db.get(ScreeningRun, state["run_id"])
        if run is None:
            raise ValueError("The screening run no longer exists")
        assessment = self.ai.assess_requirements(
            profile=state["profile"],
            requirements=state["requirements"],
            blocks=state["blocks"],
        )
        return {"assessment": assessment.model_dump(mode="json")}

    def _validate(self, state: ScreeningGraphState) -> dict[str, Any]:
        run = self.db.get(ScreeningRun, state["run_id"])
        if run is None:
            raise ValueError("The screening run no longer exists")
        assessment = ScreeningAssessment.model_validate(state["assessment"])
        metadata = state["parser_metadata"]
        if hasattr(self.ai, "audit_and_recover"):
            assessment, evidence_validation, recovery = self.ai.audit_and_recover(profile=state["profile"],
                requirements=state["requirements"], blocks=state["blocks"], assessment=assessment)
            metadata = {**metadata, "evidence_recovery": recovery, "experience_calculations": {
                m.requirement_key: m.experience_calculation for m in assessment.matches if m.experience_calculation},
                "decision_rules": {m.requirement_key: m.decision_rule for m in assessment.matches if m.decision_rule}}
        else:
            evidence_validation = self.ai.validate_evidence(
                requirements=state["requirements"], proposed_assessment=state["assessment"], blocks=state["blocks"])
        return {
            "parser_metadata": metadata,
            "evidence_validation": evidence_validation.model_dump(mode="json"),
            "validated_result": self.validate_result(
                requirements=run.requirement_snapshot["requirements"],
                blocks=state["blocks"],
                assessment=assessment.model_dump(mode="json"),
                evidence_validation=evidence_validation.model_dump(mode="json"),
            )
        }

    def _persist(self, state: ScreeningGraphState) -> dict[str, Any]:
        self.persist_result(
            run_id=state["run_id"],
            text=state["text"],
            blocks=state["blocks"],
            parser_metadata=state["parser_metadata"],
            profile=state["profile"],
            result=state["validated_result"],
        )
        return {}
