from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest

import build.tei.project_hf as projector_module

from ocd_kernel.lib.schema_enums import resolve_schema_path
from build.tei.check_ledger import check_receipt
from build.tei.project_hf import project_file

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = resolve_schema_path("loss_receipt_v2")
REAL_TEI = [
    REPO_ROOT / "ir" / "augustine" / "city-of-god.ccel-npnf102.tei.xml",
    REPO_ROOT / "ir" / "augustine" / "city-of-god.standard-ebooks.tei.xml",
]


def test_projector_exposes_only_current_internal_traversal_names() -> None:
    assert not hasattr(projector_module, "clean_text")
    assert not hasattr(projector_module, "_text_blocks")


def _fixture(path: Path) -> None:
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <titleStmt>
        <title>The City of God</title>
        <author>Augustine of Hippo</author>
        <respStmt><resp>Translator</resp><name>Marcus Dods</name></respStmt>
      </titleStmt>
      <sourceDesc>
        <bibl><ptr target="https://example.test/source"/></bibl>
      </sourceDesc>
    </fileDesc>
  </teiHeader>
  <text>
    <front>
      <div type="title" xml:id="titlepage"><head>Publisher wrapper</head><p>Dropped title.</p></div>
      <div type="preface" xml:id="preface"><head>Translator's Preface</head><p>Projected preface.</p></div>
    </front>
    <body>
      <div type="book" xml:id="book-1">
        <head>Book
          I</head>
        <div type="chapter" xml:id="chapter-1">
          <head>Chapter
            Head</head>
          <argument><p>Chapter
            argument.</p></argument>
          <p xml:id="p1">Clean <hi rend="italic">faithful</hi> text <ref type="scripture" cRef="John.1.1">John i. 1</ref>.<note xml:id="n1">Dropped note.</note><pb n="1"/></p>
          <p xml:id="p2"><quote><lg><l>Line one</l><l>Line two</l></lg></quote></p>
        </div>
      </div>
    </body>
  </text>
