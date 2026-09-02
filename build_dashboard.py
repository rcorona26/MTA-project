"""
Render the retrospective dashboard from the exported metrics.

Run export_dashboard_data.py first to refresh docs/dashboard_data.json, then
this to inject it into the templates and write the standalone pages: the
plain-words explainer (docs/index.html) and the research brief
(docs/dashboard.html). Both outputs are self-contained — no external scripts,
styles, or fonts — so they can be opened directly or published as-is.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "docs/dashboard_template.html"
DATA = ROOT / "docs/dashboard_data.json"
MODEL = ROOT / "docs/model_bundle.json"
OUTPUT = ROOT / "docs/dashboard.html"
EXPLAINER_TEMPLATE = ROOT / "docs/explainer_template.html"
EXPLAINER_OUTPUT = ROOT / "docs/index.html"


def render_page(template, data, model):
    """Inject exported payloads and metadata into the standalone template."""
    meta = data["meta"]

    page = (
        template
        .replace("__DATA__", json.dumps(data, separators=(",", ":")))
        .replace("__MODEL__", json.dumps(model, separators=(",", ":")))
        .replace("__SNAP_START__", meta["snapshot_start"])
        .replace("__SNAP_END__", meta["snapshot_end"])
        .replace("__ROWS__", f"{meta['rows']:,}")
    )

    leftover = [line for line in page.splitlines() if "__" in line and "__main__" not in line]
    if leftover:
        raise SystemExit(f"unsubstituted placeholder: {leftover[0].strip()[:80]}")
    return page


def main():
    data = json.load(open(DATA))
    model = json.load(open(MODEL))
    for template_path, output_path in ((TEMPLATE, OUTPUT), (EXPLAINER_TEMPLATE, EXPLAINER_OUTPUT)):
        page = render_page(open(template_path).read(), data, model)
        with open(output_path, "w") as handle:
            handle.write(page)
        print(f"Wrote {output_path.relative_to(ROOT)} ({len(page):,} bytes)")


if __name__ == "__main__":
    main()
