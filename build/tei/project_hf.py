"""Project TEI IR into HF clean-text JSONL plus a loss-receipt ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from lxml import etree

from build.lib.paths import REPO_ROOT
from build.tei.writer import TEI_NS, derive_address

NS = {"tei": TEI_NS}
PROJECTION_ID = "hf-clean-text-v1"
GENERATOR = "build/tei/project_hf.py"
LANGUAGE = "en"
LICENSE = "CC0"
DROP_DIV_TYPES = {"title", "titlepage", "imprint", "halftitlepage", "colophon", "copyright-page"}
DROP_ELEMENTS = {"note", "pb"}
NORMALIZED_ELEMENTS = {"ref", "hi", "emph", "foreign", "seg", "abbr", "title"}
BLOCK_ELEMENTS = {"p", "quote", "lg"}


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


def _collapse_spaces(value: str) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", value).strip()


def _collapse_all_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _normalize_text(value: str) -> str:
    lines = [_collapse_spaces(line) for line in value.split("\n")]
    return "\n".join(line for line in lines if line)


def clean_text(node: etree._Element) -> str:
    local = _local(node)
    if local in DROP_ELEMENTS:
        return ""
    if local == "lg":
        return "\n".join(filter(None, (clean_text(child) for child in node if _local(child) == "l")))
    if local == "l":
        return _normalize_text(_text_with_children(node))
    return _normalize_text(_text_with_children(node))


def _text_with_children(node: etree._Element) -> str:
    parts: list[str] = []
    if node.text:
        parts.append(node.text)
    for child in node:
        parts.append(clean_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def _under(node: etree._Element, locals_: set[str]) -> bool:
    parent = node.getparent()
    while parent is not None:
        if _local(parent) in locals_:
            return True
        parent = parent.getparent()
    return False


def _under_dropped_wrapper(node: etree._Element) -> bool:
    current: etree._Element | None = node
    while current is not None:
        if _local(current) == "div" and current.get("type") in DROP_DIV_TYPES:
            return True
        current = current.getparent()
    return False


def _first_head_text(div: etree._Element) -> str | None:
    head = div.find("tei:head", namespaces=NS)
    if head is None:
        return None
    text = _collapse_all_whitespace(clean_text(head))
    return text or None


def _header_text(tree: etree._ElementTree, xpath: str) -> str | None:
    node = tree.xpath(xpath, namespaces=NS)
    if not node:
        return None
    text = _collapse_spaces(" ".join(str(part) for part in node[0].itertext()))
    return text or None


def _source(tree: etree._ElementTree) -> dict[str, str]:
    translator = ""
    for resp_stmt in tree.xpath(".//tei:titleStmt/tei:respStmt", namespaces=NS):
        resp = _collapse_spaces(" ".join(resp_stmt.xpath("./tei:resp//text()", namespaces=NS))).lower()
        name = _collapse_spaces(" ".join(resp_stmt.xpath("./tei:name//text()", namespaces=NS)))
        if "translator" in resp and name:
            translator = name
            break
    if not translator:
        translator = "Marcus Dods"
    ptrs = tree.xpath(".//tei:sourceDesc//tei:ptr[@target]", namespaces=NS)
    return {
        "author": _header_text(tree, ".//tei:titleStmt/tei:author") or "",
        "translator": translator,
        "source_url": ptrs[0].get("target") if ptrs else "",
        "license": LICENSE,
    }


def _ids_from_path(path: Path) -> tuple[str, str]:
    name = path.name
    suffix = ".tei.xml"
    if not name.endswith(suffix):
        raise ValueError(f"TEI filename must end with {suffix}: {path}")
    stem = name.removesuffix(suffix)
    work_id, rendering_id = stem.rsplit(".", 1)
    return work_id, rendering_id


def _record_divs(text: etree._Element) -> list[etree._Element]:
    records: list[etree._Element] = []
    for div in text.xpath(".//tei:div", namespaces=NS):
        if div.get("type") in DROP_DIV_TYPES:
            continue
        has_child_div = bool(div.xpath("./tei:div", namespaces=NS))
        has_prose = bool(_text_blocks(div)) or div.find("tei:argument", namespaces=NS) is not None
        if not has_child_div and has_prose:
            records.append(div)
    return records


def _text_blocks(record_div: etree._Element) -> list[etree._Element]:
    blocks: list[etree._Element] = []
    for node in record_div.xpath(".//*[local-name()='p' or local-name()='quote' or local-name()='lg']"):
        if _under(node, {"head", "argument", "note"}):
            continue
        if any(ancestor in blocks for ancestor in node.iterancestors()):
            continue
        if clean_text(node):
            blocks.append(node)
    return blocks


def _title_path(title: str, record_div: etree._Element) -> list[str]:
    parts = [_collapse_all_whitespace(title)]
    divs = [
        ancestor for ancestor in reversed(list(record_div.iterancestors()))
        if _local(ancestor) == "div" and ancestor.get("type") not in DROP_DIV_TYPES
    ]
    divs.append(record_div)
    for div in divs:
        head = _first_head_text(div)
        if head:
            parts.append(head)
    deduped: list[str] = []
    for part in parts:
        if not deduped or deduped[-1] != part:
            deduped.append(part)
    return deduped


def _argument(record_div: etree._Element) -> str | None:
    argument = record_div.find("tei:argument", namespaces=NS)
    if argument is None:
        return None
    text = _collapse_all_whitespace(clean_text(argument))
    return text or None


def _record_id(work_id: str, rendering_id: str, div: etree._Element) -> str:
    return f"{work_id}/{rendering_id}/{derive_address(div)}"


def _nearest_record(node: etree._Element, record_divs: list[etree._Element]) -> etree._Element | None:
    current: etree._Element | None = node
    while current is not None:
        if current in record_divs:
            return current
        current = current.getparent()
    for record_div in record_divs:
        if node in record_div.iterancestors() or record_div in node.iterdescendants():
            return record_div
    return record_divs[0] if record_divs else None


def _find_span(record_text: str, needle: str, starts: dict[str, int]) -> tuple[int, int] | None:
    if not needle:
        return None
    start_at = starts.get(needle, 0)
    start = record_text.find(needle, start_at)
    if start == -1:
        start = record_text.find(needle)
    if start == -1:
        return None
    end = start + len(needle)
    starts[needle] = end
    return start, end


def _build_records(
    tree: etree._ElementTree,
    tei_path: Path,
) -> tuple[list[dict], list[etree._Element], dict[etree._Element, Span]]:
    work_id, rendering_id = _ids_from_path(tei_path)
    title = _header_text(tree, ".//tei:titleStmt/tei:title") or work_id
    source = _source(tree)
    text = tree.xpath("/tei:TEI/tei:text", namespaces=NS)[0]
    record_divs = _record_divs(text)
    spans: dict[etree._Element, Span] = {}
    records: list[dict] = []
    for div in record_divs:
        rid = _record_id(work_id, rendering_id, div)
        blocks = _text_blocks(div)
        block_texts = [clean_text(block) for block in blocks if clean_text(block)]
        record_text = "\n\n".join(block_texts)
        records.append(
            {
                "id": rid,
                "work_id": work_id,
                "rendering_id": rendering_id,
                "title_path": _title_path(title, div),
                "argument": _argument(div),
                "text": record_text,
                "language": LANGUAGE,
                "source": source,
            }
        )
        starts: dict[str, int] = {}
        for node in div.iter():
            if _under(node, {"head", "argument", "note"}) or _local(node) in DROP_ELEMENTS:
                continue
            needle = clean_text(node)
            span = _find_span(record_text, needle, starts)
            if span is not None:
                spans[node] = Span(rid, span[0], span[1])
    return records, record_divs, spans


def _node_disposition(node: etree._Element) -> tuple[str, str | None]:
    local = _local(node)
    if _under_dropped_wrapper(node) or local in DROP_ELEMENTS:
        return "dropped", None
    if local == "ref":
        return "normalized", "cRef annotation removed, text kept"
    if local in NORMALIZED_ELEMENTS:
        return "normalized", "markup removed, text kept"
    return "projected", None


def _ledger(
    tree: etree._ElementTree,
    tei_path: Path,
    output_path: Path,
    records: list[dict],
    record_divs: list[etree._Element],
    spans: dict[etree._Element, Span],
    repo_root: Path,
) -> dict:
    text = tree.xpath("/tei:TEI/tei:text", namespaces=NS)[0]
    record_ids = {_id: _id for _id in (record["id"] for record in records)}
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
        if disposition != "dropped":
            span = spans.get(node)
            if span is not None:
                entry["target"] = {
                    "record_id": span.record_id,
                    "char_start": span.start,
                    "char_end": span.end,
                }
            else:
                record_div = _nearest_record(node, record_divs)
                if record_div is not None:
                    entry["target"] = {"record_id": _record_id(*_ids_from_path(tei_path), record_div)}
                elif record_ids:
                    entry["target"] = {"record_id": next(iter(record_ids))}
                note = note or "container"
        if local == "head" and disposition != "dropped":
            note = "head->title_path"
        elif _under(node, {"argument"}) or local == "argument":
            note = note or "argument"
        if note:
            entry["note"] = note
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


def project_file(
    tei_path: Path,
    output_jsonl: Path,
    *,
    receipt_path: Path | None = None,
    repo_root: Path = REPO_ROOT,
) -> dict:
    tree = etree.parse(str(tei_path))
    records, record_divs, spans = _build_records(tree, tei_path)
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with output_jsonl.open("w", encoding="utf-8", newline="\n") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    receipt = _ledger(tree, tei_path, output_jsonl, records, record_divs, spans, repo_root)
    target_receipt = receipt_path or output_jsonl.with_suffix(output_jsonl.suffix + ".loss.json")
    target_receipt.parent.mkdir(parents=True, exist_ok=True)
    target_receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tei_file", type=Path)
    parser.add_argument("output_jsonl", type=Path)
    parser.add_argument("--receipt", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    project_file(args.tei_file, args.output_jsonl, receipt_path=args.receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
