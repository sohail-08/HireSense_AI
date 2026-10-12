"""Pure, evidence-grounded calculations. No database, AI, clocks, or randomness."""

from collections import Counter
from decimal import Decimal, ROUND_HALF_UP, localcontext
from fractions import Fraction


FORMULA_VERSION = "category-weighted-coverage-v4"
SNAPSHOT_VERSION = "scoring-snapshot-v4"
CATEGORIES = ("technical", "experience", "qualification")
STATUS_VALUES = {"met": "1", "partially_met": "0.5", "unmet": "0"}
DEFAULT_CATEGORY_WEIGHTS = {"technical": "50", "experience": "30", "qualification": "20"}


def decimal_text(value: Fraction) -> str:
    # Persist 28 significant decimal digits; do not round to a display percentage.
    with localcontext() as context:
        context.prec = 28
        return format(Decimal(value.numerator) / Decimal(value.denominator), "f")


def display_score(value: str | None) -> str:
    if value is None:
        return "not applicable"
    with localcontext() as context:
        context.prec = 50
        return str(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def rational(value: Fraction) -> dict[str, str]:
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def category_scores(configuration: dict, application: dict) -> dict:
    weights = configuration["category_weights"]
    if set(weights) != set(CATEGORIES):
        raise ValueError("All three category weights are required")
    decimals = [Decimal(weights[category]) for category in CATEGORIES]
    if any(not value.is_finite() or value < 0 for value in decimals) or sum(decimals) != 100:
        raise ValueError("Category weights must be non-negative and total 100")
    for requirement in configuration["requirements"]:
        weight = Decimal(requirement["weight"])
        if not weight.is_finite() or weight < 0:
            raise ValueError("Requirement weights must be finite and non-negative")
    block_map = {block["id"]: block for block in application.get("source_blocks", [])}
    matches = {match["requirement_key"]: match for match in application.get("matches", [])}
    duplicates = {key for key, count in Counter(match["requirement_key"] for match in application.get("matches", [])).items() if count > 1}
    screening_complete = application.get("screening_status") == "completed"
    flags = list(application.get("review_flags", []))
    if not block_map:
        flags.append("No saved CV source blocks are available for evidence verification")
    if len(matches) != len(application.get("matches", [])):
        flags.append("Duplicate saved requirement outcomes receive no credit")
    if not screening_complete:
        flags.append(application.get("error_message") or "Screening is not complete for these requirements and CV.")
    items = []
    for requirement in configuration["requirements"]:
        match = matches.get(requirement["requirement_id"])
        status = match.get("status") if match else "unmet"
        if status not in STATUS_VALUES:
            status = "unmet"
        evidence = []
        for citation in (match or {}).get("evidence", []):
            block = block_map.get(citation.get("block_id"))
            quote = citation.get("quote", "").strip()
            if block and quote and quote in block["text"]:
                evidence.append({"block_id": block["id"], "locator": block["locator"], "quote": quote})
            else:
                flags.append(f"{requirement['requirement_id']}: unsupported saved quotation")
        if match:
            flags.extend(match.get("review_flags", []))
        flagged_requirement = bool((match or {}).get("review_flags")) or any(
            flag.startswith(requirement["requirement_id"] + ":") for flag in application.get("review_flags", []))
        if status in {"met", "partially_met"} and (not evidence or flagged_requirement):
            status = "unmet"
            flags.append(f"{requirement['requirement_id']}: positive match lacks accepted evidence; zero credit applied")
        if not screening_complete or requirement["requirement_id"] in duplicates:
            status = "unmet"
            evidence = []
        weight = Fraction(requirement["weight"])
        match_value = Fraction(STATUS_VALUES[status])
        scored = requirement["category"] in CATEGORIES
        items.append({
            **requirement, "status": status, "match_value": str(STATUS_VALUES[status]),
            "score_included": scored,
            "weighted_contribution": decimal_text(weight * match_value) if scored else "0",
            "evidence": evidence, "evidence_gaps": (match or {}).get("evidence_gaps", []),
        })
    categories = {}
    for category in CATEGORIES:
        members = [item for item in items if item["category"] == category]
        denominator = sum((Fraction(item["weight"]) for item in members), Fraction(0))
        numerator = sum((Fraction(item["weight"]) * Fraction(item["match_value"]) for item in members), Fraction(0))
        score = numerator / denominator * 100 if denominator else None
        if score is None and Fraction(configuration["category_weights"][category]) > 0:
            raise ValueError(f"{category} has no positive requirement weights; approve a zero category weight and redistribute it")
        categories[category] = {
            "score": decimal_text(score) if score is not None else None,
            "exact_score": rational(score) if score is not None else None,
            "total_requirement_weight": decimal_text(denominator),
            "earned_requirement_weight": decimal_text(numerator),
            "category_weight": configuration["category_weights"][category],
        }
    counts = {status: Counter(item["status"] for item in items)[status] for status in STATUS_VALUES}
    required_gaps = [item["requirement_id"] for item in items if item["classification"] == "required" and item["status"] != "met"]
    return {"categories": categories, "requirements": items, "counts": counts, "required_gaps": required_gaps, "review_flags": sorted(set(flags))}


def weighted_score(configuration: dict, breakdown: dict) -> dict:
    numerator = Fraction(0)
    denominator = Fraction(0)
    for category, result in breakdown["categories"].items():
        weight = Fraction(configuration["category_weights"][category])
        if weight and result["exact_score"] is not None:
            exact = result["exact_score"]
            numerator += Fraction(int(exact["numerator"]), int(exact["denominator"])) * weight
        denominator += weight
    if denominator != 100:
        raise ValueError("Approved category weights must total 100")
    score = numerator / denominator
    return {**breakdown, "final_score": decimal_text(score), "exact_final_score": rational(score),
            "formula_version": FORMULA_VERSION, "requirement_version": configuration["requirement_version"],
            "review_state": "ranked"}


def justification(breakdown: dict) -> str:
    lines = ["Job-requirement coverage, not a prediction of hiring success."]
    labels = {"technical": "Technical skills", "experience": "Experience", "qualification": "Qualifications"}
    for category, label in labels.items():
        score = breakdown["categories"][category]
        lines.append(f"{label}: {display_score(score['score'])}{'%' if score['score'] is not None else ''}; approved category weight {score['category_weight']}%.")
        members = sorted((item for item in breakdown["requirements"] if item["category"] == category),
                         key=lambda item: (-Fraction(item["weighted_contribution"]), item["requirement_id"]))
        for item in members:
            # Do not repeat free-form AI explanations or extracted claims. Only
            # approved criteria, saved statuses, and reverified source quotations.
            lines.append(f"[{item['requirement_id']}] Criterion: {item['evaluation_criterion']}. "
                         f"Outcome: {item['status'].replace('_', ' ')}; {item['classification']}; "
                         f"weight {item['weight']} × value {item['match_value']} = {item['weighted_contribution']}.")
            for evidence in item["evidence"]:
                lines.append(f"Evidence [{evidence['block_id']}], {evidence['locator']}: “{evidence['quote']}”")
            if item["status"] == "unmet":
                lines.append("Not evidenced in this CV; this does not establish that the candidate lacks the capability.")
            if item["status"] == "partially_met":
                lines.append("The criterion is partially demonstrated; partial credit is applied.")
    evidence_only = [item for item in breakdown["requirements"] if item["category"] not in CATEGORIES]
    if evidence_only:
        lines.append("Evidence-only selection criteria: excluded from all category scores and the final percentage.")
        for item in evidence_only:
            lines.append(f"[{item['requirement_id']}] Criterion: {item['evaluation_criterion']}. Outcome: {item['status'].replace('_', ' ')}. No numeric contribution.")
            for evidence in item["evidence"]:
                lines.append(f"Evidence [{evidence['block_id']}], {evidence['locator']}: “{evidence['quote']}”")
    lines.append(f"Weighted coverage = Σ(category score × approved category weight) / 100 = {display_score(breakdown['final_score'])}%.")
    if breakdown["required_gaps"]:
        lines.append("Required criteria not fully evidenced: " + ", ".join(breakdown["required_gaps"]) + ". No automatic disqualification rule is applied.")
    if breakdown["review_flags"]:
        lines.append("Processing/evidence diagnostics are retained for transparency; no manual review is required. Unsupported outcomes receive zero credit.")
    return "\n".join(lines)


def assign_ranks(results: list[dict]) -> list[dict]:
    def exact(result):
        value = result["breakdown"]["exact_final_score"]
        return Fraction(int(value["numerator"]), int(value["denominator"]))
    ordered = sorted(results, key=lambda result: (-exact(result), result["application_id"]))
    previous, rank, position = None, None, 0
    for result in ordered:
        position += 1
        score = exact(result)
        rank = rank if score == previous else position
        result["rank"] = rank
        previous = score
    return ordered
