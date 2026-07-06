from __future__ import annotations

import json
from pathlib import Path

import pytest

from build.tei.check_ledger import check_receipt
from build.tei.project_hf import project_file


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
      <sourceDesc><bibl><ptr target="https://example.test/source"/></bibl></sourceDesc>
    </fileDesc>
  </teiHeader>
  <text>
    <body>
      <div type="chapter" xml:id="chapter-1">
        <head>Head</head>
        <argument><p>Argument text.</p></argument>
        <p xml:id="p1">Alpha <hi rend="italic">beta</hi>.</p>
        <p xml:id="p2">Gamma <note xml:id="n1">Note text.</note></p>
      </div>
    </body>
  </text>
</TEI>
""",
        encoding="utf-8",
    )


def _project(tmp_path: Path) -> tuple[Path, dict]:
    tei_path = tmp_path / "ir" / "augustine" / "city-of-god.ccel-npnf102.tei.xml"
    out_path = tmp_path / "ir" / "augustine" / "hf" / "city-of-god.ccel-npnf102.jsonl"
    receipt_path = out_path.with_suffix(out_path.suffix + ".loss.json")
    tei_path.parent.mkdir(parents=True)
    _fixture(tei_path)
    receipt = project_file(tei_path, out_path, receipt_path=receipt_path, repo_root=tmp_path)
    return receipt_path, receipt


def _write(path: Path, receipt: dict) -> None:
    path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")


def test_check_ledger_passes_projector_receipt(tmp_path: Path) -> None:
    receipt_path, _receipt = _project(tmp_path)

    assert check_receipt(receipt_path, repo_root=tmp_path) == []


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda receipt: receipt["nodes"].pop(),
            "missing ledger node",
        ),
        (
            lambda receipt: receipt["nodes"][0]["target"].update({"char_start": 0, "char_end": 1}),
            "span mismatch",
        ),
        (
            lambda receipt: receipt["output"].update({"path": "ir/augustine/hf/missing.jsonl"}),
            "output path does not exist",
        ),
    ],
)
def test_check_ledger_catches_corrupted_ledgers(tmp_path: Path, mutate, message: str) -> None:
    receipt_path, receipt = _project(tmp_path)
    mutate(receipt)
    _write(receipt_path, receipt)

    errors = check_receipt(receipt_path, repo_root=tmp_path)

    assert any(message in error for error in errors)


def test_check_ledger_catches_orphan_output_record(tmp_path: Path) -> None:
    receipt_path, receipt = _project(tmp_path)
    output_path = tmp_path / receipt["output"]["path"]
    with output_path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps({"id": "orphan", "text": "orphan"}) + "\n")

    errors = check_receipt(receipt_path, repo_root=tmp_path)

    assert any("orphan output record" in error for error in errors)
