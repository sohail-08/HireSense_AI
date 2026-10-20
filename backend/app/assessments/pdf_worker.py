"""Short-lived offline renderer. Receives only escaped app-owned HTML, no credentials."""
import json
import sys
from playwright.sync_api import sync_playwright


def render(html, landscape=False):
    with sync_playwright() as engine:
        browser = engine.chromium.launch(headless=True, timeout=15000)
        try:
            context = browser.new_context(java_script_enabled=False, service_workers="block", offline=True)
            context.route("**/*", lambda route: route.abort())
            page = context.new_page()
            page.set_default_timeout(15000)
            page.set_content(html, wait_until="load", timeout=15000)
            return page.pdf(format="A4", landscape=landscape, print_background=True,
                margin={"top": "14mm", "bottom": "17mm", "left": "12mm", "right": "12mm"},
                display_header_footer=True, header_template="<span></span>",
                footer_template='<div style="font-size:8px;color:#64748b;width:100%;text-align:center">HireSense - Private assessment | <span class="pageNumber"></span> / <span class="totalPages"></span></div>')
        finally:
            browser.close()


if __name__ == "__main__":
    data = json.loads(sys.stdin.buffer.read(8_100_000))
    if len(data["html"].encode("utf-8")) > 4_000_000: raise ValueError("Report too large")
    sys.stdout.buffer.write(render(data["html"], data["landscape"]))
