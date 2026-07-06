from __future__ import annotations

import json
import re
from pathlib import Path

from lxml import etree

from build.tei.check_je_ledger import check_receipt
from build.tei.project_je_hf import project_file

REPO_ROOT = Path(__file__).resolve().parents[1]
TEI_NS = "http://www.tei-c.org/ns/1.0"
NS = {"tei": TEI_NS}


def _project_synthetic(tmp_path: Path) -> tuple[Path, dict]:
    tei_path = tmp_path / "ir" / "je" / "synthetic.tei.xml"
    tei_path.parent.mkdir(parents=True)
    tei_path.write_text(
        """<?xml version='1.0' encoding='UTF-8'?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <text>
    <body>
      <ab>
        <w xml:id="w_synthetic_0001"><app><lem>alpha-one</lem><rdg>alpha</rdg></app></w>
        <w xml:id="w_synthetic_0002"><app><lem>bravo-two</lem><rdg>bravo</rdg></app></w>
        <w xml:id="w_synthetic_0003"><app><lem>charlie-three</lem><rdg>charlie</rdg></app></w>
      </ab>
    </body>
  </text>
</TEI>
""",
        encoding="utf-8",
    )
    output_path = tmp_path / "hf" / "synthetic.jsonl"
    receipt_path = tmp_path / "hf" / "synthetic.loss.json"
    receipt = project_file(tei_path, output_path, receipt_path=receipt_path, repo_root=tmp_path)
    return receipt_path, receipt


def _write_receipt(path: Path, receipt: dict) -> None:
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_record(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8").splitlines()[0])


def _write_record(path: Path, record: dict) -> None:
    path.write_text(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def _projected_nodes(receipt: dict) -> list[dict]:
    return [
        node
        for node in receipt["nodes"]
        if node["element"] == "lem" and node["target"]["char_end"] > node["target"]["char_start"]
    ]


def _lemma_texts(receipt: dict, repo_root: Path) -> list[str]:
    tree = etree.parse(str(repo_root / receipt["ir"]["path"]))
    lemmas = tree.xpath("/tei:TEI/tei:text//tei:lem", namespaces=NS)
    return [re.sub(r"\s+", " ", "".join(lemma.itertext())).strip() for lemma in lemmas]


def test_check_je_ledger_passes_faithful_synthetic_projection(tmp_path: Path) -> None:
    receipt_path, _receipt = _project_synthetic(tmp_path)

    assert check_receipt(receipt_path, repo_root=tmp_path) == []


def test_check_je_ledger_rejects_unclaimed_output_between_shifted_spans(tmp_path: Path) -> None:
    receipt_path, receipt = _project_synthetic(tmp_path)
    projected = _projected_nodes(receipt)
    insertion = "GARBAGE_INJECTED "
    insert_at = projected[0]["target"]["char_end"]
    output_path = tmp_path / receipt["output"]["path"]
    record = _read_record(output_path)
    record["text"] = record["text"][:insert_at] + insertion + record["text"][insert_at:]
    for node in projected[1:]:
        target = node["target"]
        if target["char_start"] >= insert_at:
            target["char_start"] += len(insertion)
            target["char_end"] += len(insertion)
    _write_record(output_path, record)
    _write_receipt(receipt_path, receipt)

    errors = check_receipt(receipt_path, repo_root=tmp_path)

    assert any("output text mismatch" in error for error in errors)


def test_check_je_ledger_rejects_reversed_output_with_repointed_spans(tmp_path: Path) -> None:
    receipt_path, receipt = _project_synthetic(tmp_path)
    texts = _lemma_texts(receipt, tmp_path)
    reversed_texts = list(reversed(texts))
    reversed_output = " ".join(reversed_texts)
    offsets: dict[str, tuple[int, int]] = {}
    cursor = 0
    for text in reversed_texts:
        offsets[text] = (cursor, cursor + len(text))
        cursor += len(text) + 1
    for node, text in zip(_projected_nodes(receipt), texts, strict=True):
        start, end = offsets[text]
        node["target"]["char_start"] = start
        node["target"]["char_end"] = end
    output_path = tmp_path / receipt["output"]["path"]
    record = _read_record(output_path)
    record["text"] = reversed_output
    _write_record(output_path, record)
    _write_receipt(receipt_path, receipt)

    errors = check_receipt(receipt_path, repo_root=tmp_path)

    assert any("output text mismatch" in error for error in errors)


