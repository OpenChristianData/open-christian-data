"""Project TEI IR into HF clean-text JSONL plus a loss-receipt-v2 ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lxml import etree

from build.lib.paths import REPO_ROOT
from ocd_kernel.tei.normalization import normalize_block, normalize_inline
from ocd_kernel.tei.projection_profile import (
    DISPOSITIONS,
    PROFILE_ID,
    classify_base,
    destination_for,
    drop_reason,
    rule_for,
    structural_reason,
)
from ocd_kernel.tei.writer import TEI_NS, derive_address

NS = {"tei": TEI_NS}
GENERATOR = "build/tei/project_hf.py"
LANGUAGE = "en"
LICENSE = "CC0"
BLOCK_ROOTS = frozenset(
    {
        "p",
        "quote",
        "lg",
        "sp",
        "label",
        "trailer",
        "l",
        "date",
        "q",
        "bibl",
    }
)


@dataclass(frozen=True)
class TargetSpan:
    """One exact slice in a projected output field."""

    record_id: str
    field: str
    char_start: int
    char_end: int
    item_index: int | None = None
    item_field: str | None = None

    def as_dict(self) -> dict[str, Any]:
        target: dict[str, Any] = {
            "record_id": self.record_id,
            "field": self.field,
            "char_start": self.char_start,
            "char_end": self.char_end,
        }
        if self.item_index is not None:
            target["item_index"] = self.item_index
        if self.item_field is not None:
            target["item_field"] = self.item_field
        return target


def _local(node: etree._Element) -> str:
    return etree.QName(node).localname


def _repo_relative(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _source_fragment(node: etree._Element) -> str:
    parts: list[str] = []
    if node.text:
        parts.append(node.text)
    for child in node:
        parts.append(_source_fragment(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def _fragment_part(value: str) -> str:
    """Keep word boundaries while collapsing source formatting whitespace."""

    if not value:
        return ""
    normalized = normalize_inline(value)
    if not normalized:
        return " " if any(character.isspace() for character in value) else ""
    prefix = " " if value[0].isspace() else ""
    suffix = " " if value[-1].isspace() else ""
    return prefix + normalized + suffix


def _projected_fragment(node: etree._Element) -> str:
    """Render a live node while omitting every dropped descendant."""

    local = _local(node)
    if local == "lb":
        return "\n"
    if local == "lg":
        lines = [
            _canonical_projected(child)
            for child in node
            if _local(child) == "l" and classify_base(child) != "dropped"
        ]
        return normalize_block("\n".join(lines))

    parts: list[str] = []
    if node.text:
        parts.append(_fragment_part(node.text))
    for child in node:
        if classify_base(child) != "dropped":
            parts.append(_projected_fragment(child))
        if child.tail:
            parts.append(_fragment_part(child.tail))
    return "".join(parts)


def _canonical_source(node: etree._Element) -> str:
    local = _local(node)
    if local == "lg":
        lines = [_canonical_source(child) for child in node if _local(child) == "l"]
        return normalize_block("\n".join(lines))
    if local == "l":
        return normalize_inline(_source_fragment(node))
    if local in {"p", "quote", "sp", "trailer"}:
        return normalize_block(_source_fragment(node))
    return normalize_inline(_source_fragment(node))


def _canonical_projected(node: etree._Element) -> str:
    local = _local(node)
    if local == "lg":
        return _projected_fragment(node)
    if local == "l":
        return normalize_inline(_projected_fragment(node))
    if local in {"p", "quote", "sp", "trailer"}:
        return normalize_block(_projected_fragment(node))
    return normalize_inline(_projected_fragment(node))


def _canonical_text(node: etree._Element) -> str:
    """Return the receipt canonical text for one node."""

    if classify_base(node) == "dropped":
        return _canonical_source(node)
    if _local(node) == "sp":
        return _speech_text(node)
    if destination_for(node) == "argument":
        return normalize_inline(_projected_fragment(node))
    return _canonical_projected(node)


def clean_text(node: etree._Element) -> str:
    """Backward-compatible name for the projector's canonical text function."""

    return _canonical_text(node)


def _under(node: etree._Element, locals_: frozenset[str]) -> bool:
    current = node.getparent()
    while current is not None:
        if _local(current) in locals_:
            return True
        current = current.getparent()
    return False


