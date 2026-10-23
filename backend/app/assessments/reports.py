"""Application-owned escaped HTML and offline, JavaScript-disabled Chromium PDF."""
from pathlib import Path
import json
import os
import signal
import subprocess
import sys
from jinja2 import Environment, FileSystemLoader, select_autoescape
from app.agents.interview_analysis import digest
from app.services.scoring_calculation import display_score
from app.services.date_time_display import format_date_time

TEMPLATE_VERSION = "assessment-report-v9-approved-llm-practical-score"


def render_html(payload):
    import copy
    from app.assessments.performance_summary import report_performance_summary
    payload = copy.deepcopy(payload)
    for run in payload.get("reports", []):
        result = run.get("result", {})
        if result.get("evidence_summary"):
            result["evidence_summary"] = report_performance_summary(result)
    env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"),
                      autoescape=select_autoescape(["html"], default_for_string=True))
    env.filters["score"] = lambda value: display_score(str(value)) if value is not None else "Not available"
    env.filters["label"] = lambda value: str(value).replace("_", " ")
    env.filters["anchor"] = lambda value: digest(value)[:16]
    env.filters["datetime"] = format_date_time
    content = env.get_template("report.html").render(payload=payload, template_version=TEMPLATE_VERSION)
    if len(content.encode("utf-8")) > 4_000_000: raise ValueError("Report exceeds the bounded export size")
    return content


def render_pdf(html, *, landscape=False):
    # Page.pdf has no timeout parameter. Bound the entire renderer in a separate
    # process, including browser startup, layout, printing and browser shutdown.
    if len(html.encode("utf-8")) > 4_000_000: raise ValueError("Report exceeds the bounded export size")
    options = {"start_new_session": True} if os.name != "nt" else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    runtime_keys = {"PATH", "PLAYWRIGHT_BROWSERS_PATH", "HOME", "USERPROFILE", "LOCALAPPDATA", "TEMP", "TMP", "TMPDIR",
        "SYSTEMROOT", "COMSPEC", "WINDIR", "LD_LIBRARY_PATH", "FONTCONFIG_PATH", "XDG_CACHE_HOME"}
    runtime = {k: v for k, v in os.environ.items() if k.upper() in runtime_keys}
    runtime["PYTHONIOENCODING"] = "utf-8"
    process = subprocess.Popen([sys.executable, "-m", "app.assessments.pdf_worker"], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=Path(__file__).resolve().parents[2], env=runtime, **options)
    try:
        content, _ = process.communicate(json.dumps({"html": html, "landscape": landscape}, ensure_ascii=False).encode("utf-8"), timeout=55)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        else:
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        process.communicate()
        raise ValueError("PDF rendering exceeded its time limit") from None
    if process.returncode or not content.startswith(b"%PDF-"):
        raise ValueError("PDF renderer could not produce a document")
    return content
