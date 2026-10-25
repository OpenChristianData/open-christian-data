"""Prepare readable, source-native Douay context from the frozen candidate TEI.

The candidate and the exhaustive private event ledger are inputs, never outputs.
This companion carries nonverse fields and verse-local apparatus in book and
reference-document order. The verse wording remains in the Bible projection.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

from lxml import etree


ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "reports/_logs/original-douay-rheims-current-reconciliation-20261002-v1"
SOURCE = LOG / "renewed-native-v1/content.tei.xml"
INVENTORY = LOG / "renewed-native-v1/source-field-inventory.json"
DEFAULT_OUT = LOG / "readable-companion-v2"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
EXPECTED_SOURCE_SHA = "4f47a4a914c1a98c23cfdeabebbe708bbd2f77550f2b4d917aba06e31437ea37"
MAX_NOTICE_BYTES = 65536


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def local(node: etree._Element) -> str:
    return etree.QName(node).localname


def alias(node: etree._Element) -> dict[str, str]:
    value = node.get("corresp", "")
    if not value.startswith("source-attributes:"):
        return {}
    return json.loads(unquote(value.removeprefix("source-attributes:")))


def source_field(node: etree._Element) -> bool:
    return (node.get(XML_ID) or "").startswith("odr-source-field-")


def prose(node: etree._Element) -> str:
    """Render literal wording with visible source styles and marker positions."""
    chunks = [html.escape(node.text or "", quote=False)]
    for child in node:
        name = local(child)
        if name == "lb":
            chunks.append("<br/>")
        elif name == "hi":
            value = prose(child)
            rendition = child.get("rend", "")
            if rendition == "italic":
                chunks.append(f"<em>{value}</em>")
            elif rendition == "small-caps":
                chunks.append(f"<span class=\"source-small-caps\">{value}</span>")
            elif rendition == "ref-title-sub":
                chunks.append(f"<span class=\"source-reference-title-sub\">{value}</span>")
            else:
                raise ValueError(f"Unsupported retained inline rendition: {rendition}")
        elif name == "seg":
            kind = child.get("type", "")
            value = prose(child)
            if kind in {"marginal-note-marker", "note-anchor", "cross-reference-marker", "column-left", "column-right"}:
                chunks.append(value)
            else:
                raise ValueError(f"Unsupported retained segment role: {kind}")
        else:
            raise ValueError(f"Unsupported retained inline node: {name}")
        chunks.append(html.escape(child.tail or "", quote=False))
    return "".join(chunks)


def source_label(node: etree._Element) -> str:
    kind = node.get("type") or local(node)
    number = node.get("n")
    if kind == "source-null-absence:source-language-title":
        return "Source language title absent (JSON null; not authored text)"
    return kind.replace("-", " ").title() + (f" {number}" if number else "")


def render_field(node: etree._Element, used: list[str]) -> str:
    identity = node.get(XML_ID)
    if not identity or not identity.startswith("odr-source-field-"):
        raise ValueError("Expected a source-field identity")
    used.append(identity)
    if node.get("type") == "source-null-absence:source-language-title":
        if node.text != "null" or len(node):
            raise ValueError("Unexpected source-null field")
        return "*Source language title absent (JSON null; not authored text).*\n\n"
    body = prose(node)
    # The prose may contain literal line breaks; pre preserves them while the
    # explicit TEI-style tags preserve inline role and ordering.
    return f"**{source_label(node)}**\n\n<pre style=\"white-space: pre-wrap\">{body}</pre>\n\n"


def verse_cues(verse: etree._Element) -> list[str]:
    cues: list[str] = []
    for node in verse.iter():
        if node is verse:
            continue
        kind = node.get("type")
        if local(node) == "hi":
            cues.append(f"style {node.get('rend', 'unspecified')}: {prose(node)}")
        elif kind in {"note-anchor", "cross-reference-marker", "marginal-note-marker", "alternate-reading", "column-left", "column-right"}:
            cues.append(f"{kind.replace('-', ' ')}: {prose(node)}")
        elif local(node) == "lb":
            cues.append("source line break")
    return cues


def render_verse_group(node: etree._Element, used: list[str]) -> str:
    verse = next((child for child in node if child.get("type") == "verse"), None)
    if verse is None:
        raise ValueError("Source verse group lacks verse field")
    notes = [child for child in node if source_field(child) and child is not verse]
    cues = verse_cues(verse)
    chapter = node.getparent()
    chapter_zero = chapter is not None and chapter.get("type") == "chapter" and chapter.get("n") == "0"
    if not notes and not cues and not chapter_zero:
        return ""
    number = node.get("n")
    if not number:
        raise ValueError("Verse context lacks source label")
    result = [f"**Verse {number} context** — verse wording is in its Bible row.\n\n"]
    if cues:
        result.append("Source inline cues, in order: " + "; ".join(cues) + ".\n\n")
    for note in notes:
        result.append(render_field(note, used))
    return "".join(result)


def render_blocks(node: etree._Element, used: list[str], depth: int = 2, context: tuple[str, ...] = ()):
    if node.get("type") == "source-verse-group":
        block = render_verse_group(node, used)
        if block:
            yield block, context
        return
    if source_field(node):
        if node.get("type") == "verse":
            return
        yield render_field(node, used), context
        return
    if local(node) == "div":
        kind = node.get("type", "source division").replace("-", " ").title()
        number = node.get("n")
        label = kind + (f" {number}" if number else "")
        structural_only = node.get("type") in {"reference-field", "reference-list"}
        if not structural_only:
            yield f"{'#' * min(depth, 6)} {label}\n\n", context
        context = (*context, label)
    elif (node.text or "").strip():
        raise ValueError(f"Unaccounted text in {local(node)}")
    for child in node:
        yield from render_blocks(child, used, depth + 1 if local(node) == "div" else depth, context)
        if (child.tail or "").strip():
            raise ValueError(f"Unaccounted tail after {local(child)}")


def unit_name(node: etree._Element) -> tuple[str, str]:
    kind = node.get("type")
    attributes = alias(node)
    member = attributes.get("source")
    if not member:
        raise ValueError(f"{kind} lacks source member")
    if kind == "book":
        name = node.get("n")
        if not name:
            raise ValueError("Book lacks source name")
        return f"book-{name}", member
    if kind == "reference-document":
        test = attributes.get("subtype", "unknown")
        name = node.get("n")
        if not name:
            raise ValueError("Reference document lacks source name")
        return f"reference-{test}-{name}", member
    raise ValueError(f"Unsupported unit type: {kind}")


def chunks_for_unit(unit: etree._Element, member: str, used: list[str]) -> list[tuple[bytes, list[str]]]:
    kind = unit.get("type")
    title = next(("".join(child.itertext()).strip() for child in unit if local(child) == "head"), unit.get("n", ""))
    prefix = (
        f"# {title}\n\nRetained member: `{member}`. "
        "Verse wording is in the Bible rows. Bracketed source markers and "
        "lettered note anchors retain their order; notes appear under the "
        "same source section or verse label. Italic and small-cap renditions "
        "follow the retained inline markup.\n\n"
    )
    chunks: list[tuple[bytes, list[str]]] = []
    current = prefix
    current_fields: list[str] = []
    prior_used = len(used)
    blocks = (block for child in unit for block in render_blocks(child, used, 2))
    for piece, context in blocks:
        block_fields = used[prior_used:]
        prior_used = len(used)
        if len((current + piece).encode("utf-8")) > MAX_NOTICE_BYTES and current != prefix:
            chunks.append((current.encode("utf-8"), current_fields))
            location = " > ".join(context) if context else "source unit"
            current = prefix + f"Continued in source order at {location}.\n\n"
            current_fields = []
        if len((current + piece).encode("utf-8")) > MAX_NOTICE_BYTES:
            raise ValueError(f"A single {kind} section exceeds notice limit: {member}")
        current += piece
        current_fields.extend(block_fields)
    chunks.append((current.encode("utf-8"), current_fields))
    return chunks


def build(output: Path, sample: bool) -> dict:
    raw = SOURCE.read_bytes()
    if sha(raw) != EXPECTED_SOURCE_SHA:
        raise ValueError("Frozen renewed TEI changed")
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    pointers = {"odr-source-field-" + sha(x["pointer"].encode()): x["pointer"] for x in inventory}
    root = etree.fromstring(raw)
    text = root.find(TEI + "text")
    if text is None:
        raise ValueError("TEI text missing")
    units = [node for node in text.iter(TEI + "div") if node.get("type") in {"book", "reference-document"}]
    if len(units) != 102:
        raise ValueError(f"Expected 76 books and 26 documents, found {len(units)}")
    expected = set(pointers)
    # A verse field is identified by the actual TEI role rather than a pointer
    # suffix, because source reference fields may also end in /text.
    verse_ids = {node.get(XML_ID) for node in text.iter(TEI + "ab") if node.get("type") == "verse"}
    expected -= verse_ids
    selected = ([units[0], next(node for node in units if node.get("type") == "book" and node.get("n") == "genesis")] if sample else units)
    manifest = []
    crosswalk: list[dict[str, str | int]] = []
    all_used: list[str] = []
    for unit in selected:
        name, member = unit_name(unit)
        used: list[str] = []
        parts = chunks_for_unit(unit, member, used)
        all_used.extend(used)
        for index, (data, field_ids) in enumerate(parts, 1):
            path = output / name / f"part-{index:03d}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            relative = path.relative_to(output).as_posix()
            manifest.append({"path": relative, "sha256": sha(data), "bytes": len(data), "member": member, "fields": len(field_ids)})
            crosswalk.extend({"field_id": identity, "pointer": pointers[identity], "part": relative, "position": position} for position, identity in enumerate(field_ids, 1))
    disposition = [node for node in text.iter(TEI + "note") if node.get("type") == "source-disposition"]
    if len(disposition) != 1 or len(disposition[0]) or not disposition[0].text:
        raise ValueError("Expected one literal collection disposition note")
    if not sample:
        data = (
            "# Collection context\n\n"
            "The retained release includes two identically valued Prayer members. "
            "This candidate's explicit disposition is:\n\n"
            f'<pre style="white-space: pre-wrap">{html.escape(disposition[0].text, quote=False)}</pre>\n'
        ).encode("utf-8")
        path = output / "collection-context.md"
        path.write_bytes(data)
        manifest.append({"path": path.relative_to(output).as_posix(), "sha256": sha(data), "bytes": len(data), "member": "collection-disposition", "fields": 0})
    if len(set(all_used)) != len(all_used):
        raise ValueError("A nonverse field was rendered twice")
    if not sample and set(all_used) != expected:
        raise ValueError(f"Nonverse field coverage differs: expected {len(expected)}, rendered {len(set(all_used))}")
    if any(identity not in pointers for identity in all_used):
        raise ValueError("Rendered field has no exact source pointer")
    if len(crosswalk) != len(all_used):
        raise ValueError("Rendered notice crosswalk differs from source-field count")
    raw_nonverse_bytes = sum(
        len("".join(node.itertext()).encode("utf-8"))
        for node in text.iter()
        if (node.get(XML_ID) or "") in expected
    ) + len(disposition[0].text.encode("utf-8"))
    if raw_nonverse_bytes != 3781838:
        raise ValueError(f"Literal nonverse text/tail byte total differs: {raw_nonverse_bytes}")
    if any(entry["bytes"] > MAX_NOTICE_BYTES for entry in manifest):
        raise ValueError("A readable notice exceeds the 64 KiB boundary")
    report = {"status": "sample" if sample else "pass", "source_sha256": EXPECTED_SOURCE_SHA, "units": len(selected), "notice_parts": len(manifest), "nonverse_fields": len(all_used), "expected_nonverse_fields": len(expected), "literal_nonverse_bytes": raw_nonverse_bytes, "max_notice_bytes": MAX_NOTICE_BYTES, "parts": manifest}
    (output / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "private-crosswalk.json").write_text(json.dumps(crosswalk, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--sample", action="store_true")
    args = parser.parse_args()
    print(json.dumps({key: value for key, value in build(args.output, args.sample).items() if key != "parts"}, indent=2))


if __name__ == "__main__":
    main()
