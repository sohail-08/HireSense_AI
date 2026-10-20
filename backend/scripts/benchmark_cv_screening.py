"""Opt-in synthetic evaluation. Never reads business data or real candidate files."""
import argparse
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def metrics(rows):
    labels = ("met", "partially_met", "unmet")
    f1 = []
    for label in labels:
        tp = sum(r["expected"] == r["actual"] == label for r in rows)
        fp = sum(r["actual"] == label and r["expected"] != label for r in rows)
        fn = sum(r["expected"] == label and r["actual"] != label for r in rows)
        if tp + fp + fn: f1.append(2 * tp / (2 * tp + fp + fn))
    return {"cases": len(rows), "correct": sum(r["expected"] == r["actual"] for r in rows),
        "accuracy": round(sum(r["expected"] == r["actual"] for r in rows) / len(rows), 4) if rows else None,
        "macro_f1": round(sum(f1) / len(f1), 4) if f1 else None,
        "graded_cases": sum(r["actual"] in labels for r in rows),
        "accuracy_on_graded_cases": round(sum(r["expected"] == r["actual"] for r in rows) / sum(r["actual"] in labels for r in rows),4) if any(r["actual"] in labels for r in rows) else None,
        "processing_errors": sum(r["actual"] == "processing_error" for r in rows)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicitly allow Gemini and local Ollama calls (uses quota).")
    parser.add_argument("--predictions", type=Path, help="Evaluate an existing synthetic result file without provider calls.")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--output", type=Path, default=Path("../output/cv-screening-benchmark.json"))
    args = parser.parse_args()
    if args.predictions:
        print(json.dumps(metrics(json.loads(args.predictions.read_text(encoding="utf-8"))["results"])))
        return
    if not args.live: parser.error("Use --live to permit provider calls, or --predictions for offline evaluation.")
    if not 1 <= args.limit <= 20: parser.error("--limit must be between 1 and 20")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.config import get_settings
    from app.database import Base
    import app.models  # register metadata; no SessionLocal or production DB access
    from app.screening.ai import GeminiScreeningAI
    from app.screening.retrieval import CVSemanticRetriever, digest
    from app.services.screening_service import ScreeningService, safe_screening_error
    cases = json.loads((Path(__file__).resolve().parents[1] / "tests/fixtures/cv_semantic_benchmark.json").read_text(encoding="utf-8"))[:args.limit]
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    settings = get_settings()
    retriever = CVSemanticRetriever(settings)
    rows, started = [], time.monotonic()
    with Session(engine) as db:
        for index, case in enumerate(cases, 1):
            before = time.monotonic()
            try:
                category = case.get("category", "required_skill")
                requirement = {"key": category + ":0", "category": category, "name": case["criterion"],
                    "details": "For experience, evaluate backend software development work only." if category == "experience" else None, "weight": 1}
                document = SimpleNamespace(id=index, sha256=digest(case["text"]))
                blocks, requirements, retrieval = retriever.prepare(db, document,
                    [{"id": "synthetic-page-1", "locator": "Synthetic CV page 1", "text": case["text"]}], [requirement])
                ai = GeminiScreeningAI()
                profile = ai.extract_profile(blocks=blocks).model_dump()
                profile["evaluation_as_of"] = "2026-10-01"
                initial = ai.assess_requirements(profile=profile, requirements=requirements, blocks=blocks)
                assessment, audit, recovery = ai.audit_and_recover(profile=profile, requirements=requirements, blocks=blocks, assessment=initial)
                final = ScreeningService._validate_assessment(requirements=requirements, blocks=blocks,
                    assessment=assessment.model_dump(), evidence_validation=audit.model_dump())
                actual = final["matches"][0]["status"]
                row = {"id": case["id"], "expected": case["expected"], "actual": actual,
                    "matches": final["matches"], "recovery": recovery, "retrieval": retrieval}
            except Exception as exc:
                db.rollback()
                row = {"id": case["id"], "expected": case["expected"], "actual": "processing_error", "error": safe_screening_error(exc)}
            row["seconds"] = round(time.monotonic() - before, 2)
            rows.append(row)
            print(json.dumps({k: row[k] for k in ("id", "expected", "actual", "seconds")}), flush=True)
    result = {"synthetic_only": True, "as_of": "2026-10-01", "metrics": metrics(rows), "results": rows,
        "seconds": round(time.monotonic() - started, 2), "model": settings.gemini_chat_model}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result["metrics"]))


if __name__ == "__main__": main()
