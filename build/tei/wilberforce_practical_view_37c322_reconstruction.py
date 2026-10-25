"""Ticket-local readable TEI adapter for the retained Wilberforce witness.

The LIB-072 producer supplies the established source block and heading
structure. This adapter owns the ticket's Project Gutenberg underscore
classification and changes delimiter-bearing wrappers into readable italics.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from build.tei import gutenberg_evangelical_lib072_selected_reconstruction as _shared


TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
WORK_ID = "wilberforce-practical-view"
PROFILE_ID = "selected-proofread-37c-322-v3"
EXPECTED_MARKER_COUNT = 1304
EXPECTED_DELIMITER_COUNT = 1304
EXPECTED_LITERAL_MARKER_COUNT = 0
EXPECTED_SPAN_COUNT = 652
EXPECTED_MAX_INTERIOR_CHARACTERS = 566
ENCODING_POLICY = (
    "Balanced Project Gutenberg underscore delimiters are removed from readable text; each verified interior is encoded as hi rend=italic and identified by exact source locators and a raw source-slice digest. Underscores internal to ASCII alphanumeric identifiers remain literal text. Multiline emphasis is split at retained source lines with continuations linked to the opening fragment."
)
SOURCE_MARKUP_POLICY = {
    "contract": "ocd-pg-underscore-emphasis-source-slices-v2",
    "marker_character": "_",
    "expected_marker_count": EXPECTED_MARKER_COUNT,
    "expected_delimiter_count": EXPECTED_DELIMITER_COUNT,
    "expected_literal_marker_count": EXPECTED_LITERAL_MARKER_COUNT,
    "expected_span_count": EXPECTED_SPAN_COUNT,
    "maximum_interior_character_count": EXPECTED_MAX_INTERIOR_CHARACTERS,
    "pairing_scope": "classify ASCII alphanumeric-internal underscores as literal; pair remaining emphasis delimiters within each blank-line-delimited source block",
    "classification_rule": "An underscore between ASCII letters or digits is literal source text and is not a Project Gutenberg emphasis delimiter. Other underscore characters are emphasis delimiters and must form balanced, nonempty pairs within one source block.",
    "representation": "Omit each paired outer delimiter from readable TEI; encode its exact interior as hi rend=italic, split only at retained source-line boundaries, and link continuation fragments to the opening fragment. Preserve internal literal underscores in the readable text.",
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _rows(content: bytes) -> list[dict[str, object]]:
    """Split only CR/LF while retaining exact source byte and line locations."""
    content.decode("utf-8")
    rows: list[dict[str, object]] = []
    position = 0
    line_number = 1
    while position < len(content):
        cr = content.find(b"\r", position)
        lf = content.find(b"\n", position)
        candidates = [offset for offset in (cr, lf) if offset >= 0]
        if not candidates:
            rows.append(
                {
                    "line_number": line_number,
                    "text": content[position:].decode("utf-8"),
                    "ending": "none",
                    "byte_start": position,
                    "byte_end": len(content),
                }
            )
            break
        stop = min(candidates)
        text = content[position:stop].decode("utf-8")
        if content[stop : stop + 2] == b"\r\n":
            ending, next_position = "crlf", stop + 2
        elif content[stop : stop + 1] == b"\r":
            ending, next_position = "cr", stop + 1
        else:
            ending, next_position = "lf", stop + 1
        rows.append(
            {
                "line_number": line_number,
                "text": text,
                "ending": ending,
                "byte_start": position,
                "byte_end": stop,
            }
        )
        position = next_position
        line_number += 1
    rebuilt = b"".join(
        str(row["text"]).encode("utf-8")
        + {"crlf": b"\r\n", "lf": b"\n", "cr": b"\r", "none": b""}[
            str(row["ending"])
        ]
        for row in rows
    )
    if rebuilt != content:
        raise ValueError("37c-322 local producer source rows are not byte-lossless")
    return rows


def _units(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    units: list[dict[str, object]] = []
    active: list[dict[str, object]] = []
    block_number = 0
    for row in rows:
        if row["text"] == "":
            if active:
                block_number += 1
                units.append({"kind": "block", "block_number": block_number, "rows": active})
                active = []
            units.append({"kind": "blank", "row": row})
        else:
            active.append(row)
    if active:
        block_number += 1
        units.append({"kind": "block", "block_number": block_number, "rows": active})
    return units


def _ascii_alphanumeric(character: str) -> bool:
    return len(character) == 1 and character.isascii() and character.isalnum()


def _scan_emphasis(
    content: bytes,
) -> tuple[list[dict[str, object]], list[dict[str, object]], int]:
    """Return source-located emphasis spans, literal underscores, marker count.

    ASCII alphanumeric-internal underscores are retained as source text before
    pairing the remaining Gutenberg emphasis delimiters. Adjacent underscore
    runs are rejected as ambiguous instead of guessed.
    """
    rows = _rows(content)
    result: list[dict[str, object]] = []
    literal_markers: list[dict[str, object]] = []
    marker_count = 0
    for unit in _units(rows):
        if unit["kind"] != "block":
            continue
        block_number = int(unit["block_number"])
        block_rows = unit["rows"]
        row_by_line = {int(row["line_number"]): row for row in block_rows}
        markers: list[tuple[int, int]] = []
        for row in block_rows:
            text = str(row["text"])
            line_number = int(row["line_number"])
            for index, character in enumerate(text):
                if character != "_":
                    continue
                marker_count += 1
                previous = text[index - 1] if index else ""
                following = text[index + 1] if index + 1 < len(text) else ""
                if previous == "_" or following == "_":
                    raise ValueError(
                        f"adjacent underscore sequence is ambiguous at {line_number}:{index + 1}"
                    )
                if _ascii_alphanumeric(previous) and _ascii_alphanumeric(following):
                    byte_offset = int(row["byte_start"]) + len(text[:index].encode("utf-8"))
                    literal_markers.append(
                        {
                            "line_number": line_number,
                            "column": index + 1,
                            "byte_offset": byte_offset,
                            "character": "_",
                            "sha256": _sha(b"_"),
                        }
                    )
                else:
                    markers.append((line_number, index + 1))
        if len(markers) % 2:
            line_number, column = markers[-1]
            raise ValueError(
                f"unmatched Gutenberg emphasis delimiter at {line_number}:{column}"
            )
        for marker_index in range(0, len(markers), 2):
            start_line, start_column = markers[marker_index]
            end_line, end_column = markers[marker_index + 1]
            start_row = row_by_line[start_line]
            end_row = row_by_line[end_line]
            interior_parts: list[str] = []
            fragment_rows = list(range(start_line, end_line + 1))
            for line_number in fragment_rows:
                text = str(row_by_line[line_number]["text"])
                if start_line == end_line:
                    interior_parts.append(text[start_column : end_column - 1])
                elif line_number == start_line:
                    interior_parts.append(text[start_column:])
                elif line_number == end_line:
                    interior_parts.append(text[: end_column - 1])
                else:
                    interior_parts.append(text)
            interior = "\n".join(interior_parts)
            if not interior.strip():
                raise ValueError(
                    f"empty Gutenberg emphasis span at {start_line}:{start_column}"
                )
            fragments: list[dict[str, object]] = []
            for part_index, line_number in enumerate(fragment_rows, 1):
                text = str(row_by_line[line_number]["text"])
                first_column = start_column + 1 if line_number == start_line else 1
                last_column = end_column - 1 if line_number == end_line else len(text)
                if first_column > last_column:
                    raise ValueError(
                        f"empty emphasis continuation at {line_number}:{first_column}"
                    )
                fragment_text = text[first_column - 1 : last_column]
                fragments.append(
                    {
                        "line_number": line_number,
                        "start_column": first_column,
                        "end_column": last_column,
                        "part_index": part_index,
                        "part_count": len(fragment_rows),
                        "text_sha256": _sha(fragment_text.encode("utf-8")),
                    }
                )
            start_byte = int(start_row["byte_start"]) + len(
                str(start_row["text"][: start_column - 1]).encode("utf-8")
            )
            end_byte = int(end_row["byte_start"]) + len(
                str(end_row["text"][:end_column]).encode("utf-8")
            )
            source_slice = content[start_byte:end_byte]
            span_number = len(result) + 1
            result.append(
                {
                    "span_id": f"{WORK_ID}-underscore-{span_number:04d}",
                    "block_id": f"{WORK_ID}-block-{block_number:05d}",
                    "start_line": start_line,
                    "start_column": start_column,
                    "end_line": end_line,
                    "end_column": end_column,
                    "logical_character_count": len(interior) + 2,
                    "interior_character_count": len(interior),
                    "physical_byte_count": len(source_slice),
                    "source_sha256": _sha(source_slice),
                    "source_slice_byte_start": start_byte,
                    "source_slice_byte_end": end_byte,
                    "opening_delimiter": {
                        "line_number": start_line,
                        "column": start_column,
                        "byte_offset": start_byte,
                        "character": "_",
                        "sha256": _sha(b"_"),
                    },
                    "closing_delimiter": {
                        "line_number": end_line,
                        "column": end_column,
                        "byte_offset": end_byte - 1,
                        "character": "_",
                        "sha256": _sha(b"_"),
                    },
                    "fragments": fragments,
                }
            )
    return result, literal_markers, marker_count


class _MemoryAuthority:
    def __init__(self, name: str, content: bytes) -> None:
        self.name = name
        self._content = content

    def read_bytes(self) -> bytes:
        return self._content


class _SharedProducerManifestView:
    """Adapt the ticket profile to the shared producer's legacy policy gate."""

    def __init__(self, source_manifest: object, legacy_profile: bytes) -> None:
        self._source_manifest = source_manifest
        self._legacy_profile = legacy_profile

    @property
    def record(self):
        return self._source_manifest.record

    @property
    def sha256(self) -> str:
        return self._source_manifest.sha256

    def verify(self) -> None:
        self._source_manifest.verify()

    def authority_path(self, name: str):
        if name == "reconstruction-profile":
            actual_path = self._source_manifest.authority_path(name)
            return _MemoryAuthority(actual_path.name, self._legacy_profile)
        return self._source_manifest.authority_path(name)


