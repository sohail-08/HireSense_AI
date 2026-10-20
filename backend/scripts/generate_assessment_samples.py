"""Generate synthetic-only PDFs; never reads database or candidate files.

Run from backend: python scripts/generate_assessment_samples.py --output ../output/pdf
"""
import argparse
import copy
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from assessment_fixtures import synthetic_source
from app.assessments.workflow import ConsolidatedAssessmentGraph, POLICY
from app.assessments.reports import render_html, render_pdf


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("../output/pdf"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    reports = []
    for index, name in enumerate(("Synthetic Candidate Alpha", "Synthetic Candidate Beta"), 1):
        source = synthetic_source(100 + index, name, long=True)
        if index == 2:
            source["missing"].append("Final reconciled analysis of all selected interview sessions")
            source["cv"]["final_score"] = "68.750000"
            source["cv"]["categories"]["technical"] = "67.500000"
            source["cv"]["written_justification"] = "Synthetic saved score with partial interview evidence. No upstream processing is invoked by this sample."
        result = ConsolidatedAssessmentGraph().graph.invoke({"snapshot": source})["result"]
        reports.append({"id": index, "version": 1, "application_id": source["identification"]["application_id"], "job_posting_id": 1,
            "created_at": "2026-10-20T05:00:00+00:00", "completed_at": "2026-10-20T05:00:02+00:00", "review_status": "not_reviewed",
            "completeness": result["completeness"], "comparison_cv_rank": index, "result": result,
            "notes": [{"id": 1, "author_id": 1, "note": "Synthetic demonstration only. Verify job-related evidence before making a decision.", "reviewed": False, "created_at": "2026-10-20T05:01:00+00:00"}]})
    comparison = {"id": 1, "snapshot": {"basis": "CV score order", "policy": POLICY,
        "cohort_policy": "Explicit synthetic cohort: applications 101 and 102. Original full-job CV ranks are preserved.",
        "incompatibilities": [], "interview_incompatibilities": [], "assessments": copy.deepcopy(reports)}}
    payloads = {"synthetic-individual": {"kind": "individual", "reports": [reports[0]]},
        "synthetic-comparison": {"kind": "comparison", "comparison": comparison, "reports": reports}}
    for name, payload in payloads.items():
        html = render_html(payload)
        (args.output / f"{name}.html").write_text(html, encoding="utf-8")
        (args.output / f"{name}.pdf").write_bytes(render_pdf(html, landscape=payload["kind"] == "comparison"))
        print(f"Generated {name}.pdf (synthetic data only)")


if __name__ == "__main__": main()
