"""Independent slot-by-slot verifier for the retained Barnes zCom bytes."""

from __future__ import annotations

import configparser
import hashlib
import json
import platform
from collections import Counter
from html import unescape
from pathlib import Path
import re
import struct
import sys
from typing import Mapping
import zlib

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.library.acquisitions import validate_acquisition

ORACLE_ID = "ocd-barnes-independent-zcom-slot-oracle"
ORACLE_VERSION = "3"
_TEI = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_ACQUISITION = "library/works/barnes-nt-notes/forms/barnes-english/editions/crosswire-sword-v1.1/acquisitions/barnes-sword-v1.1.json"
_FILES = {
    "nt.czv": (82460, "edd2d46416db52595af44811a49940527bba208bd6b73b7c30f480c21d63edae"),
    "nt.czz": (6018995, "d26ada7eba82d4c0c24c18ad8d8a520c1dfd5761e2bdc8161c6888bc665ea40a"),
    "nt.czs": (3120, "a39f80ec47d108a43fda634c1234fc03827f32eac1636d614c01b424dfcf6302"),
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(data: object) -> bytes:
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _xml10_character(codepoint: int) -> bool:
    return (
        codepoint in {0x9, 0xA, 0xD}
        or 0x20 <= codepoint <= 0xD7FF
        or 0xE000 <= codepoint <= 0xFFFD
        or 0x10000 <= codepoint <= 0x10FFFF
    )


def _append_source_range(ranges: list[dict[str, object]], data: bytes, start: int, end: int, state: str, cause: str | None = None) -> None:
    previous = ranges[-1] if ranges else None
    if previous is not None and previous["end"] == start and previous["state"] == state and previous.get("cause") == cause:
        previous["end"] = end
        return
    item: dict[str, object] = {"start": start, "end": end, "state": state}
    if state == "unrepresentable":
        item["cause"] = cause
    ranges.append(item)


def _source_byte_ranges(data: bytes) -> list[dict[str, object]]:
    """Independently partition retained bytes using strict-decoder error offsets."""
    ranges: list[dict[str, object]] = []

    def append_decoded(base: int, raw: bytes) -> None:
        text = raw.decode("utf-8", errors="strict")
        cursor = base
        for character in text:
            encoded = character.encode("utf-8")
            cause = None if _xml10_character(ord(character)) else "xml-1.0-forbidden-character"
            _append_source_range(ranges, data, cursor, cursor + len(encoded), "represented" if cause is None else "unrepresentable", cause)
            cursor += len(encoded)

    cursor = 0
    while cursor < len(data):
        suffix = data[cursor:]
        try:
            suffix.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            append_decoded(cursor, suffix[: error.start])
            start = cursor + error.start
            end = cursor + max(error.end, error.start + 1)
            _append_source_range(ranges, data, start, end, "unrepresentable", "invalid-utf8")
            cursor = end
        else:
            append_decoded(cursor, suffix)
            break
    for item in ranges:
        raw = data[int(item["start"]) : int(item["end"])]
        item.update({"bytes": len(raw), "sha256": _sha(raw), "hex": raw.hex()})
        if item["state"] == "unrepresentable":
            item["reason"] = "unrepresentable"
    return ranges


def _source_with_gap_tokens(data: bytes, ranges: list[dict[str, object]], slot: int) -> tuple[str, dict[str, dict[str, object]]]:
    pieces: list[str] = []
    tokens: dict[str, dict[str, object]] = {}
    safe_text = "".join(data[int(item["start"]) : int(item["end"])].decode("utf-8", errors="strict") for item in ranges if item["state"] == "represented")
    token_index = 0
    for item in ranges:
        if item["state"] == "represented":
            pieces.append(data[int(item["start"]) : int(item["end"])].decode("utf-8", errors="strict"))
            continue
        token = f"\uE000OCD_BARNES_GAP_{slot:05d}_{token_index:04d}\uE001"
        token_index += 1
        while token in safe_text or token in tokens:
            token = f"\uE000OCD_BARNES_GAP_{slot:05d}_{token_index:04d}\uE001"
            token_index += 1
        tokens[token] = {"slot": slot, **item}
        pieces.append(token)
    return "".join(pieces), tokens


def _append_source_text_event(events: list[tuple[object, ...]], text: str, gap_tokens: Mapping[str, Mapping[str, object]]) -> None:
    cursor = 0
    while cursor < len(text):
        matches = [(text.find(token, cursor), token) for token in gap_tokens]
        matches = [(position, token) for position, token in matches if position >= 0]
        if not matches:
            _append_text_event(events, unescape(text[cursor:]))
            return
        position, token = min(matches)
        before = text[cursor:position]
        ampersand = before.rfind("&")
        if ampersand > before.rfind(";"):
            possible_entity = before[ampersand + 1 :] + text[position + len(token) :]
            terminator = possible_entity.find(";")
            if terminator >= 0 and not any(char.isspace() or char in "<>" for char in possible_entity[:terminator]):
                raise ValueError("Barnes source gap overlaps a character reference")
        _append_text_event(events, unescape(before))
        source_range = gap_tokens[token]
        events.append((
            "gap",
            int(source_range["slot"]),
            int(source_range["start"]),
            int(source_range["end"]),
            str(source_range["cause"]),
            str(source_range["reason"]),
            int(source_range["bytes"]),
            str(source_range["sha256"]),
        ))
        cursor = position + len(token)


_SOURCE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9:._-]*")
_ATTRIBUTE_NAME = re.compile(r"[A-Za-z_:][A-Za-z0-9:._-]*")
_VOID_ELEMENTS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})
_MAPPED_COUNTS = {"blockquote": 0, "br": 0, "i": 0, "scripRef": 0}