</TEI>
""",
        encoding="utf-8",
    )


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_project_hf_writes_clean_text_and_loss_receipt(tmp_path: Path) -> None:
    tei_path = tmp_path / "ir" / "augustine" / "city-of-god.ccel-npnf102.tei.xml"
    out_path = tmp_path / "ir" / "augustine" / "hf" / "city-of-god.ccel-npnf102.jsonl"
    receipt_path = out_path.with_suffix(out_path.suffix + ".loss.json")
    tei_path.parent.mkdir(parents=True)
    _fixture(tei_path)

    started_at = datetime.now(timezone.utc)
    receipt = project_file(tei_path, out_path, receipt_path=receipt_path, repo_root=tmp_path)
    finished_at = datetime.now(timezone.utc)
    records = _read_jsonl(out_path)

    assert [record["id"] for record in records] == [
        "city-of-god/ccel-npnf102/preface",
        "city-of-god/ccel-npnf102/chapter-1",
    ]
    assert records[0]["title_path"] == ["The City of God", "Translator's Preface"]
    assert records[0]["text"] == "Projected preface."
    assert records[1]["title_path"] == ["The City of God", "Book I", "Chapter Head"]
    assert records[1]["argument"] == "Chapter argument."
    assert records[1]["text"] == "Clean faithful text John i. 1.\n\nLine one\nLine two"
    assert records[1]["source"] == {
        "author": "Augustine of Hippo",
        "translator": "Marcus Dods",
        "source_url": "https://example.test/source",
        "license": "CC0",
    }
    assert all(record["language"] == "en" for record in records)
    generated_at = datetime.fromisoformat(
        receipt["projection"]["generated_at"].removesuffix("Z") + "+00:00"
    )
    assert receipt["projection"]["generated_at"].endswith("Z")
    assert generated_at.tzinfo == timezone.utc
    assert started_at <= generated_at <= finished_at

    nodes_by_address = {node["address"]: node for node in receipt["nodes"]}
    assert nodes_by_address["n1"]["disposition"] == "dropped"
    assert nodes_by_address["p1/pb[1]"]["disposition"] == "dropped"
    assert nodes_by_address["p1/ref[1]"]["disposition"] == "normalized"
    assert nodes_by_address["p1/ref[1]"]["reason_code"] == "normalize.ref.annotation-removed"
    assert nodes_by_address["chapter-1/head[1]"]["targets"][0]["field"] == "title_path"
    assert receipt["totals"]["addressable_nodes"] == len(receipt["nodes"])
    assert receipt_path.exists()


def test_project_hf_explicit_metadata_is_deterministic(tmp_path: Path) -> None:
    tei_path = tmp_path / "ir" / "augustine" / "city-of-god.demo.tei.xml"
    output_path = tmp_path / "ir" / "augustine" / "hf" / "city-of-god.demo.jsonl"
    receipt_path = output_path.with_suffix(output_path.suffix + ".loss.json")
    tei_path.parent.mkdir(parents=True)
    _fixture(tei_path)
    metadata = {
        "generated_at": "2026-08-30T01:02:03.456789Z",
        "language": "la",
        "license_id": "CC-BY-4.0",
    }

    receipt = project_file(
        tei_path,
        output_path,
        receipt_path=receipt_path,
        repo_root=tmp_path,
        **metadata,
    )
    first_output = output_path.read_bytes()
    first_receipt = receipt_path.read_bytes()
    records = _read_jsonl(output_path)

    assert receipt["projection"]["generated_at"] == metadata["generated_at"]
    assert all(record["language"] == metadata["language"] for record in records)
    assert all(record["source"]["license"] == metadata["license_id"] for record in records)

    project_file(
        tei_path,
        output_path,
        receipt_path=receipt_path,
        repo_root=tmp_path,
        **metadata,
    )

    assert output_path.read_bytes() == first_output
    assert receipt_path.read_bytes() == first_receipt


@pytest.mark.parametrize(
    "generated_at",
    [
        "",
        "2026-08-30",
        "2026-08-30 01:02:03Z",
        "2026-08-30T01:02:03+00:00",
        "2026-08-30T11:02:03+10:00",
        "2026-02-30T01:02:03Z",
        123,
    ],
)
def test_project_hf_rejects_invalid_explicit_generated_at(
    tmp_path: Path,
    generated_at: object,
) -> None:
    tei_path = tmp_path / "ir" / "augustine" / "city-of-god.demo.tei.xml"
    output_path = tmp_path / "ir" / "augustine" / "hf" / "city-of-god.demo.jsonl"
    tei_path.parent.mkdir(parents=True)
    _fixture(tei_path)

    with pytest.raises(ValueError, match="generated_at"):
        project_file(
            tei_path,
            output_path,
            repo_root=tmp_path,
            generated_at=generated_at,  # type: ignore[arg-type]
        )

    assert not output_path.exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("language", ""),
        ("language", "   "),
        ("language", None),
        ("language", 123),
        ("license_id", ""),
        ("license_id", "   "),
        ("license_id", None),
        ("license_id", 123),
    ],
)
def test_project_hf_rejects_blank_language_or_license(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    tei_path = tmp_path / "ir" / "augustine" / "city-of-god.demo.tei.xml"
    output_path = tmp_path / "ir" / "augustine" / "hf" / "city-of-god.demo.jsonl"
    tei_path.parent.mkdir(parents=True)
    _fixture(tei_path)

    with pytest.raises(ValueError, match=field):
        project_file(
            tei_path,
            output_path,
            repo_root=tmp_path,
            **{field: value},
        )

    assert not output_path.exists()


def test_loss_receipt_schema_accepts_projector_output(tmp_path: Path) -> None:
    tei_path = tmp_path / "ir" / "augustine" / "city-of-god.standard-ebooks.tei.xml"
    out_path = tmp_path / "ir" / "augustine" / "hf" / "city-of-god.standard-ebooks.jsonl"
    tei_path.parent.mkdir(parents=True)
    _fixture(tei_path)

    receipt = project_file(tei_path, out_path, repo_root=tmp_path)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    jsonschema.validate(receipt, schema)


def test_projector_rolls_back_output_when_receipt_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tei_path = tmp_path / "ir" / "augustine" / "city-of-god.demo.tei.xml"
    output_path = tmp_path / "ir" / "augustine" / "hf" / "city-of-god.demo.jsonl"
    receipt_path = output_path.with_suffix(output_path.suffix + ".loss.json")
    tei_path.parent.mkdir(parents=True)
    _fixture(tei_path)
    project_file(tei_path, output_path, receipt_path=receipt_path, repo_root=tmp_path)
    original_output = output_path.read_bytes()
    original_receipt = receipt_path.read_bytes()
    tei_path.write_bytes(
        tei_path.read_bytes().replace(b"Projected preface.", b"Changed preface.")
    )
    real_replace = os.replace

    def fail_receipt_replace(source: object, target: object) -> None:
        if Path(target) == receipt_path:
            raise OSError("injected receipt replace failure")
        real_replace(source, target)

    monkeypatch.setattr(projector_module.os, "replace", fail_receipt_replace)

    with pytest.raises(OSError, match="injected receipt replace failure"):
        project_file(
            tei_path,
            output_path,
            receipt_path=receipt_path,
            repo_root=tmp_path,
        )

    assert output_path.read_bytes() == original_output
    assert receipt_path.read_bytes() == original_receipt
    assert list(output_path.parent.glob(".*.tmp")) == []


@pytest.mark.slow
@pytest.mark.parametrize("tei_path", REAL_TEI)
def test_real_city_of_god_projection_receipts_pass_check_ledger(tmp_path: Path, tei_path: Path) -> None:
    if not tei_path.exists():
        pytest.skip(f"{tei_path.as_posix()} is absent; regenerate the committed TEI IR first.")
    temp_tei = tmp_path / "ir" / "augustine" / tei_path.name
    temp_tei.parent.mkdir(parents=True)
    shutil.copyfile(tei_path, temp_tei)
    output_path = tmp_path / "ir" / "augustine" / "hf" / tei_path.name.replace(".tei.xml", ".jsonl")
    receipt_path = output_path.with_suffix(output_path.suffix + ".loss.json")

    receipt = project_file(temp_tei, output_path, receipt_path=receipt_path, repo_root=tmp_path)
    errors = check_receipt(receipt_path, repo_root=tmp_path)
    records = _read_jsonl(output_path)

    assert errors == []
    assert len(records) > 600
    assert receipt["totals"]["addressable_nodes"] == len(receipt["nodes"])
