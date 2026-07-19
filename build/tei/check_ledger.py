"""Verify a TEI projection loss receipt independently of the projector."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from lxml import etree

from build.lib.paths import REPO_ROOT
from build.tei.check_ledger_v2 import check_receipt_v2
from ocd_kernel.tei.writer import TEI_NS, derive_address

NS = {"tei": TEI_NS}
DROP_DIV_TYPES = {"title", "titlepage", "imprint", "halftitlepage", "colophon", "copyright-page"}
DROP_ELEMENTS = {"note", "pb"}
NORMALIZED_ELEMENTS = {"ref", "hi", "emph", "foreign", "seg", "abbr", "title"}


def _local(node: etree._Element) -> str:
    return etree.QName(node).localname


def _collapse_spaces(value: str) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", value).strip()


def _normalize_text(value: str) -> str:
    lines = [_collapse_spaces(line) for line in value.split("\n")]
    return "\n".join(line for line in lines if line)


def _text_with_children(node: etree._Element) -> str:
    parts: list[str] = []
    if node.text:
        parts.append(node.text)
    for child in node:
        if _local(child) not in DROP_ELEMENTS:
            parts.append(_node_clean_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def _node_clean_text(node: etree._Element) -> str:
    local = _local(node)
    if local in DROP_ELEMENTS:
        return ""
    if local == "lg":
        return "\n".join(filter(None, (_node_clean_text(child) for child in node if _local(child) == "l")))
    return _normalize_text(_text_with_children(node))


def _under_dropped_wrapper(node: etree._Element) -> bool:
    current: etree._Element | None = node
    while current is not None:
        if _local(current) == "div" and current.get("type") in DROP_DIV_TYPES:
            return True
        current = current.getparent()
    return False


def _expected_disposition(node: etree._Element) -> str:
    local = _local(node)
    if _under_dropped_wrapper(node) or local in DROP_ELEMENTS:
        return "dropped"
    if local in NORMALIZED_ELEMENTS:
        return "normalized"
    return "projected"


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


def _check_counts(receipt: dict, errors: list[str]) -> None:
    nodes = receipt["nodes"]
    totals = {
        "addressable_nodes": len(nodes),
        "projected": sum(1 for node in nodes if node["disposition"] == "projected"),
        "dropped": sum(1 for node in nodes if node["disposition"] == "dropped"),
        "normalized": sum(1 for node in nodes if node["disposition"] == "normalized"),
    }
    if receipt["totals"] != totals:
        errors.append(f"totals mismatch: receipt={receipt['totals']} computed={totals}")
    classes: dict[str, dict[str, int]] = {}
    for node in nodes:
        classes.setdefault(node["element"], {"projected": 0, "dropped": 0, "normalized": 0})[node["disposition"]] += 1
    if receipt["classes"] != classes:
        errors.append("classes mismatch")


def check_receipt(receipt_path: Path, *, repo_root: Path = REPO_ROOT) -> list[str]:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("receipt_schema") == "loss-receipt-v2":
        return check_receipt_v2(receipt_path, repo_root=repo_root)
    errors: list[str] = []
    ir_path = repo_root / receipt["ir"]["path"]
    output_path = repo_root / receipt["output"]["path"]
    if not ir_path.exists():
        return [f"IR path does not exist: {ir_path}"]
    if not output_path.exists():
        return [f"output path does not exist: {output_path}"]

    records = _load_jsonl(output_path)
    tree = etree.parse(str(ir_path))
    text = tree.xpath("/tei:TEI/tei:text", namespaces=NS)[0]
    by_address, duplicate_errors = _receipt_nodes_by_address(receipt)
    errors.extend(duplicate_errors)
    used_records: set[str] = set()

    for element in text.iter():
        address = derive_address(element)
        entry = by_address.get(address)
        if entry is None:
            errors.append(f"missing ledger node: {address}")
            continue
        expected_disposition = _expected_disposition(element)
        if entry["element"] != _local(element):
            errors.append(f"element mismatch for {address}: {entry['element']} != {_local(element)}")
        if entry["disposition"] != expected_disposition:
            errors.append(
                f"disposition mismatch for {address}: {entry['disposition']} != {expected_disposition}"
            )
        target = entry.get("target")
        if entry["disposition"] == "projected" and target is None:
            errors.append(f"projected node missing target: {address}")
            continue
        if target is None:
            continue
        record = records.get(target["record_id"])
        if record is None:
            errors.append(f"target record missing for {address}: {target['record_id']}")
            continue
        used_records.add(target["record_id"])
        if "char_start" in target or "char_end" in target:
            start = target.get("char_start")
            end = target.get("char_end")
            if not isinstance(start, int) or not isinstance(end, int) or start > end:
                errors.append(f"invalid char span for {address}: {target}")
                continue
            expected_text = _node_clean_text(element)
            actual_text = record.get("text", "")[start:end]
            if actual_text != expected_text:
                errors.append(
                    f"span mismatch for {address}: expected {expected_text!r}, got {actual_text!r}"
                )

    expected_addresses = {derive_address(element) for element in text.iter()}
    for address in sorted(set(by_address) - expected_addresses):
        errors.append(f"extra ledger node: {address}")
    for record_id in sorted(set(records) - used_records):
        errors.append(f"orphan output record: {record_id}")
    _check_counts(receipt, errors)
    return errors


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt_path", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    errors = check_receipt(args.receipt_path)
    if errors:
        for error in errors:
            print(error)
        return 1
    receipt = json.loads(args.receipt_path.read_text(encoding="utf-8"))
    if receipt.get("receipt_schema") == "loss-receipt-v1":
        print("LEGACY: loss-receipt-v1 is valid but does not prove delivery")
    else:
        print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