def _append_text_event(events: list[tuple[object, ...]], text: str) -> None:
    if not text:
        return
    if events and events[-1][0] == "text":
        events[-1] = ("text", str(events[-1][1]) + text)
    else:
        events.append(("text", text))


def _tag_token(text: str, start: int) -> dict[str, object] | None:
    """Tokenize one source tag without using the producer's HTML parser."""
    if text.startswith("<!--", start):
        end = text.find("-->", start + 4)
        stop = len(text) if end < 0 else end + 3
        return {"raw": text[start:stop], "end": stop, "literal_reason": "unmapped-comment"}
    if text.startswith("<?", start):
        end = text.find("?>", start + 2)
        stop = len(text) if end < 0 else end + 2
        return {"raw": text[start:stop], "end": stop, "literal_reason": "unmapped-processing-instruction"}
    if text.startswith("<!", start):
        quote: str | None = None
        stop = len(text)
        for index in range(start + 2, len(text)):
            char = text[index]
            if quote:
                if char == quote:
                    quote = None
            elif char in "\"'":
                quote = char
            elif char == ">":
                stop = index + 1
                break
        return {"raw": text[start:stop], "end": stop, "literal_reason": "unmapped-declaration"}

    quote = None
    stop = None
    for index in range(start + 1, len(text)):
        char = text[index]
        if quote:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == ">":
            stop = index + 1
            break
    if stop is None:
        return None
    raw = text[start:stop]
    body = raw[1:-1].strip()
    if not body:
        return None
    closing = body.startswith("/")
    if closing:
        body = body[1:].lstrip()
    name_match = _SOURCE_NAME.match(body)
    if name_match is None:
        return None
    name = name_match.group(0).casefold()
    rest = body[name_match.end() :]
    self_closing = not closing and rest.rstrip().endswith("/")
    if self_closing:
        rest = rest.rstrip()[:-1]
    return {"raw": raw, "end": stop, "name": name, "closing": closing, "self_closing": self_closing, "attributes_text": rest}


