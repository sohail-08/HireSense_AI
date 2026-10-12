from collections.abc import Callable
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.services.scoring_calculation import assign_ranks, category_scores, justification, weighted_score


class ScoringState(TypedDict, total=False):
    configuration: dict
    applications: list[dict]
    results: list[dict]
    run_id: int


class CandidateScoringWorkflow:
    """Runs only against saved evidence; never parses CVs or invokes an LLM."""

    def __init__(self, persist: Callable):
        self.persist = persist
        graph = StateGraph(ScoringState)
        graph.add_node("category_scoring", self._categories)
        graph.add_node("weighted_scoring", self._weighted)
        graph.add_node("written_justification", self._justify)
        graph.add_node("rank_candidates", self._rank)
        graph.add_node("persist_scores", self._persist)
        graph.add_edge(START, "category_scoring")
        graph.add_edge("category_scoring", "weighted_scoring")
        graph.add_edge("weighted_scoring", "written_justification")
        graph.add_edge("written_justification", "rank_candidates")
        graph.add_edge("rank_candidates", "persist_scores")
        graph.add_edge("persist_scores", END)
        self._compiled = graph.compile()

    def invoke(self, configuration: dict, applications: list[dict]):
        return self._compiled.invoke({"configuration": configuration, "applications": applications})

    @staticmethod
    def _categories(state):
        return {"results": [{"application_id": app["application_id"], "screening_run_id": app.get("screening_run_id"),
                             "breakdown": category_scores(state["configuration"], app)} for app in state["applications"]]}

    @staticmethod
    def _weighted(state):
        return {"results": [{**result, "breakdown": weighted_score(state["configuration"], result["breakdown"])} for result in state["results"]]}

    @staticmethod
    def _justify(state):
        return {"results": [{**result, "written_justification": justification(result["breakdown"])} for result in state["results"]]}

    @staticmethod
    def _rank(state):
        return {"results": assign_ranks(state["results"])}

    def _persist(self, state):
        return {"run_id": self.persist(state["results"])}
