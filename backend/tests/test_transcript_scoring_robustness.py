"""Repeatability, ASR interpretation and provenance regressions. No live provider calls."""
import copy
import json
import pytest
from app.agents.interview_analysis import InterviewAnalysisGraph, digest, present_result
from app.agents.interview_summary import evidence_summary
from app.schemas.interview_analysis import StartAnalysis
from test_interview_analysis import Model, execute, segment, snapshot, saved  # noqa: F401
from test_transcription import transcription  # noqa: F401
from test_interview_rooms import room_setup  # noqa: F401
from test_interviews import setup, records  # noqa: F401


def source():
    return snapshot([segment(1, "INTERVIEWER", "Explain transactions"),
                     segment(2, "CANDIDATE", "Um, transactions are a tomic. All writes commit together.", confidence=.4)])


def incremental(data, result):
    return {**copy.deepcopy(data), "previous_turns": copy.deepcopy(result["turns"]),
            "previous_pairs": copy.deepcopy(result["pairs"]), "reanalyze": True}


def test_explicit_reanalysis_preserves_accepted_labels_scores_and_retrieval_without_provider_calls():
    data = source()
    data["references"][0]["source"] = "knowledge_base"
    graph = InterviewAnalysisGraph(Model(), retrieve=lambda q: ["guide"])
    first = graph.graph.invoke({"snapshot": data})["result"]
    model = Model(fail=True)  # Even a different/failed provider cannot reroll accepted evidence.
    def forbidden(q): raise AssertionError("Accepted guide selection must be frozen")
    second = InterviewAnalysisGraph(model, retrieve=forbidden).graph.invoke({"snapshot": incremental(data, first)})["result"]
    assert model.calls == []
    assert second["pairs"][0]["assessment"] == first["pairs"][0]["assessment"]
    assert second["pairs"][0]["score"] == first["pairs"][0]["score"]
    assert second["pairs"][0]["reference_ids"] == ["guide"]
    assert second["pairs"][0]["reused"]


@pytest.mark.parametrize("change", ["transcript", "reference", "rubric", "model", "requirements", "configuration"])
def test_changed_scoring_inputs_invalidate_the_pair_cache(change):
    data = source()
    previous = execute(data)
    new = incremental(data, previous)
    if change == "transcript":
        new["segments"][1]["text"] = "Transactions keep partial writes."
        new["segments"][1]["hash"] = digest(new["segments"][1])
    elif change == "reference": new["references"][0]["version"] = "new-version"
    elif change == "rubric": new["rubric_version"] = "new-rubric"
    elif change == "model": new["model"] = "new-model"
    elif change == "requirements": new["requirements"]["requirements"][0]["name"] = "New requirement"
    else: new["configuration"] = {"policy": "new"}
    model = Model()
    execute(new, model)
    assert sum(title == "Assessment" for title, _, _ in model.calls) == 1


@pytest.mark.parametrize("malformed", ["exception", "duplicate", "missing", "unknown"])
def test_failed_or_incomplete_audits_never_produce_candidate_zeros(malformed):
    class BrokenAudit(Model):
        def generate_json(self, **kwargs):
            if kwargs["schema"]["title"] != "SupportCheck": return super().generate_json(**kwargs)
            if malformed == "exception": raise RuntimeError("Private provider failure")
            result = super().generate_json(**kwargs)
            if malformed == "duplicate": result["findings"][-1] = result["findings"][0]
            if malformed == "missing": result["findings"].pop()
            if malformed == "unknown": result["findings"][-1]["target"] = "invented"
            return result
    result = execute(source(), BrokenAudit())
    pair = result["pairs"][0]
    assert pair["state"] == "analysis_failed" and "score" not in pair
    assert "Private" not in json.dumps(result)
    assert not result["evidence_summary"]["weaknesses"]
    repaired = execute(incremental(source(), result))
    assert repaired["pairs"][0]["score"]["percentage"] == 100


