"""Strict, independent verification for loss-receipt-v2."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema
from lxml import etree

from build.lib.paths import REPO_ROOT
from ocd_kernel.lib.schema_enums import resolve_schema_path
from ocd_kernel.tei.normalization import normalize_inline, normalize_block
from ocd_kernel.tei.projection_profile import (
    DROP_ELEMENTS,
    classify_base,
    destination_for,
    drop_reason,
    rule_for,
    structural_reason,
)
from ocd_kernel.tei.writer import TEI_NS, derive_address

NS = {"tei": TEI_NS}
DISPOSITIONS = ("delivered", "normalized", "structural", "dropped", "empty")
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
class ExpectedTarget:
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


@dataclass(frozen=True)
class ExpectedNode:
    element: str
    disposition: str
    canonical_text: str
    reason_code: str | None
    targets: tuple[ExpectedTarget, ...]


def _local(node: etree._Element) -> str:
    return etree.QName(node).localname


def _sha256_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _resolve_repo_path(repo_root: Path, relative_path: str) -> Path:
    return (repo_root / relative_path).resolve()


def _load_jsonl(path: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    records: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"invalid JSONL at line {line_number}: {exc.msg}")
            continue
        record_id = record.get("id") if isinstance(record, dict) else None
        if not isinstance(record_id, str):
            errors.append(f"JSONL line {line_number} has no string id")
            continue
        if record_id in records:
            errors.append(f"duplicate output record: {record_id}")
        records[record_id] = record
    return records, errors


def _load_receipt_schema() -> dict[str, Any]:
    return json.loads(resolve_schema_path("loss_receipt_v2").read_text(encoding="utf-8"))


def _validate_receipt_shape(receipt: dict[str, Any]) -> list[str]:
    validator = jsonschema.Draft202012Validator(
        _load_receipt_schema(), format_checker=jsonschema.FormatChecker()
    )
    return [error.message for error in sorted(validator.iter_errors(receipt), key=str)]


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
    """Render a node's text while omitting dropped descendants."""

    local = _local(node)
    if local in DROP_ELEMENTS:
        return ""
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


def _canonical_projected(node: etree._Element) -> str:
    local = _local(node)
    if local == "lg":
        return _projected_fragment(node)
    if local == "l":
        return normalize_inline(_projected_fragment(node))
    if local in {"p", "quote", "sp", "trailer"}:
        return normalize_block(_projected_fragment(node))
    return normalize_inline(_projected_fragment(node))


def _canonical_source(node: etree._Element) -> str:
    local = _local(node)
    if local == "lg":
        lines = [
            _canonical_source(child)
            for child in node
            if _local(child) == "l"
        ]
        return normalize_block("\n".join(lines))
    if local == "l":
        return normalize_inline(_source_fragment(node))
    if local in {"p", "quote", "sp", "trailer"}:
        return normalize_block(_source_fragment(node))
    return normalize_inline(_source_fragment(node))


def _canonical_text(node: etree._Element) -> str:
    if classify_base(node) == "dropped":
        return _canonical_source(node)
    if _local(node) == "sp":
        return _spoken_text(node)
    if destination_for(node) == "argument":
        return normalize_inline(_projected_fragment(node))
    return _canonical_projected(node)


def _direct_text(node: etree._Element) -> str:
    parts = [node.text or ""]
    parts.extend(child.tail or "" for child in node)
    return normalize_inline("".join(parts))


def _ids_from_path(path: Path) -> tuple[str, str]:
    suffix = ".tei.xml"
    if not path.name.endswith(suffix):
        raise ValueError(f"TEI filename must end with {suffix}: {path}")
    work_id, rendering_id = path.name.removesuffix(suffix).rsplit(".", 1)
    return work_id, rendering_id


def _record_id(tei_path: Path, div: etree._Element) -> str:
    work_id, rendering_id = _ids_from_path(tei_path)
    return f"{work_id}/{rendering_id}/{derive_address(div)}"


