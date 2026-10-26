"""Synthetic text only. Scope exclusions never use an external provider."""
import copy
import pytest
from app.agents.interview_scope import pure_housekeeping, apply_scoring_scope
from app.agents.interview_analysis import pair_turns, present_result
from test_interview_analysis import segment, snapshot, classify, execute, Model


@pytest.mark.parametrize("text", [
    "Hello, Ashok. Can you hear me clearly?", "Hello Ashok can you hear me clearly?",
    "Can you hear me?", "How are you doing today?", "What is your name?",
    "Please turn on your camera.", "Are you ready to start the interview?",
    "Did you find the interview link easily?", "Thank you for your time.",
])
def test_clear_housekeeping_is_not_a_competency_question(text):
    assert pure_housekeeping(text)


@pytest.mark.parametrize("text", [
    "Hello, Ashok. Explain database transactions.",
    "Can you explain how an audio processing API works?",
    "How would you build a microphone permission check in React?",
    "How would you structure a recruitment interview?",
    "How do you handle a sales objection?",
    "Hello. Can you hear me? Explain transaction rollback.",
])
def test_mixed_or_job_related_questions_are_not_removed_by_keywords(text):
    assert not pure_housekeeping(text)


def test_misclassified_split_audio_check_and_reply_do_not_enter_scoring():
    items = [segment(1, "INTERVIEWER", "Hello Ashok. Can you"), segment(2, "INTERVIEWER", "hear me clearly?"),
        segment(3, "CANDIDATE", "Yes. I can hear you."), segment(4, "INTERVIEWER", "Explain transactions"),
        segment(5, "CANDIDATE", "Transactions are atomic.")]
    pairs, other = pair_turns(items, classify(items, ["question", "question_continuation", "answer", "question", "answer"]), complete=True)
    assert len(pairs) == 1 and pairs[0]["question_ids"] == [items[3]["id"]]
    assert pairs[0]["answer_ids"] == [items[4]["id"]]
    assert {item["segment_id"] for item in other} == {s["id"] for s in items[:3]}


def test_audio_check_during_an_answer_does_not_lose_the_job_related_continuation():
    items = [segment(1, "INTERVIEWER", "Explain transactions"), segment(2, "CANDIDATE", "Transactions are atomic."),
        segment(3, "INTERVIEWER", "Can you hear me clearly?"), segment(4, "CANDIDATE", "Yes. I can hear you."),
        segment(5, "CANDIDATE", "A rollback discards incomplete changes.")]
    pairs, other = pair_turns(items, classify(items, ["question", "answer", "question", "answer", "answer"]), complete=True)
    assert len(pairs) == 1 and pairs[0]["answer_ids"] == [items[1]["id"], items[4]["id"]]
    assert {item["segment_id"] for item in other} == {items[2]["id"], items[3]["id"]}


def test_only_greetings_and_device_checks_use_no_model_or_score_calls():
    model = Model()
    data = snapshot([segment(1, "INTERVIEWER", "Hello Ashok. Can you hear me clearly?"), segment(2, "CANDIDATE", "Yes. I can hear you.")])
    result = execute(data, model)
    assert not result["pairs"] and len(result["unpaired"]) == 2
    assert model.calls == []


def test_semantic_scope_excludes_non_job_questions_but_keeps_hr_competencies():
    items = [segment(1, "INTERVIEWER", "What did you have for breakfast?"), segment(2, "CANDIDATE", "Toast."),
        segment(3, "INTERVIEWER", "How would you structure a recruitment interview?"), segment(4, "CANDIDATE", "I use role-related questions and consistent evaluation criteria.")]
    turns = classify(items, ["question", "answer", "question", "answer"])
    turns[0]["scoring_scope"] = "non_assessment"
    turns[1]["scoring_scope"] = "non_assessment"
    turns[2]["scoring_scope"] = "job_related"
    pairs, other = pair_turns(items, turns, complete=True)
    assert len(pairs) == 1 and pairs[0]["question_ids"] == [items[2]["id"]]
    assert len(other) == 2


def test_candidate_small_talk_instead_of_a_job_answer_is_not_silently_excluded():
    items = [segment(1, "INTERVIEWER", "Explain transactions"), segment(2, "CANDIDATE", "Hello. How are you?")]
    turns = classify(items, ["question", "answer"])
    turns[1]["scoring_scope"] = "non_assessment"
    pairs, _ = pair_turns(items, turns, complete=True)
    assert len(pairs) == 1 and not pairs[0]["excluded"] and pairs[0]["answer_ids"] == [items[1]["id"]]


def test_old_failed_audio_check_is_excluded_from_read_only_score_summary():
    items = [segment(1, "INTERVIEWER", "Explain transactions"), segment(2, "CANDIDATE", "Transactions are atomic.")]
    data = snapshot(items)
    result = execute(data)
    q, a = segment(3, "INTERVIEWER", "Hello Ashok. Can you hear me clearly?"), segment(4, "CANDIDATE", "Yes. I can hear you.")
    data["segments"].extend([q, a])
    result["pairs"].insert(0, {"id": "old-audio-check", "state": "analysis_failed", "excluded": False,
        "question_ids": [q["id"]], "answer_ids": [a["id"]], "context_ids": [], "analysis_error": "Old scoring failure"})
    before = copy.deepcopy(result)
    displayed = present_result(result, data)
    assert displayed["score_summary"]["ready"] and displayed["score_summary"]["question_count"] == 1
    assert displayed["pairs"][0]["excluded"] and displayed["score_summary"]["percentage"] == 100
    assert len(displayed["unpaired"]) == 2 and result == before
    assert apply_scoring_scope(displayed, data) == displayed
