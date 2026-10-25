"""Focused behavior contracts for previously unmapped shared helpers.

These tests stay local and deterministic.  They exercise public helper behavior,
consumer-facing outputs, and documented failure cases without touching retained
source, canonical data, or network state.
"""

from __future__ import annotations

import ast
import json
import urllib.error
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from lxml import etree
from requests.exceptions import HTTPError as RequestsHTTPError

from build.lib.contributors import as_contributor, normalize_contributors
from build.lib.pdf_normalizer import normalise
from build.lib.pdf_quality_gate import run_quality_gate
from build.lib.scripture_canon import all_osis_books, book_chapter_count, book_verse_count
from build.lib.sidecar_migrations import (
    MigrationError,
    chain,
    is_single_step,
    upgrade,
    validate_registry,
)
from build.tei.ccel_work_config import (
    ccel_division_rule,
    ccel_rule_matches,
    ccel_scope_label,
    load_ccel_work_config,
    select_ccel_scope,
)
from ocd_kernel.lib import ia_fetch, python_dependencies
from ocd_kernel.lib.lang_classifier import classify_block
from ocd_kernel.lib.lexicons import de, fr


def test_contributor_normalization_preserves_objects_and_rejects_unknown_values() -> None:
    existing = {"name": "Jane Doe", "role": "translator"}

    assert as_contributor(existing) is existing
    assert normalize_contributors(["Jane Doe", existing]) == [
        {"name": "Jane Doe"},
        existing,
    ]
    assert normalize_contributors([]) == []

    with pytest.raises(TypeError, match=r"Expected str or dict"):
        normalize_contributors(["valid", 42])


def test_pdf_normalizer_applies_configured_transforms_in_order() -> None:
    raw = (
        "```python\n"
        "code()\n"
        "```\n\n"
        "`quoted`\n\n"
        "HEADER\n\n"
        "HEADER\n\n"
        "HEADER\n\n"
        "PSALM ONE\n\n"
        "42\n\n"
        "Theo-\n"
        "logy\n\n"
        "Lord3\n"
    )

    cleaned = normalise(
        raw,
        {
            "strip_headers_footers": True,
            "regex_headings": [{"pattern": r"^PSALM", "level": 1}],
        },
    )

    assert cleaned == "code()\n\nquoted\n\n# PSALM ONE\n\nTheology\n\nLord\n"


def test_pdf_normalizer_can_leave_repeated_headers_untouched() -> None:
    raw = "HEADER\n\nHEADER\n\nHEADER\n"

    assert normalise(raw, {"strip_headers_footers": False}) == raw


def test_pdf_quality_gate_reports_empty_and_sparse_pages() -> None:
    warnings = run_quality_gate(
        "short",
        {
            "text_layer": {"total_pages": 6, "empty_pages": [2]},
            "pages_processed": 6,
        },
        {},
    )

    by_code = {warning.split(" ", 1)[0]: warning for warning in warnings}
    assert "CHECK-1" in by_code
    assert "1/6 pages" in by_code["CHECK-1"]
    assert "CHECK-2" in by_code
    assert "low_density" in by_code["CHECK-2"]


def test_pdf_quality_gate_reports_structural_anomalies_and_ocr_exception() -> None:
    repeated_block = "x" * 201
    repeated = "\n\n\n".join([repeated_block] * 3)
    repeated_warnings = run_quality_gate(
        repeated,
        {"text_layer": {"total_pages": 3}, "pages_processed": 3},
        {},
    )
    assert any(warning.startswith("CHECK-5 repeated_content") for warning in repeated_warnings)

    replacement_warnings = run_quality_gate(
        "�" * 3 + "ok",
        {"text_layer": {"total_pages": 1}, "pages_processed": 1},
        {},
    )
    assert any(warning.startswith("CHECK-4 encoding_anomaly") for warning in replacement_warnings)

    heading_warnings = run_quality_gate(
        "body",
        {"text_layer": {"total_pages": 50}, "pages_processed": 50},
        {},
    )
    assert any(warning.startswith("CHECK-3 no_headings") for warning in heading_warnings)

    ocr_warnings = run_quality_gate(
        "body",
        {"text_layer": {"total_pages": 50}, "pages_processed": 50, "ocr_mode": True},
        {},
    )
    assert not any(warning.startswith("CHECK-3") for warning in ocr_warnings)


