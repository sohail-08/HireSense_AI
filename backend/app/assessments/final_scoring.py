"""Exact, repeatable final scores. The model never chooses weights or ranks."""
from decimal import Decimal, localcontext
from fractions import Fraction
import json
import copy
from app.agents.interview_analysis import score_pair
from app.agents.practical_scoring import POLICY as PRACTICAL_POLICY, result_hash

FORMULA_VERSION = "cv30-interview60-practical10-llm-v4"
CV_WEIGHT = 30
INTERVIEW_WEIGHT = 60
PRACTICAL_WEIGHT = 10
POLICY = f"Final score = {INTERVIEW_WEIGHT}% interview + {CV_WEIGHT}% CV + {PRACTICAL_WEIGHT}% practical task. The LLM scores practical correctness; the interviewer approves that score."
DIMENSIONS = ("relevance", "accuracy", "completeness", "quality")


def decimal(value):
    with localcontext() as ctx:
        ctx.prec = 60
        return format(Decimal(value.numerator) / Decimal(value.denominator), "f")


def exact(value):
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def cv_value(cv):
    saved = (cv.get("breakdown") or {}).get("exact_final_score")
    value = Fraction(int(saved["numerator"]), int(saved["denominator"])) if saved else Fraction(cv["final_score"])
    if not 0 <= value <= 100: raise ValueError("Invalid CV score")
    return value


def practical_value(report, source):
    interviews = source.get("interviews", [])
    if not interviews:
        return None
    selected = max(interviews, key=lambda i: (i.get("date", ""), i["id"]))["id"]
    entries = [p for p in source.get("practical_assessments", []) if p["interview_id"] == selected]
    if len(entries) != 1:
        return None
    entry = entries[0]
    decision = entry.get("assessment") or {}
    if (entry.get("review_status") != "reviewed" or decision.get("policy") != PRACTICAL_POLICY
        or decision.get("verified") is not True or not decision.get("assessment_id")
        or decision.get("submission_hash") != entry.get("submission_hash")
        or decision.get("task_hash") != entry.get("task_hash")
        or decision.get("exercise_id") != entry.get("exercise_id") or not decision.get("approved_by") or not decision.get("approved_at")):
        return None
    score = decision.get("score")
    if type(score) is not int or not 0 <= score <= 100 or entry not in report.get("practical_assessments", []):
        return None
    fields = ("score", "summary", "evidence", "verified", "verification_reason", "limitation")
    if not all(key in decision for key in (*fields, "model", "prompt_version")):
        return None
    if decision.get("result_hash") != result_hash(decision, {key: decision[key] for key in fields}):
        return None
    return Fraction(score)


