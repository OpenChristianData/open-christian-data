"""Tests for build/tools/update_dead_letter_index.py."""

from __future__ import annotations

import json
from pathlib import Path

from build.tools.update_dead_letter_index import build_index


def _write_spill(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e) + "\n")


def test_index_counts_match_spill_files(tmp_path: Path) -> None:
    spill_dir = tmp_path / "dead-letter"
    _write_spill(
        spill_dir / "alpha.jsonl",
        [
            {"reason": "producer_unknown", "producer_id": "p1", "received_at": "2026-05-13T00:00:00+00:00"},
            {"reason": "producer_unknown", "producer_id": "p1", "received_at": "2026-05-13T00:00:00+00:00"},
            {"reason": "evidence_schema_failed", "producer_id": "p2", "received_at": "2026-05-13T00:00:00+00:00"},
        ],
    )
    _write_spill(
        spill_dir / "beta.jsonl",
        [
            {"reason": "evidence_schema_failed", "producer_id": "p2", "received_at": "2026-05-13T00:00:00+00:00"},
        ],
    )

    index = build_index(spill_dir)

    assert index["resources"]["alpha"]["total"] == 3
    assert index["resources"]["alpha"]["by_reason"]["producer_unknown"] == 2
    assert index["resources"]["alpha"]["by_producer"]["p1"] == 2
    assert index["resources"]["beta"]["total"] == 1


def test_index_handles_empty_directory(tmp_path: Path) -> None:
    spill_dir = tmp_path / "empty-dead-letter"
    spill_dir.mkdir()

    index = build_index(spill_dir)

    assert index["resources"] == {}
    assert "generated_at_utc" in index


def test_index_skips_malformed_lines(tmp_path: Path) -> None:
    spill_dir = tmp_path / "dead-letter"
    spill_dir.mkdir()
    (spill_dir / "alpha.jsonl").write_text(
        '{"reason": "ok", "producer_id": "p", "received_at": "2026-05-13T00:00:00+00:00"}\n'
        "this is not json\n"
        '{"reason": "ok", "producer_id": "p", "received_at": "2026-05-13T00:00:00+00:00"}\n',
        encoding="utf-8",
    )

    index = build_index(spill_dir)

    assert index["resources"]["alpha"]["total"] == 2
