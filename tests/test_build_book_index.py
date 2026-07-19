from __future__ import annotations

import json
from pathlib import Path

from build.tools import build_book_index


def _write_record(path: Path, *, record_id: str, title: str, schema_type: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "meta": {
                    "id": record_id,
                    "title": title,
                    "schema_type": schema_type,
                },
                "data": [],
            }
        ),
        encoding="utf-8",
    )


def test_collect_entries_excludes_auxiliary_lexicon(monkeypatch, tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    _write_record(
        data_root / "structured-text" / "book.json",
        record_id="book",
        title="A Book",
        schema_type="structured_text",
    )
    _write_record(
        data_root / "lexicon" / "grc.json",
        record_id="grc",
        title="Greek Lexicon",
        schema_type="lexicon",
    )
    monkeypatch.setattr(build_book_index, "DATA_DIR", data_root)
    monkeypatch.setattr(build_book_index, "ROOT", tmp_path)

    entries = build_book_index.collect_entries()

    assert [entry["id"] for entry in entries] == ["book"]


def test_collect_entries_classifies_topical_schema_by_schema_type(monkeypatch, tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    _write_record(
        data_root / "reference" / "torrey.json",
        record_id="torrey",
        title="Torrey's Topical Textbook",
        schema_type="topical_reference",
    )
    monkeypatch.setattr(build_book_index, "DATA_DIR", data_root)
    monkeypatch.setattr(build_book_index, "ROOT", tmp_path)

    entries = build_book_index.collect_entries()

    assert entries[0]["category"] == "topical-reference"


def test_live_index_entries_match_authoritative_work_units() -> None:
    entries = build_book_index.collect_entries()

    assert len(entries) == 402
    assert sum(entry["title"] == "The Catholic Encyclopedia" for entry in entries) == 1
