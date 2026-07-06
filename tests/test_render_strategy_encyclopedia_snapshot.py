from __future__ import annotations

import json
import re
from pathlib import Path

from build.tools.render_review_html import render_resource_html


REPO_ROOT = Path(__file__).resolve().parents[1]


def _normalise(html: str) -> str:
    html = re.sub(r'\sclass="[^"]*"', "", html)
    return re.sub(r"\s+", " ", html).strip()


def test_schaff_herzog_first_five_entries_semantic_snapshot() -> None:
    record_path = REPO_ROOT / "data" / "reference" / "schaff-herzog-encyclopedia.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["data"] = record["data"][:5]

    html = _normalise(render_resource_html(record, source_path=record_path))

    expected_fragments = [
        "OCD encyclopedia review",
        "New Schaff-Herzog Encyclopedia of Religious Knowledge",
        "Review warnings",
        "Entry type: headword",
        "Aachen, Synods of",
        "Definition block 1",
        "Raw entry JSON",
    ]
    for fragment in expected_fragments:
        assert fragment in html
