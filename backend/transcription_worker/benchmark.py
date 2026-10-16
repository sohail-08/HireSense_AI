"""Offline scorer for opt-in synthetic/consented benchmark observations.

Never contacts Deepgram. Usage: python -m transcription_worker.benchmark observations.json
Input contains reference/hypothesis text: keep real candidate benchmark files private.
"""
import argparse
import json
import math
import re
import statistics
from pathlib import Path


def tokens(text):
    return re.findall(r"[\w+#.]+", text.casefold())


def distance(a, b):
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        row = [i]
        for j, y in enumerate(b, 1):
            row.append(min(row[-1] + 1, previous[j] + 1, previous[j - 1] + (x != y)))
        previous = row
    return previous[-1]


def distribution(values):
    if not values:
        return {"count": 0, "median": None, "p95": None}
    ordered = sorted(values)
    return {"count": len(values), "median": statistics.median(values), "p95": ordered[max(0, math.ceil(len(values) * .95) - 1)]}


def report(data):
    observations = data["observations"]
    refs = sum(len(tokens(o["reference"])) for o in observations)
    errors = sum(distance(tokens(o["reference"]), tokens(o["hypothesis"])) for o in observations)
    correct_speakers = sum(o["expected_speaker"] == o["actual_speaker"] for o in observations)
    terms = data.get("technical_terms", [])
    expected_terms = observed_terms = 0
    for o in observations:
        for term in terms:
            expected = o["reference"].casefold().count(term.casefold())
            expected_terms += expected
            observed_terms += min(expected, o["hypothesis"].casefold().count(term.casefold()))
    return {"environment": data.get("environment", {}), "utterances": len(observations),
        "word_error_rate": errors / refs if refs else None,
        "technical_term_error_rate": 1 - observed_terms / expected_terms if expected_terms else None,
        "speaker_attribution_accuracy": correct_speakers / len(observations) if observations else None,
        "interim_latency_ms": distribution([o["interim_latency_ms"] for o in observations if o.get("interim_latency_ms") is not None]),
        "finalization_latency_ms": distribution([o["finalization_latency_ms"] for o in observations if o.get("finalization_latency_ms") is not None]),
        "timestamp_alignment_error_ms": distribution([abs(o["actual_start_ms"] - o["reference_start_ms"]) for o in observations]),
        "overlapping_utterances": sum(bool(o.get("overlap")) for o in observations)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("observations", type=Path)
    args = parser.parse_args()
    print(json.dumps(report(json.loads(args.observations.read_text(encoding="utf-8"))), indent=2))


if __name__ == "__main__":
    main()