def _visible_wrapper_text(line_text: str, fragment: Mapping[str, object]) -> str:
    start = int(fragment["start_column"])
    end = int(fragment["end_column"])
    return line_text[start - 1 : end]


def _convert(source_manifest) -> Mapping[str, bytes]:
    """Generate a candidate with readable italics and reversible raw markers."""
    source_manifest.verify()
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    profile = json.loads(profile_bytes.decode("utf-8"))
    if (
        profile.get("profile_id") != PROFILE_ID
        or profile.get("ticket_id") != "37c-322"
        or profile.get("source_underscore_policy") != SOURCE_MARKUP_POLICY
    ):
        raise ValueError("37c-322 local producer profile binding drifted")
    source = source_manifest.authority_path("primary-source").read_bytes()
    spans, literal_markers, marker_count = _scan_emphasis(source)
    if (
        marker_count != EXPECTED_MARKER_COUNT
        or len(literal_markers) != EXPECTED_LITERAL_MARKER_COUNT
        or len(spans) != EXPECTED_SPAN_COUNT
        or max(int(span["interior_character_count"]) for span in spans)
        != EXPECTED_MAX_INTERIOR_CHARACTERS
    ):
        raise ValueError("37c-322 underscore/emphasis source census drifted")

    compatibility_profile = dict(profile)
    compatibility_profile["source_underscore_policy"] = dict(
        _shared.SOURCE_UNDERSCORE_POLICY
    )
    shared_view = _SharedProducerManifestView(
        source_manifest,
        _canonical(compatibility_profile),
    )
    produced = dict(_shared._convert(shared_view))
    accountability = json.loads(produced["source-accountability.json"].decode("utf-8"))
    base_spans = accountability["works"][0]["source_underscore_markup"]["spans"]
    source_signature = [
        (
            span["span_id"],
            span["block_id"],
            span["start_line"],
            span["start_column"],
            span["end_line"],
            span["end_column"],
            span["source_sha256"],
        )
        for span in spans
    ]
    base_signature = [
        (
            span["span_id"],
            span["block_id"],
            span["start_line"],
            span["start_column"],
            span["end_line"],
            span["end_column"],
            span["source_sha256"],
        )
        for span in base_spans
    ]
    if source_signature != base_signature:
        raise ValueError(
            "37c-322 local delimiter inventory differs from its shared structural input"
        )

    rows = _rows(source)
    row_by_line = {int(row["line_number"]): str(row["text"]) for row in rows}
    document = etree.fromstring(produced["content.tei.xml"])
    q = lambda name: f"{{{TEI_NS}}}{name}"
    for span in spans:
        base_span = next(item for item in base_spans if item["span_id"] == span["span_id"])
        for fragment, base_fragment in zip(
            span["fragments"], base_span["fragments"], strict=True
        ):
            line_number = int(fragment["line_number"])
            old_start = int(base_fragment["start_column"])
            old_end = int(base_fragment["end_column"])
            old_text = row_by_line[line_number][old_start - 1 : old_end]
            visible_text = _visible_wrapper_text(row_by_line[line_number], fragment)
            first = int(fragment["part_index"]) == 1
            last = int(fragment["part_index"]) == int(fragment["part_count"])
            expected_old_text = ("_" if first else "") + visible_text + ("_" if last else "")
            if old_text != expected_old_text:
                raise ValueError(
                    f"37c-322 wrapper delimiter projection drift at {line_number}"
                )
            line_node = document.xpath(
                ".//tei:seg[@type='source-line'][@n=$line]",
                namespaces={"tei": TEI_NS},
                line=str(line_number),
            )
            if len(line_node) != 1:
                raise ValueError(f"37c-322 local TEI line is absent: {line_number}")
            if first:
                nodes = line_node[0].xpath(
                    "./tei:hi[@xml:id=$span]",
                    namespaces={"tei": TEI_NS},
                    span=str(span["span_id"]),
                )
            else:
                nodes = line_node[0].xpath(
                    "./tei:hi[@corresp=$span]",
                    namespaces={"tei": TEI_NS},
                    span=f"#{span['span_id']}",
                )
            if len(nodes) != 1 or nodes[0].text != old_text:
                raise ValueError(
                    f"37c-322 shared wrapper identity drift at {line_number}"
                )
            nodes[0].set("rend", "italic")
            nodes[0].text = visible_text

    work_row = accountability["works"][0]
    work_row["source_underscore_markup"] = {
        "contract": SOURCE_MARKUP_POLICY["contract"],
        "marker_character": "_",
        "marker_count": marker_count,
        "delimiter_count": len(spans) * 2,
        "literal_underscore_count": len(literal_markers),
        "span_count": len(spans),
        "maximum_interior_character_count": max(
            int(span["interior_character_count"]) for span in spans
        ),
        "pairing_scope": SOURCE_MARKUP_POLICY["pairing_scope"],
        "classification_rule": SOURCE_MARKUP_POLICY["classification_rule"],
        "representation": SOURCE_MARKUP_POLICY["representation"],
        "literal_markers": literal_markers,
        "spans": spans,
    }
    accountability["contract"] = "ocd-selected-source-accountability-v3"
    accountability["profile_id"] = PROFILE_ID
    accountability["source_byte_reassembly"] = (
        "readable TEI text plus exact recorded Gutenberg underscore delimiters and each source line's recorded CR/LF terminator"
    )
    accountability["block_mapping"] = (
        "blank-line-delimited source blocks retained in order; source-located headings and mapped title attachments encoded; every underscore classified as literal source text or emphasis delimiter; emphasis interiors encoded as readable italics and removed delimiters located and reversible"
    )
    produced["source-accountability.json"] = _canonical(accountability)
    encoding_node = document.find(
        "./{http://www.tei-c.org/ns/1.0}teiHeader/"
        "{http://www.tei-c.org/ns/1.0}encodingDesc/"
        "{http://www.tei-c.org/ns/1.0}projectDesc/"
        "{http://www.tei-c.org/ns/1.0}p"
    )
    if encoding_node is None:
        raise ValueError("37c-322 encoding statement is absent")
    encoding_node.text = ENCODING_POLICY
    produced["content.tei.xml"] = etree.tostring(
        document,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=False,
    )
    return produced


_convert.converter_id = "ocd-lib072-37c-322-readable-italic-adapter"
_convert.converter_version = "1"
_convert.implementation_path = Path(__file__).resolve()
