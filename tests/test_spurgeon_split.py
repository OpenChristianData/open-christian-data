"""Tests for the Spurgeon MTP output-chunking logic.

Covers build/parsers/spurgeon_mtp.py::write_chunked_output and its sort helper.
"""
from __future__ import annotations

import json
from pathlib import Path


from build.parsers.spurgeon_mtp import natural_sort_key, write_chunked_output


def _make_entries(n: int) -> list[dict]:
    return [
        {"sermon_id": f"spurgeon-mtp.{i+1}", "word_count": 100}
        for i in range(n)
    ]


def _make_meta() -> dict:
    return {
        "id": "spurgeon-mtp",
        "title": "Metropolitan Tabernacle Pulpit",
        "schema_type": "sermon",
        "provenance": {"sources": []},
    }


def _sorted_chunks(out_dir: Path) -> list[Path]:
    """Return chunk files in numeric (not lexicographic) order."""
    return sorted(out_dir.glob("sermons-*.json"), key=natural_sort_key)


def test_chunks_of_100_create_expected_filenames(tmp_path: Path) -> None:
    entries = _make_entries(250)
    out_dir = tmp_path / "spurgeon-mtp"

    write_chunked_output(entries, _make_meta(), out_dir, chunk_size=100)

    files = _sorted_chunks(out_dir)
    assert [f.name for f in files] == [
        "sermons-1-100.json",
        "sermons-101-200.json",
        "sermons-201-250.json",
    ]


def test_chunks_preserve_all_entries_in_order(tmp_path: Path) -> None:
    entries = _make_entries(250)
    out_dir = tmp_path / "spurgeon-mtp"

    write_chunked_output(entries, _make_meta(), out_dir, chunk_size=100)

    recovered = []
    for f in _sorted_chunks(out_dir):
        recovered.extend(json.loads(f.read_text(encoding="utf-8"))["data"])
    assert recovered == entries


def test_each_chunk_has_meta_block(tmp_path: Path) -> None:
    entries = _make_entries(150)
    out_dir = tmp_path / "spurgeon-mtp"

    write_chunked_output(entries, _make_meta(), out_dir, chunk_size=100)

    for f in _sorted_chunks(out_dir):
        obj = json.loads(f.read_text(encoding="utf-8"))
        assert "meta" in obj
        assert "data" in obj
        assert obj["meta"]["id"] == "spurgeon-mtp"


def test_chunk_size_larger_than_entries_creates_single_file(tmp_path: Path) -> None:
    entries = _make_entries(50)
    out_dir = tmp_path / "spurgeon-mtp"

    write_chunked_output(entries, _make_meta(), out_dir, chunk_size=100)

    files = _sorted_chunks(out_dir)
    assert [f.name for f in files] == ["sermons-1-50.json"]


def test_exact_multiple_of_chunk_size(tmp_path: Path) -> None:
    entries = _make_entries(200)
    out_dir = tmp_path / "spurgeon-mtp"

    write_chunked_output(entries, _make_meta(), out_dir, chunk_size=100)

    files = _sorted_chunks(out_dir)
    assert [f.name for f in files] == [
        "sermons-1-100.json",
        "sermons-101-200.json",
    ]


def test_last_chunk_name_reflects_actual_last_entry(tmp_path: Path) -> None:
    """For 3,550 sermons, last file must be sermons-3501-3550.json, not sermons-3501-3600.json."""
    entries = _make_entries(3550)
    out_dir = tmp_path / "spurgeon-mtp"

    write_chunked_output(entries, _make_meta(), out_dir, chunk_size=100)

    files = _sorted_chunks(out_dir)
    assert files[-1].name == "sermons-3501-3550.json"
    assert len(files) == 36


def test_natural_sort_orders_numerically(tmp_path: Path) -> None:
    """Verify natural_sort_key sorts sermons-1-100 BEFORE sermons-101-200, not after."""
    names = [
        "sermons-1001-1100.json",
        "sermons-1-100.json",
        "sermons-101-200.json",
        "sermons-201-300.json",
    ]
    ordered = sorted(names, key=natural_sort_key)
    assert ordered == [
        "sermons-1-100.json",
        "sermons-101-200.json",
        "sermons-201-300.json",
        "sermons-1001-1100.json",
    ]
