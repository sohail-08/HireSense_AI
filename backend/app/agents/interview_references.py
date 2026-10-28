"""Bounded hybrid guide selection. Search normalization never edits source speech."""
import math
import re

_STOP = set("a an and are as at be between by can could describe discuss do does explain for from how i in is it me of on or please kindly should tell that the their them these they this to us use what when where which who why will with would you your".split())
_ALIASES = {"testing": "test", "tests": "test", "forms": "form", "layouts": "layout",
            "components": "component", "hooks": "hook", "promises": "promise", "accessibility": "accessible"}


def retrieval_question(question):
    for spoken, name in ((r"\buse\s+effect\b", "useEffect"), (r"\buse\s+state\b", "useState"),
                         (r"\bjava\s+script\b", "JavaScript"), (r"\btype\s+script\b", "TypeScript")):
        question = re.sub(spoken, name, question, flags=re.IGNORECASE)
    return question


def terms(value):
    return {_ALIASES.get(t, t) for t in re.findall(r"[a-z0-9+#]+", retrieval_question(value).lower())
            if t not in _STOP and len(t) > 1}


def retrieval_query(question, requirements):
    context = ", ".join(str(r.get("name", ""))[:100] for r in requirements.get("requirements", [])[:8])
    return retrieval_question(question) + ("\nJob competencies: " + context if context else "")


def select_guides(question, references, retrieved=None, limit=6):
    """Fuse vector ranks and specific topic matches within the approved snapshot."""
    query = terms(question)
    tokens = {r["id"]: terms(r["title"] + " " + r["content"]) for r in references}
    lexical = {}
    for ref in references:
        title = terms(ref["title"])
        lexical[ref["id"]] = sum((1 + math.log((len(references) + 1) /
            (1 + sum(t in words for words in tokens.values())))) * (3 if t in title else 1)
            for t in sorted(query & tokens[ref["id"]]))
    ranks = {key: i for i, key in enumerate(dict.fromkeys(retrieved or []))}
    matches = sorted((r for r in references if lexical[r["id"]] > 0), key=lambda r: (-lexical[r["id"]], r["id"]))
    lexical_ranks = {r["id"]: i for i, r in enumerate(matches)}
    candidates = [r for r in references if r["id"] in ranks or r["id"] in lexical_ranks]
    def rank(ref):
        key = ref["id"]
        fused = (1 / (10 + ranks[key]) if key in ranks else 0) + (1 / (10 + lexical_ranks[key]) if key in lexical_ranks else 0)
        return (ref["kind"] != "answer_guide", -fused, -lexical[key], key)
    return [r["id"] for r in sorted(candidates, key=rank)[:limit]]