def _has_ancestor(node: etree._Element, local_names: frozenset[str]) -> bool:
    current = node.getparent()
    while current is not None:
        if _local(current) in local_names:
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
    node: etree._Element, record_ids: dict[etree._Element, str]
) -> etree._Element | None:
    current: etree._Element | None = node
    while current is not None:
        if current in record_ids:
            return current
        current = current.getparent()
    return None


def _under_div(node: etree._Element, div: etree._Element) -> bool:
    current: etree._Element | None = node
    while current is not None:
        if current is div:
            return True
        current = current.getparent()
    return False


def _content_roots(div: etree._Element) -> list[etree._Element]:
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

    visit(div)
    return roots


def _record_divs(text: etree._Element) -> list[etree._Element]:
    live = [
        div
        for div in text.xpath(".//tei:div", namespaces=NS)
        if classify_base(div) != "dropped"
    ]
    records: list[etree._Element] = []
    for div in live:
        direct_argument = div.find("./tei:argument", namespaces=NS)
        if _content_roots(div) or (direct_argument is not None and _canonical_text(direct_argument)):
            records.append(div)

    # A <head> does not by itself make a div a record: its destination is
    # title_path, and it is normally delivered through the title_path of every
    # descendant record it governs. The exception is a head-bearing div that
    # governs NO content record at all -- a standalone divider such as Standard
    # Ebooks' <div type="part"><head>Part I</head></div>. _governing_records only
    # reaches descendant-or-self records, so such a heading would have nowhere to
    # be delivered and its text would be silently lost. Give only those divs a
    # record. Minting one for every head-bearing div instead would add a
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


def _render_block(node: etree._Element) -> str:
    if _local(node) != "sp":
        return _canonical_text(node)
    speakers = [
        _canonical_text(child)
        for child in node
        if _local(child) == "speaker" and _canonical_text(child)
    ]
    body = _spoken_parts(node)
    if speakers and body:
        return "\n".join(speakers + ["\n\n".join(body)])
    return "\n\n".join(speakers + body) or _canonical_text(node)


def _spoken_parts(node: etree._Element) -> list[str]:
    return [
        _canonical_text(child)
        for child in node
        if _local(child) != "speaker"
        and _local(child) in BLOCK_ROOTS
        and _canonical_text(child)
    ]


def _spoken_text(node: etree._Element) -> str:
    if _speech_is_record_block(node):
        return "\n\n".join(_spoken_parts(node))
    pieces: list[str] = []
    if node.text:
        pieces.append(_fragment_part(node.text))
    for child in node:
        if _local(child) != "speaker" and classify_base(child) != "dropped":
            pieces.append(_projected_fragment(child))
        if child.tail:
            pieces.append(_fragment_part(child.tail))
    return normalize_block("".join(pieces))


def _speech_is_record_block(node: etree._Element) -> bool:
    ancestor = node.getparent()
    while ancestor is not None and _local(ancestor) != "div":
        if _local(ancestor) in BLOCK_ROOTS:
            return False
        ancestor = ancestor.getparent()
    return True


def _immediate_speaker(node: etree._Element) -> str | None:
    values = [
        _canonical_projected(child)
        for child in node
        if _local(child) == "speaker" and _canonical_projected(child)
    ]
    if len(values) != 1:
        return values[0] if values else None
    return values[0]


def _record_owned_speeches(record_div: etree._Element) -> list[etree._Element]:
    speeches: list[etree._Element] = []

    def descend(parent: etree._Element) -> None:
        for child in parent:
            if _local(child) == "div" or classify_base(child) == "dropped":
                continue
            if _local(child) == "sp":
                speeches.append(child)
            descend(child)

    descend(record_div)
    return speeches