def test_context_supported_asr_interpretation_scores_meaning_but_preserves_original_words():
    class ASRModel(Model):
        def generate_json(self, **kwargs):
            result = super().generate_json(**kwargs)
            if kwargs["schema"]["title"] == "Assessment":
                data = json.loads(kwargs["prompt"])
                candidate = next(s for s in data["transcript"] if s["speaker"] == "CANDIDATE")
                result["interpretation"].update(status="context_supported", meaning="Transactions are atomic; all writes commit together.", notes=[{
                    "original": {"segment_id": candidate["id"], "quote": "a tomic"}, "interpreted_as": "atomic",
                    "reason": "The adjacent explanation of all writes committing together supports this term.",
                    "context": [{"segment_id": candidate["id"], "quote": "All writes commit together."}]}])
            return result
    data = source()
    original = copy.deepcopy(data)
    result = execute(data, ASRModel())
    pair = result["pairs"][0]
    assert pair["score"]["percentage"] == 100  # Low confidence / fillers alone do not reduce credit.
    note = pair["assessment"]["interpretation"]["notes"][0]
    assert note["original"]["quote"] == "a tomic" and note["original"]["revision"] == data["segments"][1]["hash"]
    assert note["context"][0]["quote"] == "All writes commit together."
    assert data == original
    assert result["evidence_summary"]["verification"][0]["rule"] == "contextual_transcription_interpretation"


@pytest.mark.parametrize("problem", ["ambiguous_negation", "fabricated_repair_quote", "no_context", "audit_rejected"])
def test_ambiguous_or_unsupported_repairs_stay_unscored_and_are_not_weaknesses(problem):
    class AmbiguousModel(Model):
        def generate_json(self, **kwargs):
            result = super().generate_json(**kwargs)
            if kwargs["schema"]["title"] == "Assessment":
                if problem == "ambiguous_negation":
                    result["interpretation"].update(status="uncertain", meaning="The negation may have been lost.")
                elif problem in {"fabricated_repair_quote", "no_context"}:
                    quote = result["interpretation"]["citations"][0]
                    result["interpretation"].update(status="context_supported", notes=[] if problem == "no_context" else [{
                        "original": {**quote, "quote": "Words not actually captured"},
                        "interpreted_as": "atomic", "reason": "Looks like ASR.", "context": [quote]}])
            if kwargs["schema"]["title"] == "SupportCheck" and problem == "audit_rejected":
                for check in result["findings"]:
                    if check["target"] == "interpretation": check["supported"] = False
            return result
    data = source()
    data["segments"][1] = segment(2, "CANDIDATE", "All writes do [unclear] commit together.")
    result = execute(data, AmbiguousModel())
    pair = result["pairs"][0]
    assert pair["state"] == "needs_clarification" and "score" not in pair
    assert not result["evidence_summary"]["weaknesses"] and not result["evidence_summary"]["strengths"]
    assert result["evidence_summary"]["verification"]
    assert all(m["status"] == "insufficient_evidence" for m in pair["mappings"])


def test_mapping_failure_can_be_retried_without_regrading_validated_dimensions():
    class FailingMapping(Model):
        def generate_json(self, **kwargs):
            if kwargs["schema"]["title"] == "Mappings": raise RuntimeError("Synthetic failure")
            return super().generate_json(**kwargs)
    data = source()
    first = execute(data, FailingMapping())
    assert first["pairs"][0]["score"]["percentage"] == 100
    model = Model()
    second = execute(incremental(data, first), model)
    assert second["pairs"][0]["score"] == first["pairs"][0]["score"]
    assert not any(title in {"Assessment", "Detection"} for title, _, _ in model.calls)
    assert second["pairs"][0]["mapping_complete"]


def test_mapping_only_audit_failure_keeps_previously_accepted_score():
    class FailingMapping(Model):
        def generate_json(self, **kwargs):
            if kwargs["schema"]["title"] == "Mappings": raise RuntimeError("Synthetic mapping failure")
            return super().generate_json(**kwargs)
    class FailingAudit(Model):
        def generate_json(self, **kwargs):
            if kwargs["schema"]["title"] == "SupportCheck": raise RuntimeError("Synthetic audit failure")
            return super().generate_json(**kwargs)
    data = source()
    first = execute(data, FailingMapping())
    second = execute(incremental(data, first), FailingAudit())
    assert second["pairs"][0]["score"] == first["pairs"][0]["score"]
    assert not second["pairs"][0]["mapping_complete"]
    assert second["pairs"][0]["analysis_error"]


