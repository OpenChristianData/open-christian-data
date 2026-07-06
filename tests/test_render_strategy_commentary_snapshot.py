from __future__ import annotations

import json
import re
from pathlib import Path

from build.tools.render_review_html import render_resource_html


REPO_ROOT = Path(__file__).resolve().parents[1]


def _normalise(html: str) -> str:
    html = re.sub(r'\sclass="[^"]*"', "", html)
    return re.sub(r"\s+", " ", html).strip()


def test_clarke_2_john_commentary_semantic_snapshot() -> None:
    record_path = REPO_ROOT / "data" / "commentaries" / "adam-clarke" / "2-john.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))

    html = _normalise(render_resource_html(record, source_path=record_path))

    expected_fragments = [
        "OCD commentary review",
        "Clarke&#x27;s Commentary on the Bible",
        "Review warnings",
        "Navigation",
        "2 John introduction",
        "Entry type: intro",
        "Entry type: verse",
        "Verse text",
        "Raw entry JSON",
    ]
    for fragment in expected_fragments:
        assert fragment in html
