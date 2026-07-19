from __future__ import annotations

import gzip
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from build.tools import export_stats


def _write_jsonl(path: Path, records: list[dict]) -> bytes:
    payload = "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records).encode("utf-8")
    path.write_bytes(payload)
    return payload


def test_token_count_uses_text_content_only(tmp_path: Path) -> None:
    path = tmp_path / "bible_text.jsonl"
    records = [
        {
            "_source_id": "metadata-that-must-not-count",
            "_source_url": "https://example.invalid/long-metadata-value",
            "_schema_type": "bible_text",
            "osis": "Gen.1.1",
            "chapter": 1,
            "verse": 1,
            "text": "In the beginning",
        },
        {
            "_source_id": "another-id",
            "_schema_type": "bible_text",
            "osis": "Gen.1.2",
            "chapter": 1,
            "verse": 2,
            "text": "God created",
        },
    ]
    payload = _write_jsonl(path, records)
    encoding = importlib.import_module("tiktoken").get_encoding("o200k_base")

    stats = export_stats.count_file(path, encoding, "bible_text")

    assert stats["records"] == 2
    assert stats["tokens"] == sum(len(encoding.encode(record["text"], disallowed_special=())) for record in records)
    assert stats["uncompressed_bytes"] == len(payload)


def test_metadata_and_json_scaffolding_do_not_change_token_count(tmp_path: Path) -> None:
    path = tmp_path / "bible_text.jsonl"
    base = {
        "_schema_type": "bible_text",
        "osis": "Gen.1.1",
        "chapter": 1,
        "verse": 1,
        "text": "A short text.",
    }
    decorated = {
        **base,
        "_source_id": "an extraordinarily long identifier that must be excluded",
        "_source_title": "A title that must be excluded",
        "_author": "An author that must be excluded",
        "_contributors": ["A contributor that must be excluded"],
        "_license": "a license that must be excluded",
        "_source_url": "https://example.invalid/metadata-that-must-be-excluded",
    }
    encoding = importlib.import_module("tiktoken").get_encoding("o200k_base")
    _write_jsonl(path, [decorated])

    stats = export_stats.count_file(path, encoding, "bible_text")

    assert stats["tokens"] == len(encoding.encode(base["text"], disallowed_special=()))


def test_gzip_size_is_reported_without_creating_gzip_artifact(tmp_path: Path) -> None:
    path = tmp_path / "bible_text.jsonl"
    payload = _write_jsonl(
        path,
        [{"_schema_type": "bible_text", "text": "repeated text " * 20}],
    )
    encoding = importlib.import_module("tiktoken").get_encoding("o200k_base")

    stats = export_stats.count_file(path, encoding, "bible_text")

    assert stats["uncompressed_bytes"] == len(payload)
    assert stats["gzip_bytes"] == len(gzip.compress(payload, mtime=0))
    assert not path.with_suffix(path.suffix + ".gz").exists()


def test_missing_tiktoken_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import_module = export_stats.importlib.import_module

    def fail_tiktoken(name: str, package: str | None = None):
        if name == "tiktoken":
            raise ModuleNotFoundError("No module named 'tiktoken'")
        return real_import_module(name, package)

    monkeypatch.setattr(export_stats.importlib, "import_module", fail_tiktoken)

    with pytest.raises(RuntimeError, match="tiktoken is required"):
        export_stats.load_encoding("o200k_base")


def test_reference_entry_uses_canonical_text_extractor() -> None:
    record = {
        "_schema_type": "reference_entry",
        "_source_id": "dictionary",
        "entry_id": "aaron",
        "term": "Aaron",
        "alt_terms": ["Aharon"],
        "definition_blocks": ["First definition.", {"text": "Second definition."}],
    }

    assert export_stats.record_texts(record) == [
        "Aaron",
        "Aharon",
        "First definition.",
        "Second definition.",
    ]


def test_nested_catechism_and_topical_fields_are_selected() -> None:
    catechism = {
        "_schema_type": "catechism_qa",
        "question": "Main question?",
        "answer": "Main answer.",
        "sub_questions": [{"question": "Sub-question?", "answer": "Sub-answer."}],
    }
    topical = {
        "_schema_type": "topical_reference",
        "topic": "Faith",
        "alt_topics": ["Belief"],
        "related_topics": ["Hope"],
        "subtopics": [{"label": "Saving faith"}],
    }

    assert export_stats.record_texts(catechism) == [
        "Main question?",
        "Main answer.",
        "Sub-question?",
        "Sub-answer.",
    ]
    assert export_stats.record_texts(topical) == [
        "Faith",
        "Belief",
        "Hope",
        "Saving faith",
    ]


def test_content_blocks_and_malformed_nested_objects() -> None:
    assert export_stats.record_texts(
        {
            "_schema_type": "sermon",
            "content_blocks": ["Opening.", {"text": "Body."}],
        }
    ) == ["Opening.", "Body."]

    with pytest.raises(ValueError, match="without a text field"):
        export_stats.record_texts(
            {"_schema_type": "sermon", "content_blocks": [{"kind": "paragraph"}]}
        )


def test_parity_mismatches_compare_all_configurations(monkeypatch: pytest.MonkeyPatch) -> None:
    from build.tools import count_dataset_records

    monkeypatch.setattr(
        count_dataset_records,
        "collect_work_catalog",
        lambda: SimpleNamespace(
            summary={"legacy_hf_export_records_by_schema": {"bible_text": 2, "sermon": 4}}
        ),
    )
    stats = {
        "configurations": [
            {"configuration": "bible_text", "records": 2},
            {"configuration": "sermon", "records": 3},
        ]
    }

    assert export_stats.parity_mismatches(stats) == [("sermon", 3, 4)]