def _has_ancestor(node: etree._Element, locals_: frozenset[str]) -> bool:
    return _under(node, locals_)


def _content_roots(record_div: etree._Element) -> list[etree._Element]:
    """Find direct-record content without traversing into child record divs."""

    roots: list[etree._Element] = []

    def visit(parent: etree._Element) -> None:
        for child in parent:
            local = _local(child)
            if local == "div":
                continue
            if local in {"head", "argument", "note", "pb"}:
                continue
            if local in BLOCK_ROOTS:
                if local == "p" and _has_ancestor(child, frozenset({"sp", "argument"})):
                    continue
                if local == "l" and _has_ancestor(child, frozenset({"lg", "quote"})):
                    continue
                if local == "date" and _has_ancestor(child, frozenset({"trailer"})):
                    continue
                if _canonical_text(child):
                    roots.append(child)
                continue
            visit(child)

    visit(record_div)
    return roots


def _record_divs(text: etree._Element) -> list[etree._Element]:
    """Select every non-dropped div that owns direct deliverable content."""

    live = [
        div
        for div in text.xpath(".//tei:div", namespaces=NS)
        if classify_base(div) != "dropped"
    ]
    records: list[etree._Element] = []
    for div in live:
        direct_argument = div.find("./tei:argument", namespaces=NS)
        if _content_roots(div) or (
            direct_argument is not None and bool(_canonical_text(direct_argument))
        ):
            records.append(div)

    # A <head> does not by itself make a div a record -- it is delivered through
    # the title_path of every descendant record it governs. The exception is a
    # head-bearing div that governs no content record at all (a standalone
    # divider such as <div type="part"><head>Part I</head></div>): its heading
    # would otherwise have no delivery path and its text would be lost. Only
    # those divs get a record; minting one per head-bearing div would add a
    # contentless record to every structural book/part div in the corpus.
    owned = set(records)
    for div in live:
        head = div.find("./tei:head", namespaces=NS)
        if head is None or not _canonical_text(head):
            continue
        if any(_is_descendant_or_self(record, div) for record in owned):
            continue
        records.append(div)

    selected = set(records)
    return [div for div in live if div in selected]


def _text_blocks(record_div: etree._Element) -> list[etree._Element]:
    """Compatibility wrapper for callers that used the v1 helper name."""

    return _content_roots(record_div)


def _render_block(node: etree._Element) -> str:
    if _local(node) != "sp":
        return _canonical_projected(node)
    speakers = [
        _canonical_projected(child)
        for child in node
        if _local(child) == "speaker" and _canonical_projected(child)
    ]
    body = _speech_parts(node)
    if speakers and body:
        return "\n".join(speakers + ["\n\n".join(body)])
    return "\n\n".join(speakers + body) or _canonical_projected(node)


def _speech_parts(node: etree._Element) -> list[str]:
    """Return ordered spoken blocks, excluding the immediate role label."""

    return [
        _canonical_text(child)
        for child in node
        if _local(child) != "speaker"
        and _local(child) in BLOCK_ROOTS
        and _canonical_text(child)
    ]


def _speech_text(node: etree._Element) -> str:
    if _speech_is_top_level_block(node):
        return "\n\n".join(_speech_parts(node))
    parts: list[str] = []
    if node.text:
        parts.append(_fragment_part(node.text))
    for child in node:
        if _local(child) != "speaker" and classify_base(child) != "dropped":
            parts.append(_projected_fragment(child))
        if child.tail:
            parts.append(_fragment_part(child.tail))
    return normalize_block("".join(parts))


def _speech_is_top_level_block(node: etree._Element) -> bool:
    current = node.getparent()
    while current is not None and _local(current) != "div":
        if _local(current) in BLOCK_ROOTS:
            return False
        current = current.getparent()
    return True


def _speech_speaker(node: etree._Element) -> str | None:
    speakers = [
        _canonical_projected(child)
        for child in node
        if _local(child) == "speaker" and _canonical_projected(child)
    ]
    if len(speakers) > 1:
        raise ValueError(f"<sp> has multiple immediate <speaker> labels: {derive_address(node)}")
    return speakers[0] if speakers else None


def _owned_speeches(record_div: etree._Element) -> list[etree._Element]:
    """Return every live speech owned by this record, excluding child record divs."""

    speeches: list[etree._Element] = []

    def visit(parent: etree._Element) -> None:
        for child in parent:
            if _local(child) == "div" or classify_base(child) == "dropped":
                continue
            if _local(child) == "sp":
                speeches.append(child)
            visit(child)

    visit(record_div)
    return speeches


