from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

import jsonschema
import pytest

from build.tei.check_ledger import check_receipt
from build.tei.project_hf import project_file

REPO_ROOT = Path(__file__).resolve().parents[1]
BCP_RENDERINGS = ("bcp-1549", "bcp-1559", "bcp-1662")


def _speech_fixture(path: Path) -> None:
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <titleStmt><title>Speaker fixture</title><author>Fixture Author</author></titleStmt>
      <sourceDesc><bibl><ptr target="https://example.test/source"/></bibl></sourceDesc>
    </fileDesc>
  </teiHeader>
  <text><body><div type="service" xml:id="service">
    <head>Service</head>
    <sp xml:id="sp-priest"><speaker>Priest</speaker><p>Unique priest line.</p></sp>
    <sp xml:id="sp-answer"><speaker>Answer</speaker><p>Unique answer response.</p></sp>
    <sp xml:id="sp-minister"><speaker>Minister</speaker><p>Unique minister line.</p></sp>
    <sp xml:id="sp-people"><speaker>People</speaker><p>Unique people response.</p></sp>
  </div></body></text>
</TEI>
""",
        encoding="utf-8",
    )


def _nested_speech_fixture(path: Path) -> None:
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader><fileDesc>
    <titleStmt><title>Nested speaker fixture</title><author>Fixture Author</author></titleStmt>
    <sourceDesc><bibl><ptr target="https://example.test/source"/></bibl></sourceDesc>
  </fileDesc></teiHeader>
  <text><body><div type="chapter" xml:id="chapter">
    <head>Nested wrapper</head>
    <quote>Before <q>aside <sp xml:id="nested-sp"><speaker>Narrator</speaker><p>Nested words.</p></sp> after.</q></quote>
  </div></body></text>
</TEI>
""",
        encoding="utf-8",
    )


def _project_fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, Any]]:
    tei_path = tmp_path / "ir" / "fixture" / "speaker-fixture.test.tei.xml"
    output_path = tmp_path / "ir" / "fixture" / "hf" / "speaker-fixture.test.jsonl"
    receipt_path = output_path.with_suffix(output_path.suffix + ".loss.json")
    tei_path.parent.mkdir(parents=True)
    _speech_fixture(tei_path)
    project_file(tei_path, output_path, receipt_path=receipt_path, repo_root=tmp_path)
    record = json.loads(output_path.read_text(encoding="utf-8"))
    return output_path, receipt_path, record


def _write_output_and_refresh_hash(
    output_path: Path, receipt_path: Path, record: dict[str, Any]
) -> None:
    output_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["output"]["sha256"] = hashlib.sha256(output_path.read_bytes()).hexdigest()
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


def test_focused_speech_projection_preserves_flat_record_and_adds_ordered_roles(
    tmp_path: Path,
) -> None:
    _output_path, receipt_path, record = _project_fixture(tmp_path)

    assert record["id"] == "speaker-fixture/test/service"
    assert record["title_path"] == ["Speaker fixture", "Service"]
    assert record["text"] == (
        "Priest\nUnique priest line.\n\n"
        "Answer\nUnique answer response.\n\n"
        "Minister\nUnique minister line.\n\n"
        "People\nUnique people response."
    )
    assert [(item["speaker"], item["text"]) for item in record["speeches"]] == [
        ("Priest", "Unique priest line."),
        ("Answer", "Unique answer response."),
        ("Minister", "Unique minister line."),
        ("People", "Unique people response."),
    ]
    assert all(
        record["text"][item["char_start"] : item["char_end"]] == item["text"]
        for item in record["speeches"]
    )
    schema = json.loads(
        (REPO_ROOT / "schemas" / "v1" / "hf_clean_text.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.Draft202012Validator(schema).validate(record)
    assert check_receipt(receipt_path, repo_root=tmp_path) == []


def test_nested_wrapper_speech_is_owned_structured_and_strictly_verified(
    tmp_path: Path,
) -> None:
    tei_path = tmp_path / "ir" / "fixture" / "nested-speaker.test.tei.xml"
    output_path = tmp_path / "ir" / "fixture" / "hf" / "nested-speaker.test.jsonl"
    receipt_path = output_path.with_suffix(output_path.suffix + ".loss.json")
    tei_path.parent.mkdir(parents=True)
    _nested_speech_fixture(tei_path)

    receipt = project_file(
        tei_path, output_path, receipt_path=receipt_path, repo_root=tmp_path
    )
    record = json.loads(output_path.read_text(encoding="utf-8"))

    assert record["id"] == "nested-speaker/test/chapter"
    assert record["title_path"] == ["Nested speaker fixture", "Nested wrapper"]
    assert record["text"] == "Before aside NarratorNested words. after."
    assert record["speeches"] == [
        {
            "speaker": "Narrator",
            "text": "Nested words.",
            "char_start": 21,
            "char_end": 34,
        }
    ]
    speech_entry = next(node for node in receipt["nodes"] if node["address"] == "nested-sp")
    assert {target["field"] for target in speech_entry["targets"]} == {
        "text",
        "speeches",
    }
    assert check_receipt(receipt_path, repo_root=tmp_path) == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda record: record["speeches"][0].update({"speaker": "Minister"}),
        lambda record: record["speeches"].__setitem__(
            slice(0, 2), [record["speeches"][1], record["speeches"][0]]
        ),
        lambda record: record["speeches"].pop(1),
        lambda record: record["speeches"][0].update({"char_start": 0}),
    ],
    ids=["wrong-role", "reordered", "missing", "corrupt-flat-span"],
)
def test_strict_checker_rejects_corrupted_speech_output(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], None]
) -> None:
    output_path, receipt_path, record = _project_fixture(tmp_path)
    mutate(record)
    _write_output_and_refresh_hash(output_path, receipt_path, record)

    errors = check_receipt(receipt_path, repo_root=tmp_path)

    assert errors
    assert any("speeches" in error or "target" in error for error in errors)