def test_scripture_canon_exposes_ordered_counts_and_rejects_unknown_bounds() -> None:
    books = all_osis_books()

    assert len(books) == 66
    assert books[0] == "Gen"
    assert books[-1] == "Rev"
    assert book_chapter_count("2John") == 1
    assert book_verse_count("2John", 1) == 13

    with pytest.raises(ValueError, match="Unknown OSIS book id"):
        book_chapter_count("Tob")
    with pytest.raises(ValueError, match="chapter must be >= 1"):
        book_verse_count("2John", 0)
    with pytest.raises(ValueError, match="Unknown chapter"):
        book_verse_count("2John", 2)


def test_sidecar_migrations_chain_single_steps_without_mutating_input() -> None:
    registry = {
        ("1.0.0", "1.0.1"): lambda sidecar: {**sidecar, "patch_applied": True},
        ("1.0.1", "1.1.0"): lambda sidecar: {**sidecar, "minor_applied": True},
    }
    original = {"schema_version": "1.0.0", "record": "sample"}

    assert chain("1.0.0", "1.1.0", migrations=registry) == [
        ("1.0.0", "1.0.1"),
        ("1.0.1", "1.1.0"),
    ]
    upgraded = upgrade(original, target_version="1.1.0", migrations=registry)

    assert upgraded == {
        "schema_version": "1.1.0",
        "record": "sample",
        "patch_applied": True,
        "minor_applied": True,
    }
    assert original == {"schema_version": "1.0.0", "record": "sample"}
    current_copy = upgrade(original)
    assert current_copy == original
    assert current_copy is not original


def test_sidecar_migrations_reject_invalid_registry_and_downgrades() -> None:
    assert is_single_step("1.0.0", "1.0.1")
    assert is_single_step("1.0.0", "1.1.0")
    assert is_single_step("1.0.0", "2.0.0")
    assert not is_single_step("1.0.0", "1.2.0")

    with pytest.raises(MigrationError, match="not a single-step bump"):
        validate_registry({("1.0.0", "1.2.0"): lambda sidecar: dict(sidecar)})
    with pytest.raises(MigrationError, match="missing schema_version"):
        upgrade({})
    with pytest.raises(MigrationError, match="downgrade is not supported"):
        upgrade({"schema_version": "2.0.0"}, target_version="1.0.0")
    with pytest.raises(MigrationError, match="no migration path"):
        upgrade({"schema_version": "1.0.0"}, target_version="1.1.0", migrations={})


