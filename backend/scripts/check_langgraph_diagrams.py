"""Check editable draw.io diagrams against compiled graphs, without invoking them.

Run from backend: .venv/Scripts/python.exe scripts/check_langgraph_diagrams.py
Use --json to inspect the live node/edge inventory. No provider, database or
business-tool calls are made, and this utility does not write any files.
"""
import argparse
import json
import math
import os
from collections import Counter
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET_KEY", "offline-diagram-check-only-secret-at-least-32-characters")
os.environ.setdefault("INTERVIEWER_EMAIL", "diagrams@example.com")
os.environ.setdefault("INTERVIEWER_PASSWORD", "offline-diagram-check-only-password")


class Offline:
    def bind_tools(self, *args, **kwargs):
        return self

    def __call__(self, *args, **kwargs):
        raise AssertionError("Diagram checks must not execute business operations")

    invoke = extract = generate_json = __call__


def graph_inventory():
    from app.agents.supervisor import HireSenseSupervisorGraph
    from app.agents.job_posting import JobPostingAssistantGraph
    from app.screening.workflow import ScreeningWorkflow
    from app.scoring.workflow import CandidateScoringWorkflow
    from app.agents.interview_analysis import InterviewAnalysisGraph
    from app.assessments.workflow import ConsolidatedAssessmentGraph
    from app.agents.work_sample import WorkSampleGraph

    offline = Offline()
    definitions = [
        ("supervisor", "01-supervisor.drawio", "app/agents/supervisor.py", HireSenseSupervisorGraph(offline, [])._compiled),
        ("job-posting", "02-job-posting.drawio", "app/agents/job_posting.py", JobPostingAssistantGraph(offline)._compiled),
        ("cv-screening", "03-cv-screening.drawio", "app/screening/workflow.py", ScreeningWorkflow(db=None, parser=None, ai=None, validate_result=offline, persist_result=offline)._compiled),
        ("candidate-scoring", "04-candidate-scoring.drawio", "app/scoring/workflow.py", CandidateScoringWorkflow(offline)._compiled),
        ("interview-analysis", "05-interview-analysis.drawio", "app/agents/interview_analysis.py", InterviewAnalysisGraph(offline).graph),
        ("consolidated-assessment", "06-consolidated-assessment.drawio", "app/assessments/workflow.py", ConsolidatedAssessmentGraph(offline).graph),
        ("work-sample-generation", "07-work-sample-generation.drawio", "app/agents/work_sample.py", WorkSampleGraph(offline).graph),
    ]
    inventory = []
    for graph_id, filename, source, compiled in definitions:
        graph = compiled.get_graph()
        inventory.append({"id": graph_id, "filename": filename, "source": "backend/" + source,
            "nodes": list(graph.nodes), "edges": [{"source": edge.source, "target": edge.target,
                "conditional": edge.conditional,
                # LangGraph omits redundant branch labels when key == target.
                "label": str(edge.data) if edge.data is not None else edge.target if edge.conditional else ""}
                for edge in graph.edges]})
    return inventory


def check_page(page, expected, filename):
    model = page.find("mxGraphModel")
    assert model is not None, f"{filename}: page must contain editable, uncompressed XML"
    cells = model.findall("./root/mxCell")
    ids = [cell.attrib["id"] for cell in cells]
    assert len(ids) == len(set(ids)), f"{filename}: duplicate cell IDs"
    nodes = {cell.attrib["id"] for cell in cells if cell.get("vertex") == "1" and not cell.attrib["id"].startswith("doc-")}
    assert nodes == set(expected["nodes"]), f"{filename}: graph nodes differ from code"
    actual_edges = Counter((cell.get("source"), cell.get("target"), "dashed=1" in cell.get("style", ""), cell.get("value", ""))
        for cell in cells if cell.get("edge") == "1")
    expected_edges = Counter((edge["source"], edge["target"], edge["conditional"], edge["label"]) for edge in expected["edges"])
    assert actual_edges == expected_edges, f"{filename}: graph edges or branch labels differ from code"
    width, height = float(model.get("pageWidth")), float(model.get("pageHeight"))
    rectangles = []
    for cell in cells:
        if cell.get("vertex") != "1":
            continue
        geometry = cell.find("mxGeometry")
        assert geometry is not None, f"{filename}: missing geometry"
        x, y, w, h = [float(geometry.get(key, "0")) for key in ("x", "y", "width", "height")]
        assert all(math.isfinite(value) for value in (x, y, w, h)), f"{filename}: invalid coordinates"
        assert x >= 0 and y >= 0 and w > 0 and h > 0 and x + w <= width and y + h <= height, f"{filename}: cell outside page"
        for other, ox, oy, ow, oh in rectangles:
            assert x >= ox + ow or ox >= x + w or y >= oy + oh or oy >= y + h, f"{filename}: overlapping cells {other} and {cell.get('id')}"
        rectangles.append((cell.get("id"), x, y, w, h))


def check_diagrams(inventory):
    folder = ROOT / "docs" / "langgraphs"
    expected_names = {item["filename"] for item in inventory} | {"hiresense-all-langgraphs.drawio"}
    assert {file.name for file in folder.glob("*.drawio")} == expected_names, "Obsolete or missing individual diagrams"
    for item in inventory:
        path = folder / item["filename"]
        pages = ET.parse(path).getroot().findall("diagram")
        assert len(pages) == 1 and pages[0].get("id") == item["id"], f"{path}: unexpected pages"
        check_page(pages[0], item, str(path))
    for path in (folder / "hiresense-all-langgraphs.drawio", ROOT / "docs" / "hiresense-langgraph-workflow.drawio"):
        pages = ET.parse(path).getroot().findall("diagram")
        assert [page.get("id") for page in pages] == [item["id"] for item in inventory], f"{path}: expected seven current graphs"
        for page, item in zip(pages, inventory):
            check_page(page, item, str(path))
    assert (folder / "hiresense-all-langgraphs.drawio").read_bytes() == (ROOT / "docs" / "hiresense-langgraph-workflow.drawio").read_bytes(), "Combined diagrams should be identical"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print graph inventory instead of checking files")
    args = parser.parse_args()
    inventory = graph_inventory()
    if args.json:
        print(json.dumps(inventory))
    else:
        check_diagrams(inventory)
        print("Verified 7 individual diagrams and both 7-page bundles against compiled LangGraphs; no graph was invoked.")