def score_summary(report, source):
    cv = report.get("cv")
    practical = practical_value(report, source)
    result = {"formula_version": FORMULA_VERSION, "cv_weight": CV_WEIGHT, "interview_weight": INTERVIEW_WEIGHT, "practical_weight": PRACTICAL_WEIGHT,
        "practical_score": decimal(practical) if practical is not None else None,
        "cv_score": cv.get("final_score") if cv else None, "interview_score": None, "final_score": None,
        "question_count": 0, "unanswered_count": 0, "ready": False, "reason": "Interview not scored yet", "policy": POLICY}
    if not cv or cv.get("final_score") is None or not cv.get("compatible"):
        result["reason"] = "Rank this candidate's CV in Assessments first."
        return result
    interviews = source.get("interviews", [])
    if not interviews: return result
    displayed = {i["id"]: i for i in report["interviews"]}
    scores, rubrics = [], set()
    for interview in interviews:
        analysis = interview.get("analysis")
        if not interview.get("finalized") or not analysis or analysis.get("status", "completed") != "completed" or not analysis.get("result", {}).get("reconciled"):
            return result
        if analysis.get("requirement_version") != report["identification"]["requirement_version"]:
            result["reason"] = "The interview used older job requirements. Score the answers for the current job requirements first."
            return result
        if analysis.get("snapshot", {}).get("watermark") != {k: v["hash"] for k, v in interview.get("segments", {}).items()}:
            result["reason"] = "Score the latest saved transcript before calculating the final score."
            return result
        saved_pairs = [p for p in analysis["result"].get("pairs", []) if not p.get("excluded") and p.get("state") != "excluded"]
        verified_pairs = {p["id"]: p for p in displayed.get(interview["id"], {}).get("pairs", [])}
        for pair in saved_pairs:
            verified, saved = verified_pairs.get(pair["id"]), pair.get("score")
            if not verified or not saved or pair["state"] not in {"analyzed", "unanswered"}:
                result["reason"] = "Some interview answers have not been scored yet."
                return result
            try:
                breakdown = saved["breakdown"]
                if set(breakdown) != set(DIMENSIONS): raise ValueError()
                recomputed = copy.deepcopy(pair)
                score_pair(recomputed)
                expected = recomputed["score"]["breakdown"]
                earned = Fraction(0)
                for name in DIMENSIONS:
                    item = breakdown[name]
                    value, weight = Fraction(str(item["value"])), Fraction(str(item["weight"]))
                    if value not in {Fraction(0), Fraction(1, 2), Fraction(1)} or weight != 25: raise ValueError()
                    if value != Fraction(str(expected[name]["value"])): raise ValueError()
                    dimension = verified["dimensions"].get(name, {})
                    if pair["state"] != "unanswered" and not dimension.get("support_validated"): raise ValueError()
                    if pair["state"] != "unanswered" and name in {"accuracy", "completeness"} and not any(
                        report["evidence"][eid]["kind"] in ({"answer_guide", "technical_reference"} if name == "accuracy" else {"answer_guide"}) for eid in dimension.get("evidence_ids", [])):
                        raise ValueError()
                    earned += value
                if pair["state"] == "unanswered" and earned: raise ValueError()
                percentage = earned / 4 * 100
                if Fraction(str(saved["percentage"])) != percentage: raise ValueError()
                if Fraction(str(saved["earned"])) != earned or Fraction(str(saved["possible"])) != 4: raise ValueError()
                if saved["rubric_version"] != analysis.get("rubric_version"): raise ValueError()
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                result["reason"] = "Score the interview answers again before calculating the final score."
                return result
            scores.append(percentage)
            rubrics.add(saved["rubric_version"])
            result["unanswered_count"] += pair["state"] == "unanswered"
    if not scores: return result
    if len(rubrics) != 1:
        result["reason"] = "Score the interview answers using the same scoring rules first."
        return result
    interview_score = sum(scores, Fraction(0)) / len(scores)
    result.update(interview_score=decimal(interview_score), exact_interview_score=exact(interview_score),
        question_count=len(scores), rubric_version=next(iter(rubrics)))
    if practical is None:
        result["reason"] = "The practical task needs a verified LLM score and interviewer approval before the final score is available."
        return result
    final = (cv_value(cv) * CV_WEIGHT + interview_score * INTERVIEW_WEIGHT + practical * PRACTICAL_WEIGHT) / 100
    result.update(interview_score=decimal(interview_score), final_score=decimal(final),
        exact_interview_score=exact(interview_score), exact_final_score=exact(final),
        question_count=len(scores), rubric_version=next(iter(rubrics)), ready=True,
        reason=f"Final score: interview {INTERVIEW_WEIGHT}% + CV {CV_WEIGHT}% + practical task {PRACTICAL_WEIGHT}%.")
    return result


def simple_summary(report):
    strengths, improvements = [], []
    for row in report.get("matrix", []):
        if "supporting_evidence" in row["interview_statuses"]:
            strengths.append({"text": f"The interview answer showed {row['name']}.", "evidence_ids": [e for m in row["interview_evidence"] for e in m["evidence_ids"]]})
        elif row["cv_status"] == "met" and row["cv_evidence_ids"]:
            strengths.append({"text": f"The CV shows {row['name']}.", "evidence_ids": row["cv_evidence_ids"]})
        if row["cv_status"] in {"unmet", "partially_met"}:
            improvements.append({"text": f"The CV did not fully show {row['name']}.", "evidence_ids": row["cv_evidence_ids"]})
        if "contradictory_evidence" in row["interview_statuses"]:
            improvements.append({"text": f"The answer did not demonstrate {row['name']} clearly.", "evidence_ids": [e for m in row["interview_evidence"] for e in m["evidence_ids"]]})
    return {"strengths": strengths[:3], "improvements": improvements[:3]}


def rank_reports(reports):
    for report in reports:
        report.pop("final_rank", None)
    ready = [r for r in reports if r["result"].get("score_summary", {}).get("ready") and not r.get("stale")]
    signatures = {(r["result"]["identification"]["requirement_version"],
        json.dumps(r["result"]["cv"]["configuration"], sort_keys=True),
        r["result"]["cv"]["formula_version"], r["result"]["score_summary"]["rubric_version"],
        r["result"]["score_summary"].get("formula_version"), r["result"]["score_summary"].get("cv_weight"),
        r["result"]["score_summary"].get("interview_weight"), r["result"]["score_summary"].get("practical_weight")) for r in ready}
    issue = "The candidates used different scoring rules. Rank their CVs and score their interviews using the same rules first." if len(signatures) > 1 else None
    def value(r):
        v = r["result"]["score_summary"]["exact_final_score"]
        return Fraction(int(v["numerator"]), int(v["denominator"]))
    ordered = sorted(ready, key=lambda r: (-value(r), r["application_id"])) if not issue else []
    previous, rank = None, None
    for index, row in enumerate(ordered, 1):
        score = value(row)
        if score != previous: rank = index
        row["final_rank"], previous = rank, score
    included = {r["id"] for r in ordered}
    return ordered + sorted([r for r in reports if r["id"] not in included], key=lambda r: r["application_id"]), issue
