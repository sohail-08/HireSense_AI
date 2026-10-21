"""Read-only evidence previews. Never change saved scores, outcomes or quotations."""
from copy import deepcopy
import re


_STOP = set("a an the and or of in on to for with at least years year relevant experience required minimum demonstrate demonstrated ability using use development skills skill".split())
_DATE = re.compile(r"\b(?:19|20)\d{2}\b")
_ROLE = re.compile(r"\b(?:engineer|developer|scientist|analyst|manager|designer|researcher|consultant|officer|intern|specialist)\b", re.I)
_ACTION = re.compile(r"\b(?:built|developed|delivered|designed|implemented|deployed|maintained|led|managed|created|tested|wrote|integrated|improved)\b", re.I)
_DEGREE = re.compile(r"\b(?:bachelor|master|degree|diploma|ph\.?d|b\.?sc|m\.?sc|b\.?s|m\.?s)\b", re.I)
_BREAK = re.compile(
    r"\n\s*\n|[•●▪]\s*|"
    r"(?<=[.!?])(?<!B.Sc.)(?<!M.Sc.)(?<!Ph.D.)(?<!B.S.)(?<!M.S.)\s+(?=[A-Z“\"])|"
    r"\n(?=[^\n]{0,120}(?:\||\b(?:19|20)\d{2}\b))|"
    r"\s+(?=(?:PROFESSIONAL EXPERIENCE|WORK EXPERIENCE|TECHNICAL SKILLS|EDUCATION)\b)"
)


def _words(value):
    return set(re.findall(r"[a-z0-9]+(?:[+#]+)?", value.casefold())) - _STOP


def _spans(text):
    groups = []
    start = 0
    for boundary in _BREAK.finditer(text):
        if boundary.start() > start:
            groups.append((start, boundary.start()))
        start = boundary.end()
    if start < len(text):
        groups.append((start, len(text)))
    contextual = []
    for start, end in groups:
        unit = text[start:end].strip()
        contrast = re.match(r"(?:but|however|although|yet|except|only|limited)\b|(?:I|We|The project)\b[^.!?\n]{0,70}\b(?:not|never|no)\b", unit, re.I)
        if contextual and contrast:
            contextual[-1] = (contextual[-1][0], end)
        else:
            contextual.append((start, end))
    yield from contextual


def evidence_preview(requirement, limit=4):
    """Pick short, distinct, contiguous source excerpts; never assemble new quotes."""
    citations = requirement.get("evidence", [])
    terms = _words(requirement["name"] + " " + requirement.get("evaluation_criterion", ""))
    candidates = []
    for source_index, citation in enumerate(citations):
        text = citation["quote"]
        for start, end in _spans(text):
            while start < end and text[start].isspace(): start += 1
            while end > start and text[end - 1].isspace(): end -= 1
            if end - start < 3: continue
            unit = text[start:end]
            score = 2 * len(_words(unit) & terms) + 3 * bool(_ACTION.search(unit))
            if requirement.get("category") == "experience":
                score = 8 * bool(_DATE.search(unit)) + 3 * bool(_ROLE.search(unit)) + bool(_ACTION.search(unit))
                if re.search(r"\b(?:SUMMARY|TECHNICAL SKILLS|EDUCATION|date of birth|DOB)\b", unit, re.I): score -= 8
                if _DEGREE.search(unit) and not _ROLE.search(unit): score -= 12
            elif requirement.get("category") == "qualification":
                score += 4 * bool(_DEGREE.search(unit))
            if "@" in unit or re.search(r"https?://", unit): score -= 4
            # Prefer complete sentences/role lines. Long passages stay available
            # in full; a preview is explicitly marked when its tail is omitted.
            if end - start > 320:
                original_start, original_end = start, end
                anchor = (_DATE.search(unit) if requirement.get("category") == "experience" else
                          _DEGREE.search(unit) if requirement.get("category") == "qualification" else None)
                if anchor is None:
                    anchor = next((m for m in re.finditer(r"[a-z0-9]+(?:[+#]+)?", unit, re.I) if m[0].casefold() in terms), None)
                if anchor and anchor.start() > 160:
                    start += anchor.start() - 120
                    while start > original_start and not text[start - 1].isspace(): start -= 1
                stop = text.rfind(" ", start + 160, start + 320)
                if stop < start + 160: stop = start + 320
                # Do not drop a later qualification/negation from a long sentence.
                omitted = text[original_start:start] + " " + text[stop:original_end]
                if re.search(r"\b(?:no|not|never|without|except|however|but|only|limited)\b", omitted, re.I):
                    continue
                end = stop
            quote = text[start:end]
            candidates.append({"block_id": citation["block_id"], "locator": citation["locator"],
                "quote": quote, "source_index": source_index, "quote_start": start, "quote_end": end,
                "omitted_before": start > 0, "omitted_after": end < len(text), "_score": score})
    selected = []
    for candidate in sorted(candidates, key=lambda c: (-c["_score"], c["source_index"], c["quote_start"])):
        if candidate["_score"] <= 0: continue
        normalized = " ".join(candidate["quote"].casefold().split())
        if any(normalized in old or old in normalized for old in [" ".join(c["quote"].casefold().split()) for c in selected]):
            continue
        selected.append(candidate)
        if len(selected) == limit: break
    selected.sort(key=lambda c: (c["source_index"], c["quote_start"]))
    return [{k: v for k, v in c.items() if k != "_score"} for c in selected]


def requirement_reason(requirement, calculation=None):
    status = requirement["status"]
    if status not in {"met", "partially_met"}:
        return "The CV does not provide enough evidence for this requirement."
    if requirement.get("category") == "experience":
        minimum = re.search(r"At least (\d+(?:\.\d+)?) years", requirement["name"])
        months = (calculation or {}).get("months")
        if minimum and type(months) is int and 0 < months <= 1200:
            years, remaining = divmod(months, 12)
            parts = ([f"{years} year{'s' if years != 1 else ''}"] if years else [])
            if remaining: parts.append(f"{remaining} month{'s' if remaining != 1 else ''}")
            duration = " ".join(parts)
            enough = months >= float(minimum[1]) * 12
            if status == "met" and enough:
                return f"Employment dates support at least {duration} of relevant work, meeting the {minimum[1]}-year minimum. Overlapping jobs count once."
            if status == "partially_met" and not enough:
                return f"Employment dates support at least {duration} of relevant work; the minimum is {minimum[1]} years. Overlapping jobs count once."
        return ("Relevant roles and employment dates support the required experience." if status == "met" else
                "Relevant work is listed, but the full required experience is not demonstrated.")
    if status == "partially_met":
        return "The CV supports part of this requirement, but does not demonstrate it fully."
    return "The CV examples below support this requirement."


def present_breakdown(breakdown, calculations=None):
    result = deepcopy(breakdown)
    for requirement in result.get("requirements", []):
        requirement["reason"] = requirement_reason(requirement, (calculations or {}).get(requirement["requirement_id"]))
        requirement["evidence_preview"] = evidence_preview(requirement)
    return result
