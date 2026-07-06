from __future__ import annotations

import json
import shutil
from pathlib import Path

import jsonschema
import pytest

from build.tei.check_ledger import check_receipt
from build.tei.project_hf import project_file

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "loss_receipt.schema.json"
REAL_TEI = [
    REPO_ROOT / "ir" / "augustine" / "city-of-god.ccel-npnf102.tei.xml",
    REPO_ROOT / "ir" / "augustine" / "city-of-god.standard-ebooks.tei.xml",
]


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

    receipt = project_file(tei_path, out_path, receipt_path=receipt_path, repo_root=tmp_path)
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

    nodes_by_address = {node["address"]: node for node in receipt["nodes"]}
    assert nodes_by_address["n1"]["disposition"] == "dropped"
    assert nodes_by_address["p1/pb[1]"]["disposition"] == "dropped"
    assert nodes_by_address["p1/ref[1]"]["disposition"] == "normalized"
    assert nodes_by_address["p1/ref[1]"]["note"] == "cRef annotation removed, text kept"
    assert nodes_by_address["chapter-1/head[1]"]["note"] == "head->title_path"
    assert receipt["totals"]["addressable_nodes"] == len(receipt["nodes"])
    assert receipt_path.exists()


def test_loss_receipt_schema_accepts_projector_output(tmp_path: Path) -> None:
    tei_path = tmp_path / "ir" / "augustine" / "city-of-god.standard-ebooks.tei.xml"
    out_path = tmp_path / "ir" / "augustine" / "hf" / "city-of-god.standard-ebooks.jsonl"
    tei_path.parent.mkdir(parents=True)
    _fixture(tei_path)

    receipt = project_file(tei_path, out_path, repo_root=tmp_path)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    jsonschema.validate(receipt, schema)


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