def _reconstruct_speeches(
    record_div: etree._Element, record_text: str
) -> list[dict[str, Any]]:
    speeches: list[dict[str, Any]] = []
    search_from = 0
    for speech in _record_owned_speeches(record_div):
        spoken = _spoken_text(speech)
        start = record_text.find(spoken, search_from) if spoken else -1
        if start >= 0:
            speeches.append(
                {
                    "speaker": _immediate_speaker(speech),
                    "text": spoken,
                    "char_start": start,
                    "char_end": start + len(spoken),
                }
            )
            search_from = start + len(spoken)
    return speeches


def _header_title(tree: etree._ElementTree) -> str:
    titles = tree.xpath(".//tei:titleStmt/tei:title", namespaces=NS)
    return normalize_inline(_source_fragment(titles[0])) if titles else ""


def _first_direct_head(div: etree._Element) -> str | None:
    head = div.find("./tei:head", namespaces=NS)
    if head is None:
        return None
    value = _canonical_text(head)
    return value or None


def _head_ancestor(node: etree._Element) -> etree._Element | None:
    current: etree._Element | None = node
    while current is not None:
        if _local(current) == "head":
            return current
        current = current.getparent()
    return None


def _title_path(title: str, div: etree._Element) -> list[str]:
    divs = [
        ancestor
        for ancestor in reversed(list(div.iterancestors()))
        if _local(ancestor) == "div" and classify_base(ancestor) != "dropped"
    ]
    divs.append(div)
    values = [title]
    for current in divs:
        for head_node in current.xpath("./tei:head", namespaces=NS):
            head = _canonical_text(head_node)
            if head and (not values or values[-1] != head):
                values.append(head)
    return values


def _build_expected_records(
    tree: etree._ElementTree, tei_path: Path
) -> tuple[list[dict[str, Any]], list[etree._Element]]:
    text_nodes = tree.xpath("/tei:TEI/tei:text", namespaces=NS)
    if not text_nodes:
        return [], []
    text = text_nodes[0]
    record_divs = _record_divs(text)
    title = _header_title(tree) or _ids_from_path(tei_path)[0]
    records: list[dict[str, Any]] = []
    for div in record_divs:
        blocks = _content_roots(div)
        rendered_blocks = [_render_block(block) for block in blocks]
        argument = div.find("./tei:argument", namespaces=NS)
        argument_text = _canonical_text(argument) if argument is not None else ""
        record = {
                "id": _record_id(tei_path, div),
                "text": "\n\n".join(rendered_blocks),
                "argument": argument_text or None,
                "title_path": _title_path(title, div),
            }
        speeches = _reconstruct_speeches(div, record["text"])
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


def _governing_records(
    head: etree._Element, record_divs: list[etree._Element], record_ids: dict[etree._Element, str]
) -> list[tuple[etree._Element, str]]:
    owning_div = _nearest_div(head)
    if owning_div is None:
        return []
    return [
        (div, record_ids[div])
        for div in record_divs
        if _is_descendant_or_self(div, owning_div)
    ]


def _block_root(node: etree._Element, record_div: etree._Element) -> etree._Element | None:
    current: etree._Element | None = node
    while current is not None and current is not record_div:
        local = _local(current)
        if local in BLOCK_ROOTS:
            if local == "p" and _has_ancestor(current, frozenset({"argument"})):
                return None
            return current
        if local in {"head", "argument", "note", "pb", "div"}:
            return None
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