def _speech_items(
    record_div: etree._Element, record_text: str
) -> list[dict[str, Any]]:
    """Build ordered speech metadata with exact offsets into the flat record text."""

    items: list[dict[str, Any]] = []
    search_from = 0
    for speech in _owned_speeches(record_div):
        spoken = _speech_text(speech)
        if not spoken:
            raise ValueError(f"<sp> has no spoken text: {derive_address(speech)}")
        start = record_text.find(spoken, search_from)
        if start < 0:
            raise ValueError(f"<sp> spoken text is absent from flat text: {derive_address(speech)}")
        items.append(
            {
                "speaker": _speech_speaker(speech),
                "text": spoken,
                "char_start": start,
                "char_end": start + len(spoken),
            }
        )
        search_from = start + len(spoken)
    return items


def _first_head_text(div: etree._Element) -> str | None:
    head = div.find("./tei:head", namespaces=NS)
    if head is None:
        return None
    text = _canonical_text(head)
    return text or None


def _header_text(tree: etree._ElementTree, xpath: str) -> str | None:
    nodes = tree.xpath(xpath, namespaces=NS)
    if not nodes:
        return None
    text = normalize_inline("".join(nodes[0].itertext()))
    return text or None


def _source(tree: etree._ElementTree) -> dict[str, str]:
    translator = ""
    for resp_stmt in tree.xpath(".//tei:titleStmt/tei:respStmt", namespaces=NS):
        resp = normalize_inline("".join(resp_stmt.xpath("./tei:resp//text()", namespaces=NS))).lower()
        name = normalize_inline("".join(resp_stmt.xpath("./tei:name//text()", namespaces=NS)))
        if "translator" in resp and name:
            translator = name
            break
    ptrs = tree.xpath(".//tei:sourceDesc//tei:ptr[@target]", namespaces=NS)
    return {
        "author": _header_text(tree, ".//tei:titleStmt/tei:author") or "",
        "translator": translator,
        "source_url": ptrs[0].get("target") if ptrs else "",
        "license": LICENSE,
    }


def _ids_from_path(path: Path) -> tuple[str, str]:
    suffix = ".tei.xml"
    if not path.name.endswith(suffix):
        raise ValueError(f"TEI filename must end with {suffix}: {path}")
    stem = path.name.removesuffix(suffix)
    work_id, rendering_id = stem.rsplit(".", 1)
    return work_id, rendering_id


def _title_path(title: str, record_div: etree._Element) -> list[str]:
    divs = [
        ancestor
        for ancestor in reversed(list(record_div.iterancestors()))
        if _local(ancestor) == "div" and classify_base(ancestor) != "dropped"
    ]
    divs.append(record_div)
    values = [normalize_inline(title)]
    for div in divs:
        for head_node in div.findall("./tei:head", namespaces=NS):
            head = _canonical_text(head_node)
            if head and values[-1] != head:
                values.append(head)
    return values


def _argument(record_div: etree._Element) -> str | None:
    argument = record_div.find("./tei:argument", namespaces=NS)
    if argument is None:
        return None
    text = _canonical_text(argument)
    return text or None


def _record_id(work_id: str, rendering_id: str, div: etree._Element) -> str:
    return f"{work_id}/{rendering_id}/{derive_address(div)}"


def _build_records(
    tree: etree._ElementTree,
    tei_path: Path,
) -> tuple[list[dict[str, Any]], list[etree._Element]]:
    work_id, rendering_id = _ids_from_path(tei_path)
    title = _header_text(tree, ".//tei:titleStmt/tei:title") or work_id
    source = _source(tree)
    text_nodes = tree.xpath("/tei:TEI/tei:text", namespaces=NS)
    if not text_nodes:
        raise ValueError(f"TEI has no /TEI/text element: {tei_path}")
    text = text_nodes[0]
    record_divs = _record_divs(text)
    records: list[dict[str, Any]] = []
    for div in record_divs:
        blocks = _content_roots(div)
        rendered_blocks = [_render_block(block) for block in blocks]
        record_text = "\n\n".join(rendered_blocks)
        speeches = _speech_items(div, record_text)
        record = {
                "id": _record_id(work_id, rendering_id, div),
                "work_id": work_id,
                "rendering_id": rendering_id,
                "title_path": _title_path(title, div),
                "argument": _argument(div),
                "text": record_text,
                "language": LANGUAGE,
                "source": source,
            }
        if speeches:
            record["speeches"] = speeches
        records.append(record)
    return records, record_divs


