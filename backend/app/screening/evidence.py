"""Source-owned quotations, explicit rubrics, and evidence-backed date arithmetic."""
import calendar
import re
from datetime import date

RUBRIC_VERSION = "three-outcome-grounded-rubric-v1"
PARSER_VERSION = "pypdf-docx-passages-v1"


def rubric(requirement):
    return {"version": RUBRIC_VERSION,
        "met": "All explicitly requested conditions are demonstrated by relevant cited CV passages.",
        "partially_met": "Relevant evidence demonstrates some, but not all, explicitly requested conditions.",
        "unmet": "No relevant evidence demonstrates the requested conditions, or cited evidence contradicts them.",
        "equivalence": "Recognize equivalent meanings (Django REST services can demonstrate Python web development). Do not replace an explicitly named required technology or qualification with a merely related one.",
        "skill_mentions": "A named skill demonstrates a skills-list claim, not professional use, proficiency, years, or delivery. Require stronger evidence only when the approved criterion requests it; do not invent extra conditions.",
        "applied_skill_partial": "For an applied-skill criterion, concrete hands-on coursework or personal-project practice with the requested technology can be Partially met when the requested professional or production context is missing. A bare skills-list mention is not applied practice. State the demonstrated part and the missing part; never award Met for missing professional/production experience.",
        "degree_level": "An explicitly required degree level must itself be demonstrated; a lower degree or course is not partial proof of that degree. Only use allowed equivalences."}


def owned_evidence(ids, blocks):
    by_id = {b["id"]: b for b in blocks}
    evidence = []
    for key in dict.fromkeys(ids):
        if key not in by_id: raise ValueError("An evidence passage ID is not in this candidate's CV")
        block = by_id[key]
        evidence.append({"block_id": key, "quote": block["text"], "char_start": 0, "char_end": len(block["text"])})
    return evidence


def plain_skill_claim(requirement, blocks):
    """A narrow literal policy, not a keyword/proficiency or semantic score.

    Only exact entries in labelled skills lists, with no extra JD conditions.
    Negated/contradictory claims are left to semantic evaluation.
    """
    if requirement["category"] not in {"required_skill", "preferred_skill"} or (requirement.get("details") or "").strip():
        return None
    name = requirement["name"].strip()
    # Multiword criteria can encode proficiency/context; leave them to semantics.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+#/-]{0,39}", name):
        return None
    combined = "\n".join(b["text"] for b in blocks)
    negative = rf"\b(?:no|not|never|without)\b[^\n.!?]{{0,60}}(?<!\w){re.escape(name)}(?!\w)"
    if re.search(negative, combined, re.I):
        return None
    heading = r"(?im)^[ \t]*(?:technical[ \t]+)?(?:skills|technologies|languages|tools|frameworks)[ \t]*:[ \t]*([^\n]+)"
    for block in blocks:
        for match in re.finditer(heading, block["text"]):
            entries = [term.strip().rstrip(".").casefold() for term in re.split(r"[,;|]", match[1])]
            if name.casefold() in entries:
                return {"status": "met", "explanation": f"The CV explicitly lists {name}. This criterion asks for the skill, not professional use or proficiency.",
                    "evidence": owned_evidence([block["id"]], blocks), "evidence_gaps": [], "decision_rule": "plain-skills-list-claim-v1"}
    return None


def month_number(value):
    match = re.fullmatch(r"(19\d{2}|20\d{2})-(0[1-9]|1[0-2])", value or "")
    return int(match[1]) * 12 + int(match[2]) - 1 if match else None


def date_is_in_source(value, text):
    month = month_number(value)
    if month is None: return False
    year, number = value.split("-")
    numeric = rf"(?<!\d)(?:{year}[-/.]0?{int(number)}|0?{int(number)}[-/.]{year})(?!\d)"
    names = (calendar.month_name[int(number)], calendar.month_abbr[int(number)])
    named = rf"\b(?:{'|'.join(names)})\.?[\s,\-]+{year}\b"
    return bool(re.search(numeric, text) or re.search(named, text, re.I))


def source_date_bound(value, text, *, start):
    if date_is_in_source(value, text): return month_number(value), False
    year = re.match(r"^(19\d{2}|20\d{2})(?:-\d{2})?$", value or "")
    if year and re.search(rf"\b{year[1]}\b", text):
        # Only count intervening complete years when the CV omits the month.
        return int(year[1]) * 12 + (12 if start else -1), True
    return None, False


def apply_experience(match, requirement, profile, blocks, selected_roles, as_of):
    if requirement["category"] != "experience": return match
    minimum = re.search(r"At least (\d+(?:\.\d+)?) years", requirement["name"])
    if not minimum: raise ValueError("The minimum experience criterion is not supported by the scoring rules")
    minimum = float(minimum[1])
    roles = profile.get("employment", [])
    by_id = {b["id"]: b for b in blocks}
    months, cited, gaps = set(), [], []
    current = as_of.year * 12 + as_of.month - 1
    for index in dict.fromkeys(selected_roles):
        if index < 0 or index >= len(roles): raise ValueError("The selected employment record does not exist")
        role = roles[index]
        ids = role.get("evidence_block_ids", [])
        if not ids or any(i not in by_id for i in ids): raise ValueError("Employment dates have no source CV evidence")
        text = "\n".join(by_id[i]["text"] for i in ids)
        # This must overlap a selected passage; the independent audit checks role relevance.
        if not set(ids) & {e["block_id"] for e in match["evidence"]}:
            raise ValueError("Relevant employment was not connected to the selected evidence")
        cited.extend(ids)
        start, coarse_start = source_date_bound(role.get("start_date"), text, start=True)
        end, coarse_end = (current - 1, False) if role.get("is_current") else source_date_bound(role.get("end_date"), text, start=False)
        current_proven = bool(re.search(r"\b(present|current|ongoing|now)\b", text, re.I))
        if start is None or end is None or (role.get("is_current") and not current_proven):
            gaps.append("Some relevant employment dates are incomplete; no precise duration was assumed.")
            continue
        if coarse_start or coarse_end:
            gaps.append("Year-only dates were assessed using a conservative minimum; no missing month was invented.")
        end = min(end, current - 1)
        if start > end:
            gaps.append("A future or reversed employment date range was not counted.")
            continue
        months.update(range(start, end + 1))
    threshold = minimum * 12
    status = "met" if len(months) >= threshold else "partially_met" if cited else "unmet"
    years = round(len(months) / 12, 2)
    explanation = f"The CV demonstrates {years:g} years of dated relevant employment against a {minimum:g}-year requirement. Overlapping months count once."
    if not selected_roles: explanation = "Relevant employment was not demonstrated in this CV."
    if minimum == 0: explanation = "This role has no minimum experience requirement."
    return {**match, "status": status, "explanation": explanation,
        "evidence_gaps": list(dict.fromkeys(gaps + ([] if status == "met" else ["The full minimum relevant experience was not demonstrated."]))),
        "experience_calculation": {"months": len(months), "as_of": as_of.isoformat(), "relevant_roles": selected_roles}}
