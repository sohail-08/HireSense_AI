"""Reference/scoping regressions use synthetic text and mocked models only."""
import copy
import json
from pathlib import Path
import pytest
from app.agents.interview_analysis import InterviewAnalysisGraph, present_result
from app.agents.interview_references import retrieval_query, select_guides
from app.agents.interview_scope import pure_housekeeping
from test_interview_analysis import Model, execute, segment, snapshot


@pytest.mark.parametrize("missing", ["accuracy", "completeness", "both", "false_positive", "foreign_quote", "candidate_quote", "foreign_segment"])
def test_incomplete_guide_citations_are_retried_before_support_check(missing):
    class Incomplete(Model):
        attempts = 0
        def generate_json(self, **kwargs):
            result = super().generate_json(**kwargs)
            if kwargs["schema"]["title"] == "Assessment":
                self.attempts += 1
                if self.attempts == 1:
                    for name in ("accuracy", "completeness"):
                        if missing in (name, "both", "false_positive"):result[name]["references"] = []
                    if missing == "false_positive":result["accuracy"]["label"] = "unable_to_verify"
                    if missing == "foreign_quote":result["completeness"]["references"][0]["quote"] = "Not in the guide"
                    if missing == "candidate_quote":result["accuracy"]["citations"][0] = {"segment_id":result["accuracy"]["citations"][0]["segment_id"],"quote":"Not in the saved answer"}
                    if missing == "foreign_segment":result["accuracy"]["citations"][0] = {"segment_id":"foreign","quote":"Transactions are atomic."}
            return result
    model = Incomplete()
    pair = execute(snapshot([segment(1,"INTERVIEWER","Explain transactions"),segment(2,"CANDIDATE","Transactions are atomic.")]),model)["pairs"][0]
    assert model.attempts == 2 and pair["score"]["percentage"] == 100
    assert sum(title == "SupportCheck" for title,_,_ in model.calls) == 1
    assert all(pair["assessment"][name]["references"] for name in ("accuracy","completeness"))


def test_repeated_missing_citations_are_a_safe_retryable_failure_not_a_zero():
    class Missing(Model):
        def generate_json(self, **kwargs):
            result = super().generate_json(**kwargs)
            if kwargs["schema"]["title"] == "Assessment":result["completeness"]["references"] = []
            return result
    model = Missing()
    pair = execute(snapshot([segment(1,"INTERVIEWER","Explain transactions"),segment(2,"CANDIDATE","Transactions are atomic.")]),model)["pairs"][0]
    assert pair["state"] == "analysis_failed" and "score" not in pair
    assert pair["analysis_failure"]["code"] == "missing_reference"
    assert sum(title == "Assessment" for title,_,_ in model.calls) == 2
    assert not any(title == "SupportCheck" for title,_,_ in model.calls)


def test_legitimate_reference_gap_is_not_forced_into_a_cited_grade():
    class Unverified(Model):
        def generate_json(self, **kwargs):
            result = super().generate_json(**kwargs)
            if kwargs["schema"]["title"] == "Assessment":
                for name in ("accuracy","completeness"):result[name].update(score=0,references=[])
                result["accuracy"]["label"] = "unable_to_verify"
                result["expected_elements_basis"] = "provisional"
            return result
    model = Unverified()
    pair = execute(snapshot([segment(1,"INTERVIEWER","Explain transactions"),segment(2,"CANDIDATE","I used transactions.")]),model)["pairs"][0]
    assert "score" not in pair and pair["assessment"]["accuracy"]["label"] == "unable_to_verify"
    assert sum(title == "Assessment" for title,_,_ in model.calls) == 1


@pytest.mark.parametrize("question,topic", [
    ("Kindly tell me what is semantic HTML and why it is important.","semantic HTML accessibility CSS"),
    ("How would you build a responsive layout?","semantic HTML accessibility CSS"),
    ("What is the difference between state and in React?","React state management"),
    ("When would you use use effect?","React state management"),
    ("How would you test a login form?","frontend testing performance"),
])
def test_topic_match_rescues_frontend_guide_missed_by_vector_search(question,topic):
    records = json.loads((Path(__file__).parents[1]/'app/data/interview_questions.json').read_text())
    refs = [{"id":str(i),"kind":"answer_guide","title":r["role"]+" "+r["topic"],
             "content":r["focus"]+" "+r["answer_guide"]} for i,r in enumerate(records)]
    wrong = [str(i) for i,r in enumerate(records) if r["role"] != "Frontend Engineer"][:8]
    chosen = select_guides(question,refs,wrong)
    wanted = str(next(i for i,r in enumerate(records) if r["topic"] == topic))
    assert wanted in chosen and len(chosen) <= 6


def test_search_normalization_adds_job_context_without_mutating_spoken_question():
    question = "When would you use use effect?"
    query = retrieval_query(question,{"requirements":[{"name":"React"},{"name":"TypeScript"}]})
    assert "useEffect" in query and "React" in query and "TypeScript" in query
    assert question == "When would you use use effect?"
    assert select_guides("Can you do this?",[{"id":"other","kind":"answer_guide","title":"Other","content":"This is a guide."}],[]) == []


def test_failed_pair_retrieves_again_instead_of_freezing_a_bad_guide_selection():
    data = snapshot([segment(1,"INTERVIEWER","Explain transactions"),segment(2,"CANDIDATE","Transactions are atomic.")])
    data["references"][0]["source"] = "knowledge_base"
    first = execute(data)
    old = copy.deepcopy(first["pairs"][0])
    old.update(state="analysis_failed",reference_ids=["missing"])
    old.pop("score")
    retriever_calls = []
    def retrieve(query):
        retriever_calls.append(query)
        return ["guide"]
    data.update(previous_pairs=[old],previous_turns=first["turns"])
    pair = InterviewAnalysisGraph(Model(),retrieve=retrieve).graph.invoke({"snapshot":data})["result"]["pairs"][0]
    assert len(retriever_calls) == 1 and pair["reference_ids"] == ["guide"]
    assert pair["score"]["percentage"] == 100


@pytest.mark.parametrize("text",["explain or introduce yourself in short","Please introduce yourself.","Could you briefly introduce yourself?","Tell me about yourself."])
def test_generic_introductions_are_housekeeping_without_model_calls(text):
    assert pure_housekeeping(text)
    model = Model()
    result = execute(snapshot([segment(1,"INTERVIEWER",text),segment(2,"CANDIDATE","I am a frontend developer.")]),model)
    assert not result["pairs"] and not model.calls


@pytest.mark.parametrize("text",["Introduce yourself and explain React effects.","Tell me about yourself and a difficult bug you solved.","Describe your experience with React."])
def test_explicit_competency_questions_are_not_excluded_as_introductions(text):
    assert not pure_housekeeping(text)


def test_historical_introduction_is_excluded_without_rewriting_saved_sources():
    items=[segment(1,"INTERVIEWER","explain or introduce yourself"),segment(2,"INTERVIEWER","in short"),segment(3,"CANDIDATE","I am a frontend developer.")]
    result={"pairs":[{"id":"intro","state":"analysis_failed","excluded":False,"question_ids":[items[0]["id"],items[1]["id"]],"answer_ids":[items[2]["id"]],"context_ids":[]}],"unpaired":[],"turns":[]}
    original=copy.deepcopy(result)
    shown=present_result(result,snapshot(items))
    assert shown["pairs"][0]["excluded"] and shown["score_summary"]["question_count"] == 0
    assert original == result