def _is_descendant_or_self(node: etree._Element, ancestor: etree._Element) -> bool:
    current: etree._Element | None = node
    while current is not None:
        if current is ancestor:
            return True
        current = current.getparent()
    return False


def _nearest_div(node: etree._Element) -> etree._Element | None:
    current: etree._Element | None = node
    while current is not None:
        if _local(current) == "div":
            return current
        current = current.getparent()
    return None


def _nearest_record_div(
    node: etree._Element, record_divs: list[etree._Element]
) -> etree._Element | None:
    current: etree._Element | None = node
    while current is not None:
        if current in record_divs:
            return current
        current = current.getparent()
    return None


def _governing_records(
    head: etree._Element,
    record_divs: list[etree._Element],
) -> list[etree._Element]:
    owning_div = _nearest_div(head)
    if owning_div is None:
        return []
    return [div for div in record_divs if _is_descendant_or_self(div, owning_div)]


def _head_ancestor(node: etree._Element) -> etree._Element | None:
    current: etree._Element | None = node
    while current is not None:
        if _local(current) == "head":
            return current
        current = current.getparent()
    return None


def _find_target_span(
    value: str,
    needle: str,
    node: etree._Element,
    previous: dict[tuple[str, str, str], list[tuple[etree._Element, tuple[int, int]]]],
    key: tuple[str, str, str],
) -> tuple[int, int] | None:
    if not needle:
        return None
    prior = previous.get(key, [])
    for prior_node, span in reversed(prior):
        if _is_descendant_or_self(node, prior_node) and node is not prior_node:
            return span
    start_at = prior[-1][1][1] if prior else 0
    start = value.find(needle, start_at)
    if start < 0:
        return None
    span = (start, start + len(needle))
    previous.setdefault(key, []).append((node, span))
    return span


def _title_target_span(
    node: etree._Element,
    canonical: str,
    record: dict[str, Any],
) -> TargetSpan | None:
    head = _head_ancestor(node)
    if head is None:
        return None
    title = _canonical_text(head)
    title_path = record["title_path"]
    try:
        item_index = title_path.index(title)
    except ValueError:
        return None
    start = title_path[item_index].find(canonical)
    if start < 0:
        return None
    return TargetSpan(
        record["id"],
        "title_path",
        start,
        start + len(canonical),
        item_index,
    )


def _targets_for_node(
    node: etree._Element,
    canonical: str,
    records_by_div: dict[etree._Element, str],
    records_by_id: dict[str, dict[str, Any]],
    record_divs: list[etree._Element],
    previous: dict[tuple[str, str, str], list[tuple[etree._Element, tuple[int, int]]]],
) -> list[TargetSpan]:
    local = _local(node)
    if local in {"sp", "speaker"}:
        record_div = _nearest_record_div(node, record_divs)
        if record_div is None:
            return []
        record_id = records_by_div.get(record_div)
        if record_id is None:
            return []
        record = records_by_id[record_id]
        speech_node = node if local == "sp" else node.getparent()
        if speech_node is None or _local(speech_node) != "sp":
            return []
        speech_nodes = _owned_speeches(record_div)
        try:
            speech_index = speech_nodes.index(speech_node)
        except ValueError:
            return []
        item_field = "text" if local == "sp" else "speaker"
        speeches = record.get("speeches", [])
        if speech_index >= len(speeches) or speeches[speech_index].get(item_field) != canonical:
            return []
        item = speeches[speech_index]
        if local == "sp":
            flat_span = (item["char_start"], item["char_end"])
        else:
            end = item["char_start"]
            while end > 0 and record["text"][end - 1].isspace():
                end -= 1
            start = end - len(canonical)
            if start < 0 or record["text"][start:end] != canonical:
                return []
            flat_span = (start, end)
        return [
            TargetSpan(record_id, "text", flat_span[0], flat_span[1]),
            TargetSpan(
                record_id,
                "speeches",
                0,
                len(canonical),
                speech_index,
                item_field,
            ),
        ]

    field = destination_for(node)
    if field == "title_path":
        head = _head_ancestor(node)
        if head is None:
            return []
        targets: list[TargetSpan] = []
        for record_div in _governing_records(head, record_divs):
            record_id = records_by_div.get(record_div)
            if record_id is None:
                continue
            target = _title_target_span(node, canonical, records_by_id[record_id])
            if target is not None:
                targets.append(target)
        return targets

    record_div = _nearest_record_div(node, record_divs)
    if record_div is None or field is None:
        return []
    record_id = records_by_div.get(record_div)
    if record_id is None:
        return []
    value = records_by_id[record_id].get(field)
    if not isinstance(value, str):
        return []
    key = (record_id, field, canonical)
    span = _find_target_span(value, canonical, node, previous, key)
    if span is None:
        return []
    return [TargetSpan(record_id, field, span[0], span[1])]


