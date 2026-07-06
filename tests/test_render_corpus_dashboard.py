"""Tests for build/tools/render_corpus_dashboard.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from build.tools import render_corpus_dashboard as rcd

# All tests load every committed data file from disk — slow by design.
pytestmark = pytest.mark.slow


def test_render_includes_all_resources_in_data(tmp_path: Path) -> None:
    body = rcd.render_dashboard(repo_root=rcd.REPO_ROOT, dead_letter_index={"resources": {}})
    # Both pilots must appear by id
    assert "adam-clarke" in body or "2-john" in body
    assert "schaff-herzog-encyclopedia" in body


def test_render_emits_375px_viewport_meta(tmp_path: Path) -> None:
    body = rcd.render_dashboard(dead_letter_index={"resources": {}})
    assert 'name="viewport"' in body
    assert "width=device-width" in body


def test_render_html_escapes_resource_id(tmp_path: Path, monkeypatch) -> None:
    # Synthesize a record with an XSS-y id in a tmp data tree
    monkeypatch.setattr(rcd, "REPO_ROOT", tmp_path)
    rec = tmp_path / "data" / "test.json"
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(
        json.dumps({"meta": {"id": "<script>alert(1)</script>"}, "data": []}),
        encoding="utf-8",
    )

    body = rcd.render_dashboard(repo_root=tmp_path, dead_letter_index={"resources": {}})
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body


def test_render_includes_confidence_axis_pills(tmp_path: Path) -> None:
    body = rcd.render_dashboard(dead_letter_index={"resources": {}})
    assert "axis-label" in body
    assert "structural" in body
    assert "text" in body
    assert "edition" in body


def test_render_includes_applier_state_counts(tmp_path: Path) -> None:
    body = rcd.render_dashboard(dead_letter_index={"resources": {}})
    # Per G retro: applier state counts surface in the dashboard
    assert "approved" in body
    assert "applied" in body
    assert "deferred" in body


def test_dead_letter_counts_come_from_index(tmp_path: Path) -> None:
    dl_index = {
        "resources": {
            "schaff-herzog-encyclopedia": {"total": 17, "by_reason": {}, "by_producer": {}, "spill_path": ""},
        }
    }
    body = rcd.render_dashboard(dead_letter_index=dl_index)
    assert "dead-letter 17" in body
