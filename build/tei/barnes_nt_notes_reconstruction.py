"""Loss-accounted TEI projection of the exact retained Barnes SWORD module."""

from __future__ import annotations

import configparser
import hashlib
import json
from collections import Counter
from html import unescape
from html.parser import HTMLParser
import re
import struct
import zlib
from pathlib import Path
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest
from ocd_kernel.library.acquisitions import validate_acquisition

CONVERTER_ID = "ocd-barnes-sword-zcom-to-tei"
CONVERTER_VERSION = "3"
_TEI = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_MODULE = "raw/sword_modules/Barnes/modules/comments/zcom/barnes"
_ACQUISITION = "library/works/barnes-nt-notes/forms/barnes-english/editions/crosswire-sword-v1.1/acquisitions/barnes-sword-v1.1.json"
_EXPECTED = {
    "nt.czv": (82460, "edd2d46416db52595af44811a49940527bba208bd6b73b7c30f480c21d63edae"),
    "nt.czz": (6018995, "d26ada7eba82d4c0c24c18ad8d8a520c1dfd5761e2bdc8161c6888bc665ea40a"),
    "nt.czs": (3120, "a39f80ec47d108a43fda634c1234fc03827f32eac1636d614c01b424dfcf6302"),
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _utf8_sequence_end(data: bytes, start: int) -> tuple[int, str | None]:
    """Return one strict UTF-8 sequence boundary, without decoding bad bytes."""
    lead = data[start]
    if lead <= 0x7F:
        return start + 1, None
    if 0xC2 <= lead <= 0xDF:
        length, second_min, second_max = 2, 0x80, 0xBF
    elif lead == 0xE0:
        length, second_min, second_max = 3, 0xA0, 0xBF
    elif 0xE1 <= lead <= 0xEC or 0xEE <= lead <= 0xEF:
        length, second_min, second_max = 3, 0x80, 0xBF
    elif lead == 0xED:
        length, second_min, second_max = 3, 0x80, 0x9F
    elif lead == 0xF0:
        length, second_min, second_max = 4, 0x90, 0xBF
    elif 0xF1 <= lead <= 0xF3:
        length, second_min, second_max = 4, 0x80, 0xBF
    elif lead == 0xF4:
        length, second_min, second_max = 4, 0x80, 0x8F
    else:
        return start + 1, "invalid-utf8"

    for relative in range(1, length):
        offset = start + relative
        if offset >= len(data):
            return len(data), "invalid-utf8"
        byte = data[offset]
        lower, upper = (second_min, second_max) if relative == 1 else (0x80, 0xBF)
        if not lower <= byte <= upper:
            return offset, "invalid-utf8"
    return start + length, None


def _xml10_character(codepoint: int) -> bool:
    return (
        codepoint in {0x9, 0xA, 0xD}
        or 0x20 <= codepoint <= 0xD7FF
        or 0xE000 <= codepoint <= 0xFFFD
        or 0x10000 <= codepoint <= 0x10FFFF
    )


def _byte_ranges(data: bytes) -> list[dict[str, object]]:
    """Partition a carrier into maximal TEI-safe and exact unrepresentable byte runs."""
    groups: list[dict[str, object]] = []

    def append(start: int, end: int, state: str, cause: str | None = None) -> None:
        previous = groups[-1] if groups else None
        if previous is not None and previous["end"] == start and previous["state"] == state and previous.get("cause") == cause:
            previous["end"] = end
            return
        item: dict[str, object] = {"start": start, "end": end, "state": state}
        if state == "unrepresentable":
            item["cause"] = cause
        groups.append(item)

    offset = 0
    while offset < len(data):
        end, invalid_cause = _utf8_sequence_end(data, offset)
        if invalid_cause is not None:
            append(offset, end, "unrepresentable", invalid_cause)
            offset = end
            continue
        character = data[offset:end].decode("utf-8", errors="strict")
        if _xml10_character(ord(character)):
            append(offset, end, "represented")
        else:
            append(offset, end, "unrepresentable", "xml-1.0-forbidden-character")
        offset = end
    ranges: list[dict[str, object]] = []
    for group in groups:
        start, end = int(group["start"]), int(group["end"])
        raw = data[start:end]
        item = {**group, "bytes": len(raw), "sha256": _sha(raw), "hex": raw.hex()}
        if group["state"] == "unrepresentable":
            item["reason"] = "unrepresentable"
        ranges.append(item)
    return ranges


def _source_with_gap_markers(data: bytes, ranges: list[dict[str, object]], slot: int) -> tuple[str, dict[str, dict[str, object]]]:
    safe_text = "".join(
        data[int(item["start"]) : int(item["end"])].decode("utf-8", errors="strict")
        for item in ranges
        if item["state"] == "represented"
    )
    used_characters = set(safe_text)
    tokens: dict[str, dict[str, object]] = {}
    pieces: list[str] = []
    marker_codepoint = 0xF0000
    for item in ranges:
        if item["state"] == "represented":
            pieces.append(data[int(item["start"]) : int(item["end"])].decode("utf-8", errors="strict"))
            continue
        while chr(marker_codepoint) in used_characters or chr(marker_codepoint) in tokens:
            marker_codepoint += 1
            if marker_codepoint > 0xFFFFD:
                raise ValueError(f"Barnes slot {slot} has no collision-free internal gap marker")
        marker = chr(marker_codepoint)
        marker_codepoint += 1
        tokens[marker] = {"slot": slot, **item}
        pieces.append(marker)
    return "".join(pieces), tokens


def _carriers(manifest: SourceManifest) -> tuple[list[tuple[int, bytes]], dict[str, object]]:
    """Read each BZV slice independently of the legacy commentary converter."""
    root = manifest.repository_root
    files: dict[str, bytes] = {}
    for name, (size, digest) in _EXPECTED.items():
        data = (root / _MODULE / name).read_bytes()
        if len(data) != size or _sha(data) != digest:
            raise ValueError(f"retained Barnes {name} bytes do not match the ticket binding")
        files[name] = data
    index, compressed, block_index = files["nt.czv"], files["nt.czz"], files["nt.czs"]
    if len(index) % 10 or len(block_index) % 12:
        raise ValueError("Barnes SWORD indexes are not record-aligned")
    blocks: dict[int, bytes] = {}
    rows: list[tuple[int, bytes]] = []
    for slot, offset in enumerate(range(0, len(index), 10)):
        block, start, length = struct.unpack_from("<IIH", index, offset)
        if length == 0:
            payload = b""
        else:
            if block not in blocks:
                record = block * 12
                if record + 12 > len(block_index):
                    raise ValueError(f"Barnes BZV references missing block {block}")
                block_offset, compressed_length, expected_length = struct.unpack_from("<III", block_index, record)
                end = block_offset + compressed_length
                if compressed_length == 0 or end > len(compressed):
                    raise ValueError(f"Barnes BZS block {block} range is invalid")
                raw = zlib.decompress(compressed[block_offset:end])
                if len(raw) != expected_length:
                    raise ValueError(f"Barnes BZS block {block} length mismatch")
                blocks[block] = raw
            raw = blocks[block]
            if start + length > len(raw):
                raise ValueError(f"Barnes BZV slot {slot} exceeds block {block}")
            payload = raw[start : start + length]
        rows.append((slot, payload))
    ranges_by_slot = {slot: _byte_ranges(data) for slot, data in rows if data}
    invalid_utf8_slots = [slot for slot, ranges in ranges_by_slot.items() if any(item.get("cause") == "invalid-utf8" for item in ranges)]
    xml_incompatible_slots = [
        slot
        for slot, ranges in ranges_by_slot.items()
        if not any(item.get("cause") == "invalid-utf8" for item in ranges)
        and any(item.get("cause") == "xml-1.0-forbidden-character" for item in ranges)
    ]
    unrepresentable_byte_counts = {
        "invalid_utf8": sum(int(item["bytes"]) for ranges in ranges_by_slot.values() for item in ranges if item.get("cause") == "invalid-utf8"),
        "xml_1_0_forbidden": sum(int(item["bytes"]) for ranges in ranges_by_slot.values() for item in ranges if item.get("cause") == "xml-1.0-forbidden-character"),
    }
    unrepresentable_range_count = sum(1 for ranges in ranges_by_slot.values() for item in ranges if item["state"] == "unrepresentable")
    census = {
        "archive_sha256": "9e8edc0333875c214124371b3862df118ad3a76ade7753cb2faeed3484615baf",
        "member_hashes": {name: digest for name, (_size, digest) in _EXPECTED.items()},
        "slot_count": len(rows),
        "nonempty_slots": sum(bool(data) for _, data in rows),
        "empty_slots": sum(not data for _, data in rows),
        "payload_bytes": sum(len(data) for _, data in rows),
        "invalid_utf8_slots": invalid_utf8_slots,
        "xml_incompatible_slots": xml_incompatible_slots,
        "unrepresentable_byte_counts": unrepresentable_byte_counts,
        "unrepresentable_byte_count": sum(unrepresentable_byte_counts.values()),
        "unrepresentable_range_count": unrepresentable_range_count,
        "carrier_stream_sha256": _sha(b"".join(struct.pack("<II", slot, len(data)) + data for slot, data in rows)),
    }
    return rows, census


def _bible_positions(manifest: SourceManifest) -> tuple[list[dict[str, object]], str, dict[str, int], str]:
    """Derive every SWORD key from the bound module versification and KJV canon."""
    module = configparser.ConfigParser(interpolation=None)
    module.read_string(manifest.authority_path("retained-module-config").read_text(encoding="utf-8"))
    if "Barnes" not in module:
        raise ValueError("Barnes SWORD module configuration has no [Barnes] section")
    versification = module["Barnes"].get("Versification", "KJV").strip().upper()
    if versification != "KJV":
        raise ValueError(f"Barnes SWORD position map supports only the retained KJV versification, got {versification!r}")

    profile = json.loads(manifest.authority_path("reconstruction-profile").read_bytes())
    mapping = profile.get("mapping", {}).get("bible_positions", {})
    scheme = mapping.get("scheme")
    if scheme != "ocd-barnes-sword-kjv-position-v1" or mapping.get("versification") != versification:
        raise ValueError("Barnes profile does not bind the retained SWORD KJV position scheme")

    positions: list[dict[str, object]] = [
        {"kind": "module-heading", "key": "module-heading"},
        {"kind": "testament-heading", "key": "testament.2", "testament": 2},
    ]
    for book in mapping.get("books", []):
        osis = book.get("osis")
        chapter_verse_counts = book.get("chapter_verse_counts")
        if not isinstance(osis, str) or not isinstance(chapter_verse_counts, list) or not chapter_verse_counts:
            raise ValueError("Barnes KJV canon contains a malformed New Testament book")
        positions.append({"kind": "book-heading", "key": osis, "testament": 2, "osis_book": osis})
        for chapter, verse_count in enumerate(chapter_verse_counts, start=1):
            if not isinstance(verse_count, int) or isinstance(verse_count, bool) or verse_count < 1:
                raise ValueError(f"Barnes KJV canon has an invalid verse count for {osis}.{chapter}")
            positions.append({"kind": "chapter-heading", "key": f"{osis}.{chapter}", "testament": 2, "osis_book": osis, "chapter": chapter})
            positions.extend(
                {"kind": "verse", "key": f"{osis}.{chapter}.{verse}", "testament": 2, "osis_book": osis, "chapter": chapter, "verse": verse}
                for verse in range(1, verse_count + 1)
            )

    counts = dict(sorted(Counter(str(item["kind"]) for item in positions).items()))
    if counts != mapping.get("expected_counts"):
        raise ValueError("Barnes KJV position counts differ from the bound reconstruction profile")
    if len(positions) != profile.get("source_scope", {}).get("expected_slots"):
        raise ValueError("Barnes KJV key sequence does not cover every retained SWORD slot")
    position_stream = "\n".join(f"{slot}\t{item['kind']}\t{item['key']}" for slot, item in enumerate(positions)).encode("utf-8")
    position_digest = _sha(position_stream)
    if position_digest != mapping.get("position_stream_sha256"):
        raise ValueError("Barnes KJV position sequence differs from its profile-bound digest")
    return positions, scheme, counts, position_digest


class _ThmlToTei(HTMLParser):
    """Map the source's evidenced ThML subset and expose everything else."""

    _VOID_ELEMENTS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})

    def __init__(self, parent: etree._Element, source_text: str, slot: int, gap_tokens: Mapping[str, Mapping[str, object]] | None = None) -> None:
        super().__init__(convert_charrefs=True)
        self.parent = parent
        self.source_text = source_text
        self.slot = slot
        self.gap_tokens = dict(gap_tokens or {})
        self.seen_gap_tokens: set[str] = set()
        self.stack: list[dict[str, object]] = []
        self.mapped_elements: Counter[str] = Counter()
        self.unmapped_markup: list[dict[str, object]] = []
        self.structural_warnings: list[dict[str, object]] = []
        self.line_starts = [0]
        self.line_starts.extend(match.end() for match in re.finditer("\n", source_text))

    def _current_parent(self) -> etree._Element:
        for frame in reversed(self.stack):
            element = frame["element"]
            if element is not None:
                return element  # type: ignore[return-value]
        return self.parent

    def _append_text(self, value: str) -> None:
        if not value:
            return
        target = self._current_parent()
        if len(target):
            last = target[-1]
            last.tail = (last.tail or "") + value
        else:
            target.text = (target.text or "") + value

    def _record_unmapped(self, token: str, reason: str) -> None:
        self._append_text(token)
        self.unmapped_markup.append({"slot": self.slot, "token": token, "reason": reason})

    def _raw_end_tag(self, tag: str) -> str:
        line, column = self.getpos()
        if line <= len(self.line_starts):
            start = self.line_starts[line - 1] + column
            end = self.source_text.find(">", start)
            if end >= start and self.source_text[start : start + 2] == "</":
                return self.source_text[start : end + 1]
        return f"</{tag}>"

    def _new_mapped_element(self, tag: str, attributes: list[tuple[str, str | None]]) -> tuple[etree._Element, str] | None:
        parent = self._current_parent()
        if tag == "br" and not attributes:
            return etree.SubElement(parent, f"{{{_TEI}}}lb"), "br"
        if tag == "i" and not attributes:
            element = etree.SubElement(parent, f"{{{_TEI}}}hi")
            element.set("rend", "italic")
            return element, "i"
        if tag == "blockquote" and not attributes:
            element = etree.SubElement(parent, f"{{{_TEI}}}quote")
            element.set("type", "block")
            return element, "blockquote"
        if tag == "scripref":
            names = [name for name, _value in attributes]
            values = dict(attributes)
            if len(names) != len(values) or set(values) - {"passage", "version"} or any(value is None for value in values.values()):
                return None
            element = etree.SubElement(parent, f"{{{_TEI}}}ref")
            element.set("type", "scripture")
            if values.get("passage") is not None:
                element.set("n", values["passage"] or "")
            if values.get("version") is not None:
                element.set("subtype", values["version"] or "")
            return element, "scripRef"
        return None

    @staticmethod
    def _source_name(tag: str) -> str:
        return "scripRef" if tag == "scripref" else tag

    def _open(self, tag: str, attributes: list[tuple[str, str | None]], raw: str, *, self_closing: bool) -> None:
        tag = tag.casefold()
        element = self._new_mapped_element(tag, attributes)
        if element is None:
            reason = "unmapped-element-start" if tag not in {"br", "i", "blockquote", "scripref"} else "unsupported-source-attributes"
            self._record_unmapped(raw, reason)
            if not self_closing and tag not in self._VOID_ELEMENTS:
                self.stack.append({"source_tag": tag, "source_name": self._source_name(tag), "element": None, "mapped": False})
            return
        node, source_name = element
        self.mapped_elements[source_name] += 1
        if tag not in self._VOID_ELEMENTS and not self_closing:
            self.stack.append({"source_tag": tag, "source_name": source_name, "element": node, "mapped": True})

    def _close(self, tag: str, raw: str) -> None:
        tag = tag.casefold()
        match = next((index for index in range(len(self.stack) - 1, -1, -1) if self.stack[index]["source_tag"] == tag), None)
        if match is None:
            self._record_unmapped(raw, "unmatched-closing-tag")
            return
        for frame in reversed(self.stack[match + 1 :]):
            self.structural_warnings.append({"slot": self.slot, "element": frame["source_name"], "reason": "implicitly-closed-before-matching-end"})
        frame = self.stack[match]
        del self.stack[match:]
        if not frame["mapped"]:
            self._record_unmapped(raw, "unmapped-element-end")

    def finish(self) -> None:
        if self.seen_gap_tokens != set(self.gap_tokens):
            missing = sorted(set(self.gap_tokens) - self.seen_gap_tokens)
            raise ValueError(f"Barnes slot {self.slot} has a gap range inside ThML markup or a reference: {missing!r}")
        for frame in reversed(self.stack):
            self.structural_warnings.append({"slot": self.slot, "element": frame["source_name"], "reason": "unclosed-at-slot-end"})
        self.stack.clear()

    def handle_data(self, data: str) -> None:
        cursor = 0
        while cursor < len(data):
            matches = [(data.find(marker, cursor), marker) for marker in self.gap_tokens]
            matches = [(position, marker) for position, marker in matches if position >= 0]
            if not matches:
                self._append_text(data[cursor:])
                return
            position, marker = min(matches)
            self._append_text(data[cursor:position])
            if marker in self.seen_gap_tokens:
                raise ValueError(f"Barnes slot {self.slot} repeated an internal gap marker")
            self.seen_gap_tokens.add(marker)
            source_range = self.gap_tokens[marker]
            gap = etree.SubElement(
                self._current_parent(),
                f"{{{_TEI}}}gap",
                reason="unrepresentable",
                extent=f"{source_range['bytes']} bytes",
                ana="#source-invalid-utf8" if source_range["cause"] == "invalid-utf8" else "#source-xml-1.0-forbidden-character",
            )
            gap.set(_XML_ID, f"barnes-slot-{self.slot:05d}-byte-{int(source_range['start']):08d}-{int(source_range['end']):08d}")
            gap.set("n", str(source_range["sha256"]))
            cursor = position + len(marker)

    def handle_entityref(self, name: str) -> None:
        self._append_text(unescape(f"&{name};"))

    def handle_charref(self, name: str) -> None:
        self._append_text(unescape(f"&#{name};"))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag, attrs, self.get_starttag_text() or f"<{tag}>", self_closing=False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag, attrs, self.get_starttag_text() or f"<{tag}/>", self_closing=True)

    def handle_endtag(self, tag: str) -> None:
        self._close(tag, self._raw_end_tag(tag))

    def handle_comment(self, data: str) -> None:
        self._record_unmapped(f"<!--{data}-->", "unmapped-comment")

    def handle_decl(self, decl: str) -> None:
        self._record_unmapped(f"<!{decl}>", "unmapped-declaration")

    def handle_pi(self, data: str) -> None:
        self._record_unmapped(f"<?{data}?>", "unmapped-processing-instruction")

    def unknown_decl(self, data: str) -> None:
        self._record_unmapped(f"<![{data}]>", "unmapped-declaration")


