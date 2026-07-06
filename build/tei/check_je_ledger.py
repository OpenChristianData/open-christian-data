"""Verify a JE TEI projection loss receipt independently of the projector."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Sequence

from lxml import etree

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.paths import REPO_ROOT
from build.tei.writer import TEI_NS, derive_address

NS = {"tei": TEI_NS}
DROPPED_ELEMENTS = frozenset({"rdg", "note", "pb"})
NORMALIZED_ELEMENTS = frozenset({"text", "body", "ab", "w", "app"})


def _local(node: etree._Element) -> str:
    return etree.QName(node).localname


def _collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _clean_text(node: etree._Element) -> str:
    return _collapse_whitespace("".join(node.itertext()))


def _short_text(value: str, limit: int = 120) -> str:
    rendered = ascii(value)
    if len(rendered) <= limit:
        return rendered
    return rendered[: limit - 3] + "..."


def _expected_disposition(node: etree._Element) -> str:
    local = _local(node)
    if local == "lem":
        return "projected"
    if local in DROPPED_ELEMENTS:
        return "dropped"
    if local in NORMALIZED_ELEMENTS:
        return "normalized"
    return "normalized"


def _load_jsonl(path: Path) -> dict[str, dict]:
    records: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        records[record["id"]] = record
    return records


def _receipt_nodes_by_address(receipt: dict) -> tuple[dict[str, dict], list[str]]:
    seen: dict[str, dict] = {}
    errors: list[str] = []
    for node in receipt["nodes"]:
        address = node["address"]
        if address in seen:
            errors.append(f"duplicate ledger node: {address}")
        seen[address] = node
    return seen, errors


def _expected_counts(text: etree._Element) -> tuple[dict, dict[str, dict[str, int]]]:
    nodes = list(text.iter())
    totals = {
        "addressable_nodes": len(nodes),
        "projected": 0,
        "dropped": 0,
        "normalized": 0,
    }
    classes: dict[str, dict[str, int]] = {}
    for node in nodes:
        local = _local(node)
        disposition = _expected_disposition(node)
        totals[disposition] += 1
        classes.setdefault(local, {"projected": 0, "dropped": 0, "normalized": 0})[disposition] += 1
    return totals, classes


def _receipt_counts(receipt: dict) -> tuple[dict, dict[str, dict[str, int]]]:
    totals = {
        "addressable_nodes": len(receipt["nodes"]),
        "projected": sum(1 for node in receipt["nodes"] if node["disposition"] == "projected"),
        "dropped": sum(1 for node in receipt["nodes"] if node["disposition"] == "dropped"),
        "normalized": sum(1 for node in receipt["nodes"] if node["disposition"] == "normalized"),
    }
    classes: dict[str, dict[str, int]] = {}
    for node in receipt["nodes"]:
        classes.setdefault(node["element"], {"projected": 0, "dropped": 0, "normalized": 0})[
            node["disposition"]
        ] += 1
    return totals, classes


def _check_counts(receipt: dict, text: etree._Element, errors: list[str]) -> None:
    expected_totals, expected_classes = _expected_counts(text)
    receipt_totals, receipt_classes = _receipt_counts(receipt)
    if receipt["totals"] != receipt_totals:
        errors.append(f"totals mismatch: stored={ascii(receipt['totals'])} receipt_nodes={ascii(receipt_totals)}")
    if receipt["totals"] != expected_totals:
        errors.append(f"totals mismatch: stored={ascii(receipt['totals'])} expected_tei={ascii(expected_totals)}")
    if receipt["classes"] != receipt_classes:
        errors.append("classes mismatch: stored classes do not match receipt nodes")
    if receipt["classes"] != expected_classes:
        errors.append("classes mismatch: stored classes do not match TEI")


def _check_record_texts(records: dict[str, dict], expected_texts: dict[str, list[str]], errors: list[str]) -> None:
    for record_id, lemma_texts in sorted(expected_texts.items()):
        expected = " ".join(lemma_texts)
        actual = records.get(record_id, {}).get("text", "")
        if actual == expected:
            continue
        errors.append(
            "output text mismatch for "
            f"{ascii(record_id)}: expected_len={len(expected)} actual_len={len(actual)} "
            f"expected_prefix={_short_text(expected[:80])} actual_prefix={_short_text(actual[:80])}"
        )


def check_receipt(receipt_path: Path, *, repo_root: Path = REPO_ROOT) -> list[str]:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    ir_path = repo_root / receipt["ir"]["path"]
    output_path = repo_root / receipt["output"]["path"]
    if not ir_path.exists():
        return [f"IR path does not exist: {ascii(str(ir_path))}"]
    if not output_path.exists():
        return [f"output path does not exist: {ascii(str(output_path))}"]

    records = _load_jsonl(output_path)
    tree = etree.parse(str(ir_path))
    text = tree.xpath("/tei:TEI/tei:text", namespaces=NS)[0]
    by_address, duplicate_errors = _receipt_nodes_by_address(receipt)
    errors.extend(duplicate_errors)
    used_records: set[str] = set()
    expected_texts_by_record: dict[str, list[str]] = {}
    previous_span_by_record: dict[str, tuple[int, int, str]] = {}

    for element in text.iter():
        address = derive_address(element)
        entry = by_address.get(address)
        if entry is None:
            errors.append(f"missing ledger node: {address}")
            continue
        expected_disposition = _expected_disposition(element)
        local = _local(element)
        if entry["element"] != local:
            errors.append(f"element mismatch for {address}: {entry['element']} != {local}")
        if entry["disposition"] != expected_disposition:
            errors.append(
                f"disposition mismatch for {address}: {entry['disposition']} != {expected_disposition}"
            )
        target = entry.get("target")
        if expected_disposition == "projected" and target is None:
            errors.append(f"projected node missing target: {address}")
            continue
        if target is None:
            continue
        record = records.get(target["record_id"])
        if record is None:
            errors.append(f"target record missing for {address}: {ascii(target['record_id'])}")
            continue
        used_records.add(target["record_id"])
        if expected_disposition != "projected":
            continue
        start = target.get("char_start")
        end = target.get("char_end")
        if not isinstance(start, int) or not isinstance(end, int) or start > end:
            errors.append(f"invalid char span for {address}: {ascii(target)}")
            continue
        expected_text = _clean_text(element)
        expected_texts_by_record.setdefault(target["record_id"], []).append(expected_text)
        previous_span = previous_span_by_record.get(target["record_id"])
        if previous_span is not None:
            previous_start, previous_end, previous_address = previous_span
            if start < previous_start or start < previous_end:
                errors.append(
                    "span ordering/overlap for "
                    f"{address}: previous={previous_address} {previous_start}:{previous_end} "
                    f"current={start}:{end}"
                )
        previous_span_by_record[target["record_id"]] = (start, end, address)
        actual_text = record.get("text", "")[start:end]
        if actual_text != expected_text:
            errors.append(
                f"span mismatch for {address}: expected {ascii(expected_text)}, got {ascii(actual_text)}"
            )

    expected_addresses = {derive_address(element) for element in text.iter()}
    for address in sorted(set(by_address) - expected_addresses):
        errors.append(f"extra ledger node: {address}")
    for record_id in sorted(set(records) - used_records):
        errors.append(f"orphan output record: {ascii(record_id)}")
    _check_record_texts(records, expected_texts_by_record, errors)
    _check_counts(receipt, text, errors)
    return errors


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt_path", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    errors = check_receipt(args.receipt_path)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