def _source_attributes(raw: str) -> dict[str, str] | None:
    """Parse source attributes conservatively; reject duplicates and unknown syntax."""
    attributes: dict[str, str] = {}
    position = 0
    while position < len(raw):
        while position < len(raw) and raw[position].isspace():
            position += 1
        if position == len(raw):
            break
        name_match = _ATTRIBUTE_NAME.match(raw, position)
        if name_match is None:
            return None
        name = name_match.group(0).casefold()
        position = name_match.end()
        while position < len(raw) and raw[position].isspace():
            position += 1
        if position >= len(raw) or raw[position] != "=":
            return None
        position += 1
        while position < len(raw) and raw[position].isspace():
            position += 1
        if position >= len(raw):
            return None
        if raw[position] in "\"'":
            delimiter = raw[position]
            end = raw.find(delimiter, position + 1)
            if end < 0:
                return None
            value = raw[position + 1 : end]
            position = end + 1
        else:
            end = position
            while end < len(raw) and not raw[end].isspace() and raw[end] != "/":
                end += 1
            value = raw[position:end]
            if not value:
                return None
            position = end
        if name in attributes:
            return None
        attributes[name] = unescape(value)
    return attributes


def _mapped_source_event(name: str, attributes: dict[str, str]) -> tuple[str, tuple[object, ...]] | None:
    if name == "br" and not attributes:
        return "br", ("lb",)
    if name == "i" and not attributes:
        return "i", ("start", "hi", (("rend", "italic"),))
    if name == "blockquote" and not attributes:
        return "blockquote", ("start", "quote", (("type", "block"),))
    if name == "scripref" and not (set(attributes) - {"passage", "version"}):
        tei_attributes = {"type": "scripture"}
        if "passage" in attributes:
            tei_attributes["n"] = attributes["passage"]
        if "version" in attributes:
            tei_attributes["subtype"] = attributes["version"]
        return "scripRef", ("start", "ref", tuple(sorted(tei_attributes.items())))
    return None


def _source_thml_events(source_text: str, slot: int, gap_tokens: Mapping[str, Mapping[str, object]] | None = None) -> tuple[list[tuple[object, ...]], dict[str, int], list[dict[str, object]], list[dict[str, object]]]:
    """Independently compare carrier text and markup with the candidate TEI events."""
    gap_tokens = dict(gap_tokens or {})
    events: list[tuple[object, ...]] = []
    mapped_counts = dict(_MAPPED_COUNTS)
    unmapped_markup: list[dict[str, object]] = []
    structural_warnings: list[dict[str, object]] = []
    stack: list[dict[str, object]] = []

    def add_unmapped(token: str, reason: str) -> None:
        _append_text_event(events, token)
        unmapped_markup.append({"slot": slot, "token": token, "reason": reason})

    def close_frame(frame: dict[str, object], reason: str) -> None:
        structural_warnings.append({"slot": slot, "element": frame["source_name"], "reason": reason})
        if frame["mapped_event"] is not None:
            event = frame["mapped_event"]
            events.append(("end", event[1]))

    cursor = 0
    while cursor < len(source_text):
        start = source_text.find("<", cursor)
        if start < 0:
            _append_source_text_event(events, source_text[cursor:], gap_tokens)
            break
        _append_source_text_event(events, source_text[cursor:start], gap_tokens)
        token = _tag_token(source_text, start)
        if token is None:
            _append_text_event(events, "<")
            cursor = start + 1
            continue
        raw = str(token["raw"])
        if any(marker in raw for marker in gap_tokens):
            raise ValueError("Barnes source gap overlaps ThML markup")
        cursor = int(token["end"])
        literal_reason = token.get("literal_reason")
        if literal_reason is not None:
            add_unmapped(raw, str(literal_reason))
            continue
        name = str(token["name"])
        closing = bool(token["closing"])
        self_closing = bool(token["self_closing"])
        if closing:
            match = next((index for index in range(len(stack) - 1, -1, -1) if stack[index]["source_tag"] == name), None)
            if match is None:
                add_unmapped(raw, "unmatched-closing-tag")
                continue
            for frame in reversed(stack[match + 1 :]):
                close_frame(frame, "implicitly-closed-before-matching-end")
            frame = stack[match]
            del stack[match:]
            if frame["mapped_event"] is None:
                add_unmapped(raw, "unmapped-element-end")
            else:
                events.append(("end", frame["mapped_event"][1]))
            continue

        attributes = _source_attributes(str(token["attributes_text"]))
        mapped = None if attributes is None else _mapped_source_event(name, attributes)
        if mapped is None:
            reason = "unmapped-element-start" if name not in {"br", "i", "blockquote", "scripref"} else "unsupported-source-attributes"
            add_unmapped(raw, reason)
            if not self_closing and name not in _VOID_ELEMENTS:
                stack.append({"source_tag": name, "source_name": "scripRef" if name == "scripref" else name, "mapped_event": None})
            continue
        source_name, start_event = mapped
        mapped_counts[source_name] += 1
        events.append(start_event)
        if name in _VOID_ELEMENTS:
            continue
        if self_closing:
            events.append(("end", start_event[1]))
        else:
            stack.append({"source_tag": name, "source_name": source_name, "mapped_event": start_event})

    for frame in reversed(stack):
        if frame["mapped_event"] is None:
            structural_warnings.append({"slot": slot, "element": frame["source_name"], "reason": "unclosed-at-slot-end"})
        else:
            close_frame(frame, "unclosed-at-slot-end")
    return events, mapped_counts, unmapped_markup, structural_warnings


