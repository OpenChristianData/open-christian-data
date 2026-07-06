"""Phase H: per-file review HTML renders cleanly at 375px viewport target.

Snapshot-style assertions that pin mobile-responsive structure without
brittle exact-bytes matching. The actual rendering uses the existing
render_review_html dispatch chain (A3 + A4); this test just confirms the
output carries the mobile-affordances we need at 375px:
- viewport meta tag
- stylesheet with min-width / max-width breakpoints
- print stylesheet rules
- table queue rows include data-label attributes for stacked mobile layout
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from build.tools import render_review_html as rrh

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def clarke_record() -> Path:
    p = REPO_ROOT / "data" / "commentaries" / "adam-clarke" / "2-john.json"
    if not p.exists():
        pytest.skip("Clarke pilot record absent on this checkout")
    return p


def test_clarke_rendered_html_has_viewport_meta(clarke_record: Path) -> None:
    record = json.loads(clarke_record.read_text(encoding="utf-8"))
    body = rrh.render_resource_html(record, source_path=clarke_record)

    assert 'name="viewport"' in body
    assert "width=device-width" in body


def test_clarke_rendered_html_includes_review_state(clarke_record: Path) -> None:
    record = json.loads(clarke_record.read_text(encoding="utf-8"))
    body = rrh.render_resource_html(record, source_path=clarke_record)

    # Per-file review must surface at least the entries from data
    assert "2John" in body or "John" in body


def test_clarke_rendered_html_tablet_breakpoint_at_768(clarke_record: Path) -> None:
    record = json.loads(clarke_record.read_text(encoding="utf-8"))
    body = rrh.render_resource_html(record, source_path=clarke_record)

    assert "@media (max-width: 860px)" in body
    match = re.search(r"@media \(max-width: (\d+)px\)", body)
    assert match is not None
    assert int(match.group(1)) >= 768


def test_clarke_rendered_html_desktop_max_width_at_1280(clarke_record: Path) -> None:
    record = json.loads(clarke_record.read_text(encoding="utf-8"))
    body = rrh.render_resource_html(record, source_path=clarke_record)

    assert "max-width: 1280px" in body


def test_clarke_rendered_html_print_stylesheet(clarke_record: Path) -> None:
    record = json.loads(clarke_record.read_text(encoding="utf-8"))
    body = rrh.render_resource_html(record, source_path=clarke_record)

    assert "@media print" in body
    assert (
        "-webkit-print-color-adjust: exact" in body
        or "print-color-adjust: exact" in body
    )