def test_strict_checker_rejects_speaker_target_at_wrong_array_index(tmp_path: Path) -> None:
    _output_path, receipt_path, _record = _project_fixture(tmp_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    speaker = next(node for node in receipt["nodes"] if node["address"] == "sp-priest/speaker[1]")
    nested_target = next(target for target in speaker["targets"] if target["field"] == "speeches")
    nested_target["item_index"] = 1
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    errors = check_receipt(receipt_path, repo_root=tmp_path)

    assert any("target set mismatch" in error for error in errors)


@pytest.mark.parametrize(
    ("rendering", "expected_count"),
    [("bcp-1549", 124), ("bcp-1559", 137), ("bcp-1662", 233)],
)
def test_committed_bcp_speech_census(rendering: str, expected_count: int) -> None:
    path = REPO_ROOT / "ir" / "bcp" / "hf" / f"book-of-common-prayer.{rendering}.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    schema = json.loads(
        (REPO_ROOT / "schemas" / "v1" / "hf_clean_text.schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert sum(len(record.get("speeches", [])) for record in records) == expected_count
    for record in records:
        jsonschema.Draft202012Validator(schema).validate(record)


def test_bcp_1559_communion_preserves_all_roles_and_representative_pairs() -> None:
    path = REPO_ROOT / "ir" / "bcp" / "hf" / "book-of-common-prayer.bcp-1559.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    communion = next(
        record
        for record in records
        if record["id"]
        == "book-of-common-prayer/bcp-1559/bcp-bcp-1559-communion-1559"
    )
    speeches = communion["speeches"]

    assert len(speeches) == 24
    assert [item["speaker"] for item in speeches] == ["Minister", "People"] * 10 + [
        "Answer",
        "Priest",
        "Answer",
        "Priest",
    ]
    pairs = {(item["speaker"], item["text"]) for item in speeches}
    assert any(role == "Minister" and text.startswith("God spake these wordes") for role, text in pairs)
    assert any(role == "People" and text.startswith("Lorde have mercye upon us") for role, text in pairs)
    assert ("Answer", "We lyfte them up unto the Lorde.") in pairs
    assert ("Priest", "Let us geve thanckes unto our Lorde God.") in pairs


def test_committed_fisher_projection_has_all_source_faithful_roles() -> None:
    path = (
        REPO_ROOT
        / "ir"
        / "fisher"
        / "hf"
        / "fisher-marrow-of-modern-divinity.ia-ocr.jsonl"
    )
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    speeches = [item for record in records for item in record.get("speeches", [])]

    assert len(speeches) == 455
    assert {"Evan.", "Norn.", "iVeo."} <= {item["speaker"] for item in speeches}