def _thml_mapping(slots: list[bytes], ranges_by_slot: list[list[dict[str, object]]], states: list[str]) -> dict[str, object]:
    mapped_counts = dict(_MAPPED_COUNTS)
    unmapped_markup: list[dict[str, object]] = []
    structural_warnings: list[dict[str, object]] = []
    for slot, (value, ranges, state) in enumerate(zip(slots, ranges_by_slot, states, strict=True)):
        if state == "empty":
            continue
        source_text, markers = _source_with_gap_tokens(value, ranges, slot)
        _events, counts, unmapped, warnings = _source_thml_events(source_text, slot, markers)
        for name, count in counts.items():
            mapped_counts[name] += count
        unmapped_markup.extend(unmapped)
        structural_warnings.extend(warnings)
    return {"mapped_elements": mapped_counts, "unmapped_markup": unmapped_markup, "structural_warnings": structural_warnings}


def _tei_events(carrier: etree._Element) -> list[tuple[object, ...]]:
    events: list[tuple[object, ...]] = []
    carrier_slot = int(carrier.get("n", "-1"))

    def walk(parent: etree._Element) -> None:
        _append_text_event(events, parent.text or "")
        for child in parent:
            name = etree.QName(child).localname
            attributes = dict(child.attrib)
            if name == "gap":
                gap_id = attributes.get(_XML_ID, "")
                match = re.fullmatch(r"barnes-slot-(\d{5})-byte-(\d{8})-(\d{8})", gap_id)
                if match is None:
                    raise ValueError("Barnes TEI gap lacks its source slot and byte offsets")
                slot, start, end = map(int, match.groups())
                cause = {"#source-invalid-utf8": "invalid-utf8", "#source-xml-1.0-forbidden-character": "xml-1.0-forbidden-character"}.get(attributes.get("ana", ""), "")
                range_sha256 = attributes.get("n", "")
                expected_attributes = {
                    _XML_ID: gap_id,
                    "reason": "unrepresentable",
                    "extent": f"{end - start} bytes",
                    "ana": "#source-invalid-utf8" if cause == "invalid-utf8" else "#source-xml-1.0-forbidden-character",
                    "n": range_sha256,
                }
                if slot != carrier_slot or end <= start or cause not in {"invalid-utf8", "xml-1.0-forbidden-character"}:
                    raise ValueError("Barnes TEI gap identifies an invalid source byte range")
                if attributes != expected_attributes or len(child) or child.text:
                    raise ValueError("Barnes TEI gap differs from the exact source byte range contract")
                events.append(("gap", slot, start, end, cause, "unrepresentable", end - start, range_sha256))
            elif name == "lb":
                if attributes or len(child) or child.text:
                    raise ValueError("Barnes TEI line-break mapping carries unsupported content or attributes")
                events.append(("lb",))
            elif name == "hi":
                if attributes != {"rend": "italic"}:
                    raise ValueError("Barnes TEI emphasis differs from source ThML i semantics")
                events.append(("start", "hi", (("rend", "italic"),)))
                walk(child)
                events.append(("end", "hi"))
            elif name == "ref":
                if attributes.get("type") != "scripture" or set(attributes) - {"type", "n", "subtype"}:
                    raise ValueError("Barnes TEI reference differs from source ThML scripRef semantics")
                events.append(("start", "ref", tuple(sorted(attributes.items()))))
                walk(child)
                events.append(("end", "ref"))
            elif name == "quote":
                if attributes != {"type": "block"}:
                    raise ValueError("Barnes TEI quotation differs from source ThML blockquote semantics")
                events.append(("start", "quote", (("type", "block"),)))
                walk(child)
                events.append(("end", "quote"))
            else:
                raise ValueError(f"Unexpected TEI element in Barnes source carrier: {name}")
            _append_text_event(events, child.tail or "")

    walk(carrier)
    return events