def _convert_thml(parent: etree._Element, source_text: str, slot: int, gap_tokens: Mapping[str, Mapping[str, object]] | None = None) -> dict[str, object]:
    parser = _ThmlToTei(parent, source_text, slot, gap_tokens)
    parser.feed(source_text)
    parser.close()
    parser.finish()
    return {
        "mapped_elements": dict(sorted(parser.mapped_elements.items())),
        "unmapped_markup": parser.unmapped_markup,
        "structural_warnings": parser.structural_warnings,
    }


def _acquisition_binding(source_manifest: SourceManifest) -> tuple[dict[str, object], str]:
    """Bind the source-derived candidate to the installed three-member acquisition."""
    root = source_manifest.repository_root
    acquisition = validate_acquisition(root / _ACQUISITION, root=root)
    primary = sorted((dict(name=item["name"], path=item["path"], bytes=item["bytes"], sha256=item["sha256"])
                      for item in source_manifest.record["authorities"] if item["role"] == "primary-source"),
                     key=lambda item: (item["path"], item["name"]))
    retained = acquisition["retained_files"]
    if (len(primary) != 3 or len(retained) != 3
            or acquisition["source_kind"] != "retained-member-set"
            or acquisition["acquisition_id"] != "barnes-sword-v1.1"
            or acquisition["edition_id"] != "crosswire-sword-v1.1"
            or [(item["path"], item["bytes"], item["sha256"]) for item in primary]
               != [(item["path"], item["bytes"], item["sha256"]) for item in retained]):
        raise ValueError("Barnes acquisition does not bind the three primary SWORD members")
    source_set_sha = _sha(_canonical({"contract": "ocd-source-member-set-v1", "members": primary}))
    return acquisition, source_set_sha


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    if (source_manifest.record.get("ticket_id"), source_manifest.record.get("work_id"), source_manifest.record.get("source_id")) != ("37c-066", "barnes-nt-notes", "barnes-crosswire-sword-v1.1"):
        raise ValueError("Barnes source manifest identity mismatch")
    acquisition, source_set_sha = _acquisition_binding(source_manifest)
    rows, census = _carriers(source_manifest)
    positions, position_scheme, position_counts, position_digest = _bible_positions(source_manifest)
    if (
        len(rows) != 8246
        or len(census["invalid_utf8_slots"]) != 60
        or len(census["xml_incompatible_slots"]) != 76
        or census["unrepresentable_byte_counts"] != {"invalid_utf8": 68, "xml_1_0_forbidden": 98}
        or census["unrepresentable_byte_count"] != 166
    ):
        raise ValueError("Barnes retained-source census drifted")
    if len(positions) != len(rows):
        raise ValueError("Barnes Bible-position sequence does not match retained slot count")
    root = etree.Element(f"{{{_TEI}}}TEI", nsmap={None: _TEI})
    root.set(_XML_ID, "barnes-sword-nt-candidate")
    header = etree.SubElement(root, f"{{{_TEI}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{_TEI}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{_TEI}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{_TEI}}}title").text = "Notes on the New Testament"
    etree.SubElement(title_stmt, f"{{{_TEI}}}author").text = "Albert Barnes"
    pub = etree.SubElement(file_desc, f"{{{_TEI}}}publicationStmt")
    etree.SubElement(pub, f"{{{_TEI}}}p").text = "Nonaccepted technical candidate; rights and publication not assessed."
    source_desc = etree.SubElement(file_desc, f"{{{_TEI}}}sourceDesc")
    bibl = etree.SubElement(source_desc, f"{{{_TEI}}}bibl")
    etree.SubElement(bibl, f"{{{_TEI}}}title").text = "Barnes SWORD zCom New Testament module"
    etree.SubElement(bibl, f"{{{_TEI}}}idno", type="sha256").text = acquisition["source_sha256"]
    etree.SubElement(bibl, f"{{{_TEI}}}idno", type="source-member-set-sha256").text = source_set_sha
    etree.SubElement(bibl, f"{{{_TEI}}}idno", type="acquisition-package-sha256").text = census["archive_sha256"]
    etree.SubElement(bibl, f"{{{_TEI}}}note").text = "The source is the three extracted SWORD parser members. Barnes.zip is their acquisition package, not the textual source. Slot order is preserved; print-volume boundaries and an original textual edition are not inferred."
    etree.SubElement(etree.SubElement(header, f"{{{_TEI}}}encodingDesc"), f"{{{_TEI}}}p").text = "Valid UTF-8 spans containing only XML 1.0 characters are preserved as readable ThML-derived TEI. Only exact malformed UTF-8 byte sequences and XML 1.0-forbidden characters are represented by explicit gaps; the ticket-local accountability member retains their byte ranges and exact source bytes. No replacement decoding or guessed character set is used."
    text = etree.SubElement(root, f"{{{_TEI}}}text")
    body = etree.SubElement(text, f"{{{_TEI}}}body")
    div = etree.SubElement(body, f"{{{_TEI}}}div", type="sword-module", subtype="new-testament")
    thml_counts = {"blockquote": 0, "br": 0, "i": 0, "scripRef": 0}
    unmapped_markup: list[dict[str, object]] = []
    structural_warnings: list[dict[str, object]] = []
    byte_ranges_by_slot: dict[int, list[dict[str, object]]] = {}
    for (slot, data), position in zip(rows, positions, strict=True):
        node = etree.SubElement(div, f"{{{_TEI}}}ab", n=str(slot), type="sword-slot")
        node.set(_XML_ID, f"barnes-slot-{slot:05d}")
        node.set("subtype", f"{position['kind']}:{position['key']}")
        if not data:
            node.set("ana", "#empty-source-slot")
        else:
            ranges = _byte_ranges(data)
            gap_ranges = [item for item in ranges if item["state"] == "unrepresentable"]
            if gap_ranges:
                node.set("ana", "#contains-unrepresentable-source-byte-ranges")
                byte_ranges_by_slot[slot] = ranges
            source_text, gap_tokens = _source_with_gap_markers(data, ranges, slot)
            mapping = _convert_thml(node, source_text, slot, gap_tokens)
            for name, count in mapping["mapped_elements"].items():
                thml_counts[name] += count
            unmapped_markup.extend(mapping["unmapped_markup"])
            structural_warnings.extend(mapping["structural_warnings"])
    account = {
        "contract": "ocd-barnes-source-accountability-v2",
        "work_id": "barnes-nt-notes",
        "source_id": source_manifest.record["source_id"],
        **census,
        "accounting": "Every BZV slot in source order is represented once and mapped to its SWORD KJV position using only the retained module configuration and the bound KJV canon table. Position keys are not inferred from carrier text, generated Bible JSON, or neighboring payloads. Valid UTF-8/XML 1.0-safe spans preserve source order and source-native ThML i, br, scripRef, and blockquote semantics; only malformed UTF-8 byte runs and XML 1.0-forbidden characters are TEI gaps. For each affected slot, byte_ranges partition the exact carrier with zero-based half-open offsets; ordered range hex concatenates to the retained carrier and every range carries its SHA-256. Empty slots are explicit; no replacement decoding or guessed character set is used.",
        "byte_range_contract": {"scheme": "ocd-barnes-source-byte-span-v1", "offset_unit": "byte", "offset_origin": 0, "end_exclusive": True, "scope": "affected-carriers-only"},
        "bible_position_mapping": {"scheme": position_scheme, "versification": "KJV", "counts": position_counts, "position_stream_sha256": position_digest},
        "thml_mapping": {"mapped_elements": thml_counts, "unmapped_markup": unmapped_markup, "structural_warnings": structural_warnings},
        "slots": [
            {
                "slot": slot,
                "bible_position": position,
                "bytes": len(data),
                "sha256": _sha(data),
                "state": "empty" if not data else "partial" if slot in byte_ranges_by_slot else "utf8",
                "byte_ranges": [{"slot": slot, **item} for item in byte_ranges_by_slot.get(slot, [])],
            }
            for (slot, data), position in zip(rows, positions, strict=True)
        ],
    }
    provenance = {"contract": "ocd-barnes-candidate-provenance-v1", "status": "nonaccepted", "work_id": "barnes-nt-notes", "ticket_id": "LIB-012", "source_id": source_manifest.record["source_id"], "source_manifest_sha256": source_manifest.sha256, "acquisition_id": acquisition["acquisition_id"], "edition_id": acquisition["edition_id"], "acquisition_source_sha256": acquisition["source_sha256"], "source_member_set_sha256": source_set_sha, "acquisition_package_sha256": census["archive_sha256"], "acceptance_status": "not-accepted", "rights_status": "not-assessed", "release_status": "not-selected", "publication_status": "not-authorized"}
    unresolved = [
        {"id": "barnes-unrepresentable-carriers", "status": "open", "kind": "source-bytes", "detail": "Across 136 affected retained carriers, 68 malformed UTF-8 bytes and 98 XML 1.0-forbidden bytes remain unrepresentable and are shown as exact TEI gaps. Every affected carrier's safe UTF-8/XML 1.0 spans remain readable; all source byte ranges, offsets, hex values, and hashes are preserved in source-accountability.json. The offending bytes remain unresolved; no replacement decoding or guessed character set is used."},
        {"id": "barnes-edition-and-parts", "status": "unresolved", "kind": "identity", "detail": "The retained SWORD module alone does not settle print edition, original textual form, or volume boundaries."},
        {"id": "barnes-thml-unclosed-elements", "status": "open", "kind": "source-structure", "detail": "Four source blockquote start tags in three carriers have no closing tag within their BZV slot. TEI quotes end at the carrier boundary; each source boundary is listed in source-accountability.json."},
        {"id": "barnes-human-acceptance-rights-publication", "status": "unresolved", "kind": "governance", "detail": "Human acceptance, rights review, release selection, and publication authorization are outside this technical route."},
    ]
    return {"content.tei.xml": etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False), "source-accountability.json": _canonical(account), "provenance.json": _canonical(provenance), "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved), "README.source.md": source_manifest.authority_path("source-readme").read_bytes()}


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
