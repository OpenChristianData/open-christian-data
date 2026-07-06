"""Project JE apparatus TEI into HF clean text plus a loss-receipt ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import jsonschema
from lxml import etree

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.paths import REPO_ROOT
from build.tei.writer import TEI_NS, derive_address

NS = {"tei": TEI_NS}
PROJECTION_ID = "je-hf-clean-text-v1"
GENERATOR = "build/tei/project_je_hf.py"
DEFAULT_WORK_ID = "jewish-encyclopedia.vol_02"
LANGUAGE = "en"
SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "loss_receipt.schema.json"
DROPPED_ELEMENTS = frozenset({"rdg", "note", "pb"})
NORMALIZED_ELEMENTS = frozenset({"text", "body", "ab", "w", "app"})


@dataclass(frozen=True)
class Span:
    record_id: str
    start: int
    end: int


def _local(node: etree._Element) -> str:
    return etree.QName(node).localname


def _repo_relative(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _clean_text(node: etree._Element) -> str:
    return _collapse_whitespace("".join(node.itertext()))


def _page_id(tei_path: Path, tree: etree._ElementTree) -> str:
    pb = tree.find(".//tei:pb", namespaces=NS)
    if pb is not None:
        pb_id = pb.get(f"{{http://www.w3.org/XML/1998/namespace}}id")
        if pb_id and pb_id.startswith("pb_"):
            return pb_id.removeprefix("pb_")
    suffix = ".tei.xml"
    if tei_path.name.endswith(suffix):
        return tei_path.name.removesuffix(suffix)
    return tei_path.stem


def _record_id(work_id: str, page_id: str) -> str:
    return f"{work_id}/{page_id}"


def _build_record_and_spans(
    tree: etree._ElementTree,
    *,
    tei_path: Path,
    work_id: str,
) -> tuple[dict, dict[etree._Element, Span]]:
    page_id = _page_id(tei_path, tree)
    record_id = _record_id(work_id, page_id)
    lemmas = tree.xpath("/tei:TEI/tei:text//tei:lem", namespaces=NS)
    lemma_texts = [_clean_text(lemma) for lemma in lemmas]
    spans: dict[etree._Element, Span] = {}
    offset = 0
    for index, (lemma, lemma_text) in enumerate(zip(lemmas, lemma_texts, strict=True)):
        if index:
            offset += 1
        start = offset
        end = start + len(lemma_text)
        spans[lemma] = Span(record_id, start, end)
        offset = end
    record = {
        "id": record_id,
        "work_id": work_id,
        "page_id": page_id,
        "text": " ".join(lemma_texts),
        "language": LANGUAGE,
    }
    return record, spans


def _node_disposition(node: etree._Element) -> tuple[str, str | None]:
    local = _local(node)
    if local == "lem":
        return "projected", None
    if local in DROPPED_ELEMENTS:
        return "dropped", None
    if local in NORMALIZED_ELEMENTS:
        return "normalized", "markup removed, text kept"
    return "normalized", "container markup removed, text kept"


def _ledger(
    tree: etree._ElementTree,
    tei_path: Path,
    output_path: Path,
    record: dict,
    spans: dict[etree._Element, Span],
    repo_root: Path,
) -> dict:
    text = tree.xpath("/tei:TEI/tei:text", namespaces=NS)[0]
    nodes: list[dict] = []
    classes: dict[str, dict[str, int]] = {}
    for node in text.iter():
        local = _local(node)
        disposition, note = _node_disposition(node)
        entry: dict = {
            "address": derive_address(node),
            "element": local,
            "disposition": disposition,
        }
        classes.setdefault(local, {"projected": 0, "dropped": 0, "normalized": 0})[disposition] += 1
        if disposition == "projected":
            span = spans[node]
            entry["target"] = {
                "record_id": span.record_id,
                "char_start": span.start,
                "char_end": span.end,
            }
        elif disposition == "normalized":
            entry["note"] = note or "markup removed, text kept"
        nodes.append(entry)

    totals = {
        "addressable_nodes": len(nodes),
        "projected": sum(1 for node in nodes if node["disposition"] == "projected"),
        "dropped": sum(1 for node in nodes if node["disposition"] == "dropped"),
        "normalized": sum(1 for node in nodes if node["disposition"] == "normalized"),
    }
    return {
        "receipt_schema": "loss-receipt-v1",
        "projection": {
            "id": PROJECTION_ID,
            "generator": GENERATOR,
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        },
        "ir": {"path": _repo_relative(tei_path, repo_root), "sha256": _sha256(tei_path)},
        "output": {"path": _repo_relative(output_path, repo_root), "sha256": _sha256(output_path)},
        "totals": totals,
        "classes": classes,
        "nodes": nodes,
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _write_jsonl(path: Path, records: Sequence[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    temp.replace(path)


def _validate_receipt(receipt: dict) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(receipt, schema)


def project_file(
    tei_path: Path,
    output_jsonl: Path,
    *,
    receipt_path: Path | None = None,
    repo_root: Path = REPO_ROOT,
    work_id: str = DEFAULT_WORK_ID,
) -> dict:
    tree = etree.parse(str(tei_path))
    record, spans = _build_record_and_spans(tree, tei_path=tei_path, work_id=work_id)
    _write_jsonl(output_jsonl, [record])
    receipt = _ledger(tree, tei_path, output_jsonl, record, spans, repo_root)
    _validate_receipt(receipt)
    target_receipt = receipt_path or output_jsonl.with_suffix(output_jsonl.suffix + ".loss.json")
    _write_json(target_receipt, receipt)
    return receipt


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tei_file", type=Path)
    parser.add_argument("output_jsonl", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--work-id", default=DEFAULT_WORK_ID)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    project_file(args.tei_file, args.output_jsonl, receipt_path=args.receipt, work_id=args.work_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
