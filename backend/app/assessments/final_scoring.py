"""Exact, repeatable final scores. The model never chooses weights or ranks."""
from decimal import Decimal, localcontext
from fractions import Fraction
import json
import copy
from app.agents.interview_analysis import score_pair

FORMULA_VERSION = "cv50-interview50-v1"
POLICY = "Final score = 50% CV score + 50% interview score. The interview score is the average of the scored questions."
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


def score_summary(report, source):
    cv = report.get("cv")
    result = {"formula_version": FORMULA_VERSION, "cv_weight": 50, "interview_weight": 50,
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
                    if value and not dimension.get("support_validated"): raise ValueError()
                    if value and name in {"accuracy", "completeness"} and not any(
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
    final = (cv_value(cv) + interview_score) / 2
    result.update(interview_score=decimal(interview_score), final_score=decimal(final),
        exact_interview_score=exact(interview_score), exact_final_score=exact(final),
        question_count=len(scores), rubric_version=next(iter(rubrics)), ready=True,
        reason="The final score gives equal weight to the CV score and the interview score.")
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
        r["result"]["cv"]["formula_version"], r["result"]["score_summary"]["rubric_version"]) for r in ready}
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