def test_question_side_asr_repair_can_cite_original_question_without_rewriting_it():
    class QuestionRepair(Model):
        def generate_json(self, **kwargs):
            result = super().generate_json(**kwargs)
            if kwargs["schema"]["title"] == "Assessment":
                data = json.loads(kwargs["prompt"])
                question = next(s for s in data["transcript"] if s["speaker"] == "INTERVIEWER")
                candidate = next(s for s in data["transcript"] if s["speaker"] == "CANDIDATE")
                result["interpretation"].update(status="context_supported", notes=[{
                    "original": {"segment_id": question["id"], "quote": "a tomic"}, "interpreted_as": "atomic",
                    "reason": "The rest of the exchange concerns atomic database transactions.",
                    "context": [{"segment_id": candidate["id"], "quote": candidate["text"]}]}])
            return result
    data = source()
    data["segments"][0] = segment(1, "INTERVIEWER", "Explain a tomic transactions")
    pair = execute(data, QuestionRepair())["pairs"][0]
    assert pair["score"]["percentage"] == 100
    assert pair["assessment"]["interpretation"]["notes"][0]["original"]["speaker"] == "INTERVIEWER"
    assert data["segments"][0]["text"] == "Explain a tomic transactions"


def test_rejected_dimension_does_not_invent_a_weakness_or_numeric_score():
    class RejectOne(Model):
        def generate_json(self, **kwargs):
            result = super().generate_json(**kwargs)
            if kwargs["schema"]["title"] == "SupportCheck":
                next(c for c in result["findings"] if c["target"] == "accuracy")["supported"] = False
            return result
    result = execute(source(), RejectOne())
    assert result["pairs"][0]["state"] == "analysis_failed" and "score" not in result["pairs"][0]
    assert result["evidence_summary"]["weaknesses"] == []


def test_traceable_weaknesses_require_supported_negative_labels_and_exact_sources():
    class Partial(Model):
        def generate_json(self, **kwargs):
            result = super().generate_json(**kwargs)
            if kwargs["schema"]["title"] == "Assessment":
                result["completeness"]["label"] = "partial"
                result["completeness"]["justification"] = "Only one requested part was explained."
            return result
    data = source()
    result = execute(data, Partial())
    assert result["pairs"][0]["score"]["percentage"] == 87.5
    for category in ("strengths", "weaknesses"):
        assert result["evidence_summary"][category]
        for finding in result["evidence_summary"][category]:
            assert finding["citations"]
            for cite in finding["citations"]:
                original = next(s for s in data["segments"] if s["id"] == cite["segment_id"])
                assert original["hash"] == cite["revision"]
                assert original["text"][cite["char_start"]:cite["char_end"]] == cite["quote"]
    corrupted = copy.deepcopy(result)
    for pair in corrupted["pairs"]:
        for name in ("relevance", "accuracy", "completeness", "quality"):
            pair["assessment"][name]["citations"][0]["revision"] = "not-current"
    checked = evidence_summary(corrupted, data)
    assert checked["strengths"] == checked["weaknesses"] == []


def test_model_revision_drift_aborts_instead_of_mixing_scoring_judgments():
    class Drifting(Model):
        def generate_json(self, **kwargs):
            value = super().generate_json(**kwargs)
            self.last_model_version = "v1" if len(self.calls) == 1 else "v2"
            return value
    with pytest.raises(RuntimeError, match="revision changed"):
        execute(source(), Drifting())


def test_service_reanalysis_retains_accepted_exchange_and_turn_cache(saved):
    from app.schemas.interview_analysis import ReferenceUpdate
    t = saved
    t.analysis.references(t.db, t.owner.id, t.row.id, ReferenceUpdate(revision=0, approved=True, references=[{
        "id": "guide", "title": "Database transactions", "kind": "answer_guide", "content": "Transactions are atomic."}]))
    first = t.analysis.enqueue(t.db, t.owner.id, t.row.id, StartAnalysis())
    t.analysis.process(first.id)
    t.db.expire_all()
    before = t.analysis.read(t.db, t.owner.id, t.row.id)["run"]
    second = t.analysis.enqueue(t.db, t.owner.id, t.row.id, StartAnalysis(reanalyze=True))
    t.analysis.model = Model(fail=True)
    t.analysis.process(second.id)
    t.db.expire_all()
    after = t.analysis.read(t.db, t.owner.id, t.row.id)["run"]
    assert after["status"] == "completed" and after["id"] != before["id"]
    assert after["result"]["pairs"][0]["score"] == before["result"]["pairs"][0]["score"]
    assert not t.analysis.model.calls
    assert after["result"]["evidence_summary"]["strengths"]