def _expected_nodes(
    tree: etree._ElementTree,
    tei_path: Path,
    record_divs: list[etree._Element],
    expected_records: list[dict[str, Any]],
) -> tuple[dict[str, ExpectedNode], list[str]]:
    text_nodes = tree.xpath("/tei:TEI/tei:text", namespaces=NS)
    if not text_nodes:
        return {}, ["TEI has no /TEI/text element"]
    text = text_nodes[0]
    record_ids = {div: _record_id(tei_path, div) for div in record_divs}
    records_by_id = {record["id"]: record for record in expected_records}
    expected: dict[str, ExpectedNode] = {}
    errors: list[str] = []
    previous: dict[tuple[str, str, str], list[tuple[etree._Element, tuple[int, int]]]] = {}

    for element in text.iter():
        address = derive_address(element)
        local = _local(element)
        base = classify_base(element)
        if base is None:
            if not _canonical_text(element):
                continue
            errors.append(f"unknown TEI element fails closed: {local} at {address}")
            continue
        if base == "delivered" and local == "sp" and _direct_text(element):
            errors.append(f"delivered <sp> has unmapped direct text: {address}")
        canonical = _canonical_text(element)
        if base == "structural":
            if _direct_text(element):
                errors.append(f"structural element has unmapped direct text: {address}")
            expected[address] = ExpectedNode(
                local, "structural", "", structural_reason(local), ()
            )
            continue
        if base == "dropped":
            expected[address] = ExpectedNode(local, "dropped", canonical, drop_reason(element), ())
            continue
        if base not in {"delivered", "normalized"}:
            errors.append(f"profile returned unsupported role {base!r} for {address}")
            continue
        disposition = "empty" if not canonical else base
        if disposition == "empty":
            expected[address] = ExpectedNode(local, "empty", "", "empty.text-bearing", ())
            continue

        targets: list[ExpectedTarget] = []
        field = destination_for(element)
        if local in {"sp", "speaker"}:
            record_div = _nearest_record_div(element, record_ids)
            speech_node = element if local == "sp" else element.getparent()
            if (
                record_div is None
                or speech_node is None
                or _local(speech_node) != "sp"
            ):
                errors.append(f"speech node has no governing output record: {address}")
            else:
                record_id = record_ids[record_div]
                record = records_by_id[record_id]
                speech_nodes = _record_owned_speeches(record_div)
                try:
                    speech_index = speech_nodes.index(speech_node)
                except ValueError:
                    errors.append(f"speech node has no structured item: {address}")
                else:
                    item_field = "text" if local == "sp" else "speaker"
                    speech_items = record.get("speeches", [])
                    if (
                        speech_index >= len(speech_items)
                        or speech_items[speech_index].get(item_field) != canonical
                    ):
                        errors.append(f"structured speech value mismatch for {address}")
                    else:
                        targets.append(
                            ExpectedTarget(
                                record_id,
                                "speeches",
                                0,
                                len(canonical),
                                speech_index,
                                item_field,
                            )
                        )
                    item = speech_items[speech_index]
                    if local == "sp":
                        span = (item["char_start"], item["char_end"])
                    else:
                        end = item["char_start"]
                        while end > 0 and record["text"][end - 1].isspace():
                            end -= 1
                        start = end - len(canonical)
                        span = (start, end) if start >= 0 else None
                        if span is not None and record["text"][start:end] != canonical:
                            span = None
                    if span is None:
                        errors.append(f"speech value has no flat-text span for {address}")
                    else:
                        targets.append(
                            ExpectedTarget(record_id, "text", span[0], span[1])
                        )
        elif field == "title_path":
            governing_head = _head_ancestor(element)
            if governing_head is None:
                errors.append(f"title-path node has no governing head: {address}")
                governing_records: list[tuple[etree._Element, str]] = []
            else:
                governing_records = _governing_records(
                    governing_head, record_divs, record_ids
                )
            title = _canonical_text(governing_head) if governing_head is not None else ""
            for record_div, record_id in governing_records:
                title_path = records_by_id[record_id]["title_path"]
                try:
                    item_index = title_path.index(title)
                except ValueError:
                    errors.append(f"title-path text missing for {address} in {record_id}")
                    continue
                start = title_path[item_index].find(canonical)
                if start < 0:
                    errors.append(f"title-path span missing for {address} in {record_id}")
                    continue
                targets.append(
                    ExpectedTarget(record_id, field, start, start + len(canonical), item_index)
                )
        else:
            record_div = _nearest_record_div(element, record_ids)
            if record_div is None or record_div not in record_ids:
                errors.append(f"no governing output record for delivered node: {address}")
            else:
                record_id = record_ids[record_div]
                record = records_by_id[record_id]
                if field is None:
                    errors.append(f"no target field declared for {address}")
                elif field == "text" and _block_root(element, record_div) is None:
                    errors.append(f"delivered text node has no output block: {address}")
                else:
                    value = record.get(field)
                    if not isinstance(value, str):
                        errors.append(f"target field is not a string for {address}: {field}")
                    else:
                        key = (record_id, field, canonical)
                        span = _find_target_span(value, canonical, element, previous, key)
                        if span is None:
                            errors.append(f"canonical text has no exact output span for {address}")
                        else:
                            targets.append(ExpectedTarget(record_id, field, span[0], span[1]))
        expected[address] = ExpectedNode(
            local,
            disposition,
            canonical,
            rule_for(local).reason_code if disposition == "normalized" else None,
            tuple(targets),
        )
    return expected, errors


