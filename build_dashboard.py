"""
Render the retrospective dashboard from the exported metrics.

Run export_dashboard_data.py first to refresh docs/dashboard_data.json, then
this to inject it into docs/dashboard_template.html and write the standalone
page. The output is self-contained — no external scripts, styles, or fonts —
so it can be opened directly or published as-is.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "docs/dashboard_template.html"
DATA = ROOT / "docs/dashboard_data.json"
MODEL = ROOT / "docs/model_bundle.json"
OUTPUT = ROOT / "docs/dashboard.html"


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
    template = open(TEMPLATE).read()
    data = json.load(open(DATA))
    model = json.load(open(MODEL))
    page = render_page(template, data, model)

    with open(OUTPUT, "w") as handle:
        handle.write(page)
    print(f"Wrote {OUTPUT.relative_to(ROOT)} ({len(page):,} bytes)")


if __name__ == "__main__":
    main()