def _ledger(
    tree: etree._ElementTree,
    tei_path: Path,
    output_path: Path,
    records: list[dict[str, Any]],
    record_divs: list[etree._Element],
    repo_root: Path,
) -> dict[str, Any]:
    text_nodes = tree.xpath("/tei:TEI/tei:text", namespaces=NS)
    if not text_nodes:
        raise ValueError(f"TEI has no /TEI/text element: {tei_path}")
    text = text_nodes[0]
    records_by_id = {record["id"]: record for record in records}
    records_by_div = {
        div: record["id"]
        for div in record_divs
        for record in records
        if record["id"].endswith(f"/{derive_address(div)}")
    }
    previous: dict[tuple[str, str, str], list[tuple[etree._Element, tuple[int, int]]]] = {}
    nodes: list[dict[str, Any]] = []
    classes: dict[str, dict[str, int]] = {}

    for node in text.iter():
        local = _local(node)
        base = classify_base(node)
        if base is None:
            if not _canonical_text(node):
                continue
            raise ValueError(f"unclassified TEI element fails closed: {local} at {derive_address(node)}")

        canonical = _canonical_text(node)
        if base == "dropped":
            disposition = "dropped"
            reason_code = drop_reason(node)
        elif base == "structural":
            disposition = "structural"
            reason_code = structural_reason(local)
        elif base in {"delivered", "normalized"}:
            disposition = base if canonical else "empty"
            reason_code = (
                "empty.text-bearing"
                if disposition == "empty"
                else rule_for(local).reason_code if disposition == "normalized" else None
            )
        else:
            raise ValueError(f"unsupported projection role {base!r} for {local}")

        entry: dict[str, Any] = {
            "address": derive_address(node),
            "element": local,
            "disposition": disposition,
        }
        if disposition in {"delivered", "normalized", "dropped"}:
            entry["canonical_text_sha256"] = _sha256_text(canonical)
            entry["canonical_text_length"] = len(canonical)
        elif disposition == "empty":
            entry["canonical_text_length"] = 0
        if reason_code is not None:
            entry["reason_code"] = reason_code
        if disposition in {"delivered", "normalized"}:
            targets = _targets_for_node(
                node,
                canonical,
                records_by_div,
                records_by_id,
                record_divs,
                previous,
            )
            if not targets:
                raise ValueError(
                    f"no exact output target for {local} at {derive_address(node)}"
                )
            entry["targets"] = [target.as_dict() for target in targets]

        class_counts = classes.setdefault(local, {disposition_name: 0 for disposition_name in DISPOSITIONS})
        class_counts[disposition] += 1
        nodes.append(entry)

    totals = {
        "addressable_nodes": len(nodes),
        **{disposition: sum(1 for node in nodes if node["disposition"] == disposition) for disposition in DISPOSITIONS},
    }
    return {
        "receipt_schema": "loss-receipt-v2",
        "projection": {
            "id": PROFILE_ID,
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
) -> dict[str, Any]:
    tree = etree.parse(str(tei_path))
    records, record_divs = _build_records(tree, tei_path)
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with output_jsonl.open("w", encoding="utf-8", newline="\n") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    receipt = _ledger(tree, tei_path, output_jsonl, records, record_divs, repo_root)
    target_receipt = receipt_path or output_jsonl.with_suffix(output_jsonl.suffix + ".loss.json")
    target_receipt.parent.mkdir(parents=True, exist_ok=True)
    target_receipt.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
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