def _receipt_nodes(receipt: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    entries: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for entry in receipt.get("nodes", []):
        address = entry.get("address")
        if address in entries:
            errors.append(f"duplicate ledger node: {address}")
        entries[address] = entry
    return entries, errors


def _target_key(target: dict[str, Any]) -> tuple[str, str, int | None, str | None, int, int]:
    return (
        target["record_id"],
        target["field"],
        target.get("item_index"),
        target.get("item_field"),
        target["char_start"],
        target["char_end"],
    )


def _expected_target_key(
    target: ExpectedTarget,
) -> tuple[str, str, int | None, str | None, int, int]:
    return (
        target.record_id,
        target.field,
        target.item_index,
        target.item_field,
        target.char_start,
        target.char_end,
    )


def _check_counts(receipt: dict[str, Any], entries: dict[str, dict[str, Any]], errors: list[str]) -> None:
    totals = {"addressable_nodes": len(entries)}
    for disposition in DISPOSITIONS:
        totals[disposition] = sum(
            1 for entry in entries.values() if entry.get("disposition") == disposition
        )
    if receipt.get("totals") != totals:
        errors.append(f"totals mismatch: receipt={receipt.get('totals')} computed={totals}")

    classes: dict[str, dict[str, int]] = {}
    for entry in entries.values():
        element = entry.get("element")
        classes.setdefault(element, {disposition: 0 for disposition in DISPOSITIONS})[
            entry.get("disposition")
        ] += 1
    if receipt.get("classes") != classes:
        errors.append("classes mismatch")


def check_receipt_v2(receipt_path: Path, *, repo_root: Path = REPO_ROOT) -> list[str]:
    """Return strict v2 verification errors; an empty list means PASS."""

    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"could not read receipt: {exc}"]
    shape_errors = _validate_receipt_shape(receipt)
    if shape_errors:
        return [f"schema: {error}" for error in shape_errors]

    errors: list[str] = []
    ir_path = _resolve_repo_path(repo_root, receipt["ir"]["path"])
    output_path = _resolve_repo_path(repo_root, receipt["output"]["path"])
    if not ir_path.is_file():
        return [f"IR path does not exist: {ir_path}"]
    if not output_path.is_file():
        return [f"output path does not exist: {output_path}"]
    if _sha256_bytes(ir_path) != receipt["ir"]["sha256"]:
        errors.append("IR sha256 mismatch")
    if _sha256_bytes(output_path) != receipt["output"]["sha256"]:
        errors.append("output sha256 mismatch")

    records, record_errors = _load_jsonl(output_path)
    errors.extend(record_errors)
    try:
        tree = etree.parse(str(ir_path))
    except (OSError, etree.XMLSyntaxError) as exc:
        return errors + [f"could not parse IR: {exc}"]
    expected_records, record_divs = _build_expected_records(tree, ir_path)
    expected_by_id = {record["id"]: record for record in expected_records}
    for record_id in sorted(set(expected_by_id) - set(records)):
        errors.append(f"missing output record: {record_id}")
    for record_id in sorted(set(records) - set(expected_by_id)):
        errors.append(f"orphan output record: {record_id}")
    for record_id in sorted(set(expected_by_id) & set(records)):
        expected = expected_by_id[record_id]
        actual = records[record_id]
        for field in ("text", "argument", "title_path", "speeches"):
            if actual.get(field) != expected.get(field):
                errors.append(
                    f"output field mismatch for {record_id}.{field}: "
                    f"expected {expected.get(field)!r}, got {actual.get(field)!r}"
                )

    expected_nodes, node_build_errors = _expected_nodes(
        tree, ir_path, record_divs, expected_records
    )
    errors.extend(node_build_errors)
    entries, entry_errors = _receipt_nodes(receipt)
    errors.extend(entry_errors)
    expected_addresses = set(expected_nodes)
    for address in sorted(expected_addresses - set(entries)):
        errors.append(f"missing ledger node: {address}")
    for address in sorted(set(entries) - expected_addresses):
        errors.append(f"extra ledger node: {address}")

    for address, expected in expected_nodes.items():
        entry = entries.get(address)
        if entry is None:
            continue
        if entry.get("element") != expected.element:
            errors.append(f"element mismatch for {address}: {entry.get('element')} != {expected.element}")
        if entry.get("disposition") != expected.disposition:
            errors.append(
                f"disposition mismatch for {address}: {entry.get('disposition')} != {expected.disposition}"
            )
        if expected.disposition in {"delivered", "normalized", "dropped"}:
            expected_length = len(expected.canonical_text)
            if entry.get("canonical_text_length") != expected_length:
                errors.append(f"canonical length mismatch for {address}")
            if entry.get("canonical_text_sha256") != _sha256_text(expected.canonical_text):
                errors.append(f"canonical hash mismatch for {address}")
        elif expected.disposition == "empty":
            if entry.get("canonical_text_length") != 0:
                errors.append(f"empty node has nonzero canonical length for {address}")
        if expected.reason_code is not None and entry.get("reason_code") != expected.reason_code:
            errors.append(
                f"reason mismatch for {address}: {entry.get('reason_code')} != {expected.reason_code}"
            )
        actual_targets = entry.get("targets", [])
        actual_keys = sorted(_target_key(target) for target in actual_targets)
        expected_keys = sorted(_expected_target_key(target) for target in expected.targets)
        if actual_keys != expected_keys:
            errors.append(f"target set mismatch for {address}")
        for target in actual_targets:
            record = records.get(target.get("record_id"))
            if record is None:
                errors.append(f"target record missing for {address}: {target.get('record_id')}")
                continue
            field = target.get("field")
            if field == "title_path":
                index = target.get("item_index")
                value = record.get("title_path", [])[index] if isinstance(index, int) and index < len(record.get("title_path", [])) else None
            elif field == "speeches":
                index = target.get("item_index")
                item_field = target.get("item_field")
                speeches = record.get("speeches", [])
                value = (
                    speeches[index].get(item_field)
                    if isinstance(index, int)
                    and index < len(speeches)
                    and item_field in {"speaker", "text"}
                    else None
                )
            else:
                value = record.get(field)
            start = target.get("char_start")
            end = target.get("char_end")
            if not isinstance(value, (str, list)) or not isinstance(start, int) or not isinstance(end, int):
                errors.append(f"invalid target evidence for {address}")
                continue
            if start >= end or end > len(value):
                errors.append(f"target span out of bounds for {address}")
                continue
            if isinstance(value, str) and value[start:end] != expected.canonical_text:
                errors.append(f"target slice mismatch for {address}")
    _check_counts(receipt, entries, errors)
    return errors


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt_path", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    errors = check_receipt_v2(args.receipt_path)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
