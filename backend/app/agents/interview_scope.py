"""Conservative, local exclusion of pure interview housekeeping. No model calls."""
import copy
import re

SCOPING_VERSION = "job-related-interview-scope-v1"

_SALUTATION = r"(?:hello|hi|hey|good morning|good afternoon|good evening)"
_HOUSEKEEPING = re.compile(
    r"(?:"
    r"(?:can|could|do) you (?:hear me|see me|see my screen)(?: (?:clearly|now|okay|ok|well))?|"
    r"(?:am i audible|is (?:my|your|the) (?:audio|microphone|camera|video|connection) (?:working|clear|on|off|okay|ok))|"
    r"(?:how are you(?: doing)?(?: today)?|how is your day|what is your name|what's your name)|"
    r"(?:are you ready(?: to (?:start|begin)(?: the interview)?)?)|"
    r"(?:(?:please|can you|could you) (?:turn|switch) (?:on|off) your (?:camera|microphone))|"
    r"(?:did you find the interview link(?: easily)?|can you open the interview link)|"
    r"(?:thank you(?: for (?:your time|joining|coming|attending))?|thanks(?: for your time)?|"
    r"welcome(?: to (?:the|this) interview)?|that is all|that's all|goodbye|bye)"
    r")", re.IGNORECASE)


def pure_housekeeping(text):
    """Only whole, known phrases qualify; a mixed technical question is retained."""
    clauses = [re.sub(r"\s+", " ", part).strip(" ,:-") for part in re.split(r"[.!?;\n]+", text.lower()) if part.strip(" ,:-")]
    if not clauses:
        return False
    for clause in clauses:
        # A salutation with a name may precede a device check in the same sentence.
        if _HOUSEKEEPING.fullmatch(clause):
            continue
        if re.fullmatch(_SALUTATION + r"(?:[ ,]+[a-z][a-z'-]*){0,3}", clause):
            if not re.search(r"\b(?:explain|describe|implement|design|debug|what|how|why|tell)\b", clause):
                continue
        match = re.search(r"\b(?:can|could|do|am|is|are|how|what)\b", clause)
        if match and re.fullmatch(_SALUTATION + r"(?:[ ,]+[a-z][a-z'-]*){0,3}[ ,]*", clause[:match.start()].strip(" ,")) and _HOUSEKEEPING.fullmatch(clause[match.start():]):
            continue
        return False
    return True


def housekeeping_segment_ids(segments):
    """Recognize short checks split across adjacent interviewer ASR segments."""
    excluded = set()
    for start, segment in enumerate(segments):
        if segment.get("speaker") != "INTERVIEWER":
            continue
        group = []
        for item in segments[start:start + 4]:
            if item.get("speaker") != "INTERVIEWER": break
            group.append(item)
            if pure_housekeeping(" ".join(s["text"] for s in group)):
                excluded.update(s["id"] for s in group)
    return excluded


def housekeeping_reply(text):
    """Only used after an excluded interviewer turn, never on a job answer alone."""
    normalized = re.sub(r"[.!?,;]+", " ", text.lower()).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    return bool(re.fullmatch(r"(?:(?:yes|yeah|yep|no|okay|ok|sure|thanks|thank you)(?: i can hear you(?: clearly)?| i can see you| i am ready| i'm ready)?|i can hear you(?: clearly)?|i can see you|hello|hi)", normalized))


def apply_scoring_scope(result, snapshot):
    """Read-only filtering of older clear housekeeping pairs, preserving sources."""
    scoped = copy.deepcopy(result)
    segments = {s["id"]: s for s in snapshot.get("segments", [])}
    local = housekeeping_segment_ids(snapshot.get("segments", []))
    turns = {t["segment_id"]: t for t in scoped.get("turns", [])}
    unpaired = {item["segment_id"]: item for item in scoped.get("unpaired", [])}
    for pair in scoped.get("pairs", []):
        questions = pair.get("question_ids", [])
        if not questions or not all(i in segments and (i in local or turns.get(i, {}).get("scoring_scope") == "non_assessment") for i in questions):
            continue
        pair.update(excluded=True, state="excluded", exclusion_reason="Greeting, small talk or interview logistics; excluded from assessment.")
        pair.pop("score", None)
        pair.pop("analysis_error", None)
        pair.pop("analysis_failure", None)
        pair.pop("score_unavailable_reason", None)
        for identifier in questions + pair.get("answer_ids", []) + pair.get("context_ids", []):
            if identifier in segments:
                unpaired.setdefault(identifier, {"segment_id": identifier, "kind": "non_assessment"})
    order = {identifier: index for index, identifier in enumerate(segments)}
    scoped["unpaired"] = sorted(unpaired.values(), key=lambda item: order.get(item["segment_id"], len(segments)))
    scoped["scoping_version"] = SCOPING_VERSION
    return scoped