def _write_ccel_config(tmp_path: Any) -> tuple[Any, Any]:
    raw_path = tmp_path / "raw.xml"
    raw_path.write_text(
        "<root><div1 id='work'><div2 id='chapter' type='Chapter' title='Chapter'>"
        "<p>Text</p></div2><div2 id='preface' type='Preface' title='Preface'/></div1></root>",
        encoding="utf-8",
    )
    config_path = tmp_path / "ccel_work_configs.json"
    config_path.write_text(
        json.dumps(
            {
                "works": [
                    {
                        "work_id": "sample-work",
                        "rendering_id": "sample-rendering",
                        "raw_path": "raw.xml",
                        "scope": {"tag": "div1", "id": "work"},
                        "title": "Sample Work",
                        "author": "Sample Author",
                        "contributors": ["Sample Translator"],
                        "source_url": "https://example.test/sample.xml",
                        "source_hash": "sha256:sample",
                        "source_edition": "Sample edition",
                        "division_rules": [
                            {"tag": "div2", "source_type": "Chapter", "tei_type": "chapter", "place": "body"},
                            {"tag": "div2", "source_type": "Preface", "skip": True},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return config_path, raw_path


def test_ccel_work_config_loads_scope_rules_and_fallbacks(tmp_path: Any) -> None:
    config_path, raw_path = _write_ccel_config(tmp_path)
    config = load_ccel_work_config(config_path, "sample-work", repo_root=tmp_path)
    root = etree.parse(str(raw_path)).getroot()
    scope = select_ccel_scope(root, config)
    chapter = scope.find("div2")
    assert chapter is not None

    assert config.raw_path == raw_path
    assert config.contributors == ["Sample Translator"]
    assert scope.get("id") == "work"
    assert ccel_scope_label(config) == "div1[@id='work']"
    assert ccel_rule_matches(
        {"tag": "div2", "source_type": "Chapter", "title": "Chapter"},
        chapter,
    )
    assert not ccel_rule_matches({"tag": "div2", "source_type": "Preface"}, chapter)
    assert ccel_division_rule(chapter, config.division_rules)["tei_type"] == "chapter"
    assert ccel_division_rule(etree.Element("div2", type="Appendix"), config.division_rules) == {
        "tei_type": "appendix",
        "place": "body",
    }

    with pytest.raises(ValueError, match="No CCEL work config"):
        load_ccel_work_config(config_path, "missing-work", repo_root=tmp_path)
    with pytest.raises(ValueError, match="No div1 with id"):
        select_ccel_scope(root, replace(config, scope={"tag": "div1", "id": "missing"}))
    with pytest.raises(ValueError, match="must declare scope tag and id"):
        select_ccel_scope(root, replace(config, scope={}))


def test_ia_fetch_selects_jp2_and_parses_retry_after_without_network() -> None:
    files = etree.fromstring(
        "<files><file name='01.sample._jp2.zip'/><file name='02.sample._jp2.zip'/></files>"
    )
    assert ia_fetch.find_jp2_zip(files, 2) == "02.sample._jp2.zip"
    assert ia_fetch.find_jp2_zip(etree.fromstring("<files><file name='only._jp2.zip'/></files>"), 9) == "only._jp2.zip"
    with pytest.raises(ValueError, match="No JP2 ZIP"):
        ia_fetch.find_jp2_zip(etree.fromstring("<files><file name='01.txt'/></files>"), 1)

    assert ia_fetch._parse_retry_after("") == 5
    assert ia_fetch._parse_retry_after(" 30 ") == 30
    assert ia_fetch._parse_retry_after("not-a-date") == ia_fetch.MAX_RETRY_AFTER + 1


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def read(self) -> bytes:
        return self.payload


def test_ia_fetch_url_retries_rate_limit_and_server_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    rate_limit = urllib.error.HTTPError("https://example.test", 429, "rate limited", {"Retry-After": "0"}, None)
    server_error = urllib.error.HTTPError("https://example.test", 503, "unavailable", {}, None)
    responses = iter([rate_limit, server_error, _FakeResponse(b"ok")])
    sleeps: list[int] = []

    def fake_urlopen(_request: object, timeout: int) -> _FakeResponse:
        assert timeout == 7
        outcome = next(responses)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(ia_fetch.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(ia_fetch.time, "sleep", sleeps.append)

    assert ia_fetch.fetch_url_bytes("https://example.test", {"Accept": "image"}, timeout=7) == b"ok"
    assert sleeps == [0, 4]


def test_ia_fetch_aborts_excessive_retry_after_and_retries_remote_zip(monkeypatch: pytest.MonkeyPatch) -> None:
    excessive = urllib.error.HTTPError(
        "https://example.test", 429, "rate limited", {"Retry-After": "301"}, None
    )
    monkeypatch.setattr(ia_fetch.urllib.request, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(excessive))
    with pytest.raises(RuntimeError, match="exceeds maximum"):
        ia_fetch.fetch_url_bytes("https://example.test", {})

    transient = RequestsHTTPError("temporary")
    transient.response = SimpleNamespace(status_code=503)
    outcomes: list[object] = [transient, b"jp2-bytes"]
    sleeps: list[int] = []

    def fake_remote_zip(*_args: object, **_kwargs: object) -> bytes:
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(ia_fetch, "_open_remote_zip", fake_remote_zip)
    monkeypatch.setattr(ia_fetch.time, "sleep", sleeps.append)
    assert ia_fetch._download_jp2("zip", "01.jp2", {}, max_retries=2) == b"jp2-bytes"
    assert sleeps == [2]


def test_python_import_discovery_walks_nested_function_and_match_bodies() -> None:
    tree = ast.parse(
        "import os\n"
        "from pathlib import Path\n"
        "\n"
        "def load():\n"
        "    import json\n"
        "\n"
        "match 1:\n"
        "    case _:\n"
        "        import re\n"
    )

    nodes = list(python_dependencies.iter_python_imports(tree))
    assert [(type(node).__name__, node.lineno) for node in nodes] == [
        ("Import", 1),
        ("ImportFrom", 2),
        ("Import", 5),
        ("Import", 9),
    ]
    assert list(python_dependencies.iter_python_imports(ast.parse("value = 1"))) == []


def test_german_lexicon_is_consumed_by_layer2_language_classifier() -> None:
    assert de.COVERAGE_STATUS == "v1_floor"
    assert "Gnade" in de.VOCAB

    result = classify_block("Die Gnade Gottes und die Kirche haben Frieden", "commentary")

    assert result["language"] == "de"
    assert result["chosen_layer"] == "layer2"
    assert result["language_confidence"] >= 0.60


def test_french_lexicon_is_consumed_by_layer2_language_classifier() -> None:
    assert fr.COVERAGE_STATUS == "v1_floor"
    assert "grâce" in fr.VOCAB

    result = classify_block("La grâce de Dieu et la prière de l'Église", "commentary")

    assert result["language"] == "fr"
    assert result["chosen_layer"] == "layer2"
    assert result["language_confidence"] >= 0.60