def _closure(root: Path) -> str:
    # Shared reconstruction-contract code is deliberately not copied into this
    # work binding: other authorized tickets may update it concurrently. The
    # bound closure is the ticket-local oracle module; the live shared contract
    # remains separately exercised by candidate validation and runtime checks.
    path = Path(__file__).resolve(strict=True)
    records = [{"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())}]
    return _sha(_json(records))


def _source_slots(manifest: SourceManifest) -> list[bytes]:
    root = manifest.repository_root / "raw/sword_modules/Barnes/modules/comments/zcom/barnes"
    values = {}
    for name, (size, digest) in _FILES.items():
        data = (root / name).read_bytes()
        if len(data) != size or _sha(data) != digest:
            raise ValueError(f"Barnes retained {name} authority mismatch")
        values[name] = data
    index, packed, blocks = values["nt.czv"], values["nt.czz"], values["nt.czs"]
    if len(index) % 10 or len(blocks) % 12:
        raise ValueError("Barnes index alignment mismatch")
    cache: dict[int, bytes] = {}
    result = []
    for offset in range(0, len(index), 10):
        block, start, length = struct.unpack_from("<IIH", index, offset)
        if not length:
            result.append(b"")
            continue
        if block not in cache:
            p = block * 12
            if p + 12 > len(blocks):
                raise ValueError("Barnes block pointer exceeds BZS")
            pos, size, expected = struct.unpack_from("<III", blocks, p)
            if not size or pos + size > len(packed):
                raise ValueError("Barnes compressed block range invalid")
            cache[block] = zlib.decompress(packed[pos : pos + size])
            if len(cache[block]) != expected:
                raise ValueError("Barnes decompressed block length mismatch")
        value = cache[block]
        if start + length > len(value):
            raise ValueError("Barnes carrier range exceeds decompressed block")
        result.append(value[start : start + length])
    return result


def _bible_positions(manifest: SourceManifest) -> tuple[list[dict[str, object]], str, dict[str, int], str]:
    """Independently enumerate the SWORD KJV heading, book, chapter, and verse keys."""
    config = configparser.ConfigParser(interpolation=None)
    config.read_string(manifest.authority_path("retained-module-config").read_text(encoding="utf-8"))
    if "Barnes" not in config:
        raise ValueError("Barnes module configuration has no [Barnes] section")
    version = config["Barnes"].get("Versification", "KJV").strip().upper()
    if version != "KJV":
        raise ValueError(f"Unsupported Barnes SWORD versification for this mapping: {version!r}")

    profile = json.loads(manifest.authority_path("reconstruction-profile").read_bytes())
    spec = profile.get("mapping", {}).get("bible_positions", {})
    scheme = spec.get("scheme")
    if scheme != "ocd-barnes-sword-kjv-position-v1" or spec.get("versification") != version:
        raise ValueError("Bound Barnes position profile does not agree with the retained SWORD versification")

    positions: list[dict[str, object]] = []
    positions.append({"kind": "module-heading", "key": "module-heading"})
    positions.append({"kind": "testament-heading", "key": "testament.2", "testament": 2})
    books = spec.get("books")
    if not isinstance(books, list) or len(books) != 27:
        raise ValueError("Barnes KJV position profile must contain the 27 New Testament books")
    seen: set[str] = set()
    for item in books:
        book_code = item.get("osis")
        lengths = item.get("chapter_verse_counts")
        if not isinstance(book_code, str) or book_code in seen or not isinstance(lengths, list) or not lengths:
            raise ValueError("Barnes KJV position profile has an invalid or repeated book")
        seen.add(book_code)
        positions.append({"kind": "book-heading", "key": book_code, "testament": 2, "osis_book": book_code})
        chapter = 1
        for verse_count in lengths:
            if not isinstance(verse_count, int) or isinstance(verse_count, bool) or verse_count < 1:
                raise ValueError(f"Barnes KJV position profile has an invalid chapter in {book_code}")
            positions.append({"kind": "chapter-heading", "key": f"{book_code}.{chapter}", "testament": 2, "osis_book": book_code, "chapter": chapter})
            verse = 1
            while verse <= verse_count:
                positions.append({"kind": "verse", "key": f"{book_code}.{chapter}.{verse}", "testament": 2, "osis_book": book_code, "chapter": chapter, "verse": verse})
                verse += 1
            chapter += 1

    counts = dict(sorted(Counter(str(position["kind"]) for position in positions).items()))
    if counts != spec.get("expected_counts") or len(positions) != profile.get("source_scope", {}).get("expected_slots"):
        raise ValueError("Independent Barnes KJV position sequence does not match the bound profile counts")
    key_lines = []
    for index, position in enumerate(positions):
        key_lines.append(str(index) + "\t" + str(position["kind"]) + "\t" + str(position["key"]))
    position_digest = _sha("\n".join(key_lines).encode("utf-8"))
    if position_digest != spec.get("position_stream_sha256"):
        raise ValueError("Independent Barnes KJV position digest differs from the bound profile")
    return positions, scheme, counts, position_digest


def _acquisition_binding(source_manifest: SourceManifest) -> tuple[dict[str, object], str]:
    """Independently compare acquired source members with manifest authorities."""
    root = source_manifest.repository_root
    acquisition = validate_acquisition(root / _ACQUISITION, root=root)
    primary = sorted(({"name": item["name"], "path": item["path"], "bytes": item["bytes"], "sha256": item["sha256"]}
                      for item in source_manifest.record["authorities"] if item["role"] == "primary-source"),
                     key=lambda item: (item["path"], item["name"]))
    members = acquisition["retained_files"]
    if (len(primary) != 3 or len(members) != 3
            or acquisition.get("source_kind") != "retained-member-set"
            or acquisition.get("acquisition_id") != "barnes-sword-v1.1"
            or acquisition.get("edition_id") != "crosswire-sword-v1.1"
            or [(item["path"], item["bytes"], item["sha256"]) for item in primary]
               != [(item["path"], item["bytes"], item["sha256"]) for item in members]):
        raise ValueError("Barnes acquired source members differ from candidate authorities")
    source_set_sha = _sha(_json({"contract": "ocd-source-member-set-v1", "members": primary}))
    return acquisition, source_set_sha


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    record = source_manifest.record
    if (record.get("ticket_id"), record.get("work_id"), record.get("source_id")) != ("37c-066", "barnes-nt-notes", "barnes-crosswire-sword-v1.1"):
        raise ValueError("Barnes manifest identity mismatch")
    acquisition, source_set_sha = _acquisition_binding(source_manifest)
    slots = _source_slots(source_manifest)
    positions, position_scheme, position_counts, position_digest = _bible_positions(source_manifest)
    if len(positions) != len(slots):
        raise ValueError("Barnes SWORD position sequence does not cover the retained BZV slots")
    digests = [_sha(item) for item in slots]
    ranges_by_slot = [_source_byte_ranges(value) if value else [] for value in slots]
    states = ["empty" if not item else "partial" if any(span["state"] == "unrepresentable" for span in ranges) else "utf8" for item, ranges in zip(slots, ranges_by_slot, strict=True)]
    invalid_utf8_slots = [i for i, ranges in enumerate(ranges_by_slot) if any(span.get("cause") == "invalid-utf8" for span in ranges)]
    xml_incompatible_slots = [
        i
        for i, ranges in enumerate(ranges_by_slot)
        if i not in invalid_utf8_slots and any(span.get("cause") == "xml-1.0-forbidden-character" for span in ranges)
    ]
    unrepresentable_byte_counts = {
        "invalid_utf8": sum(int(span["bytes"]) for ranges in ranges_by_slot for span in ranges if span.get("cause") == "invalid-utf8"),
        "xml_1_0_forbidden": sum(int(span["bytes"]) for ranges in ranges_by_slot for span in ranges if span.get("cause") == "xml-1.0-forbidden-character"),
    }
    unrepresentable_range_count = sum(1 for ranges in ranges_by_slot for span in ranges if span["state"] == "unrepresentable")
    if len(invalid_utf8_slots) != 60 or len(xml_incompatible_slots) != 76 or unrepresentable_byte_counts != {"invalid_utf8": 68, "xml_1_0_forbidden": 98}:
        raise ValueError("Independent Barnes source-byte classification differs from the retained ticket census")
    stream = _sha(b"".join(struct.pack("<II", i, len(value)) + value for i, value in enumerate(slots)))
    expected = {
        "contract": "ocd-barnes-source-accountability-v2",
        "work_id": "barnes-nt-notes",
        "source_id": record["source_id"],
        "archive_sha256": "9e8edc0333875c214124371b3862df118ad3a76ade7753cb2faeed3484615baf",
        "member_hashes": {name: digest for name, (_size, digest) in _FILES.items()},
        "slot_count": len(slots),
        "nonempty_slots": sum(bool(v) for v in slots),
        "empty_slots": sum(not v for v in slots),
        "payload_bytes": sum(map(len, slots)),
        "invalid_utf8_slots": invalid_utf8_slots,
        "xml_incompatible_slots": xml_incompatible_slots,
        "unrepresentable_byte_counts": unrepresentable_byte_counts,
        "unrepresentable_byte_count": sum(unrepresentable_byte_counts.values()),
        "unrepresentable_range_count": unrepresentable_range_count,
        "carrier_stream_sha256": stream,
        "accounting": "Every BZV slot in source order is represented once and mapped to its SWORD KJV position using only the retained module configuration and the bound KJV canon table. Position keys are not inferred from carrier text, generated Bible JSON, or neighboring payloads. Valid UTF-8/XML 1.0-safe spans preserve source order and source-native ThML i, br, scripRef, and blockquote semantics; only malformed UTF-8 byte runs and XML 1.0-forbidden characters are TEI gaps. For each affected slot, byte_ranges partition the exact carrier with zero-based half-open offsets; ordered range hex concatenates to the retained carrier and every range carries its SHA-256. Empty slots are explicit; no replacement decoding or guessed character set is used.",
        "byte_range_contract": {"scheme": "ocd-barnes-source-byte-span-v1", "offset_unit": "byte", "offset_origin": 0, "end_exclusive": True, "scope": "affected-carriers-only"},
        "bible_position_mapping": {"scheme": position_scheme, "versification": "KJV", "counts": position_counts, "position_stream_sha256": position_digest},
        "thml_mapping": _thml_mapping(slots, ranges_by_slot, states),
        "slots": [
            {
                "slot": i,
                "bible_position": positions[i],
                "bytes": len(value),
                "sha256": digests[i],
                "state": states[i],
                "byte_ranges": [{"slot": i, **span} for span in ranges_by_slot[i]] if states[i] == "partial" else [],
            }
            for i, value in enumerate(slots)
        ],
    }
    account_bytes = candidate.member_bytes("source-accountability.json")
    if account_bytes != _json(expected):
        raise ValueError("Barnes accountability differs from independent carrier traversal")
    schema = json.loads(source_manifest.authority_path("source-accountability-schema").read_bytes())
    errors = list(Draft202012Validator(schema).iter_errors(expected))
    if errors:
        raise ValueError(f"Barnes accountability schema: {errors[0].message}")
    tree = etree.fromstring(candidate.member_bytes("content.tei.xml"), etree.XMLParser(resolve_entities=False, no_network=True))
    if not etree.XMLSchema(etree.parse(str(source_manifest.authority_path("tei-p5-xsd")))).validate(tree):
        raise ValueError("Barnes candidate fails bound TEI P5 schema")
    source_ids = tree.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl/t:idno", namespaces={"t": _TEI})
    actual_ids = [(item.get("type"), item.text) for item in source_ids]
    expected_ids = [("sha256", acquisition["source_sha256"]),
                    ("source-member-set-sha256", source_set_sha),
                    ("acquisition-package-sha256", expected["archive_sha256"])]
    if actual_ids != expected_ids:
        raise ValueError("Barnes TEI source identity does not distinguish extracted members from package")
    nodes = tree.xpath("/t:TEI/t:text/t:body/t:div/t:ab", namespaces={"t": _TEI})
    if len(nodes) != len(slots) or [int(node.get("n")) for node in nodes] != list(range(len(slots))):
        raise ValueError("Barnes TEI carrier positions are incomplete or reordered")
    for i, (node, value, state, ranges) in enumerate(zip(nodes, slots, states, ranges_by_slot, strict=True)):
        position = positions[i]
        if node.get("subtype") != f"{position['kind']}:{position['key']}":
            raise ValueError(f"Barnes TEI Bible position differs from the independent SWORD map at slot {i}")
        if state in {"utf8", "partial"}:
            source_text, markers = _source_with_gap_tokens(value, ranges, i)
            source_events, _counts, _unmapped, _warnings = _source_thml_events(source_text, i, markers)
            expected_ana = "#contains-unrepresentable-source-byte-ranges" if state == "partial" else None
            if node.get("ana") != expected_ana or source_events != _tei_events(node):
                raise ValueError(f"Barnes TEI source text or ThML semantics differ at slot {i}")
        elif state == "empty":
            if node.get("ana") != "#empty-source-slot" or node.text or len(node):
                raise ValueError(f"Barnes empty slot mismatch at {i}")
    unresolved = [json.loads(line) for line in candidate.member_bytes("unresolved.jsonl").splitlines()]
    if not unresolved or unresolved[0]["id"] != "barnes-unrepresentable-carriers":
        raise ValueError("Barnes source-byte limitation was hidden")
    if expected["thml_mapping"]["structural_warnings"] and not any(item.get("id") == "barnes-thml-unclosed-elements" and item.get("status") == "open" for item in unresolved):
        raise ValueError("Barnes unclosed source ThML elements were hidden")
    if candidate.member_bytes("README.source.md") != source_manifest.authority_path("source-readme").read_bytes():
        raise ValueError("Barnes source README mismatch")
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    if (provenance.get("source_manifest_sha256") != source_manifest.sha256
            or provenance.get("acquisition_id") != acquisition["acquisition_id"]
            or provenance.get("edition_id") != acquisition["edition_id"]
            or provenance.get("acquisition_source_sha256") != acquisition["source_sha256"]
            or provenance.get("source_member_set_sha256") != source_set_sha
            or provenance.get("acquisition_package_sha256") != expected["archive_sha256"]
            or provenance.get("status") != "nonaccepted"):
        raise ValueError("Barnes candidate provenance differs from the installed acquisition")
    impl = Path(__file__).read_bytes()
    validator = record["validator"]
    closure = _closure(source_manifest.repository_root)
    if validator["implementation_sha256"] != _sha(impl) or validator["import_closure_sha256"] != closure:
        raise ValueError("Barnes oracle code binding mismatch")
    profile = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy = source_manifest.authority_path("validation-policy").read_bytes()
    result: dict[str, object] = {"status": "pass", "oracle_id": ORACLE_ID, "oracle_version": ORACLE_VERSION, "implementation_sha256": _sha(impl), "import_closure_sha256": closure, "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})", "source_manifest_sha256": source_manifest.sha256, "candidate_sha256": candidate.sha256, "profile_sha256": _sha(profile), "package_schema_sha256": _sha(source_manifest.authority_path("candidate-package-schema").read_bytes()), "source_sha256": source_set_sha, "xsd_sha256": _sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()), "policy_sha256": _sha(policy), "findings": []}
    result["result_sha256"] = _sha(_json(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
