"""Ticket-local PG underscore-emphasis overlay for Drummond's source member.

The shared LIB-071 builder owns headings, blocks, and line accountability. This
adapter preserves that output and adds the source-marked emphasis represented by
balanced Project Gutenberg underscores, retaining both delimiter characters.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import re
from typing import Mapping, Protocol

from lxml import etree


CONVERTER_ID = "ocd-37c-135-drummond-source-underscore-to-tei"
CONVERTER_VERSION = "1"
BASE_CONVERTER_PATH = (
    "build/tei/gutenberg_evangelical_lib071_selected_reconstruction.py"
)
BASE_CONVERTER_AUTHORITY = "base-converter-implementation"
MARKUP_CONTRACT = "ocd-source-underscore-emphasis-v1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_EOL_TEXT = {"crlf": "\r\n", "lf": "\n", "cr": "\r", "none": ""}
_EOL_BYTES = {key: value.encode("ascii") for key, value in _EOL_TEXT.items()}


class SourceManifestLike(Protocol):
    @property
    def record(self) -> Mapping[str, object]: ...

    @property
    def repository_root(self) -> Path: ...

    def authority_path(self, name: str) -> Path: ...

    def verify(self) -> None: ...


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    value = json.loads(content.decode("utf-8"), object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _authority(source_manifest: SourceManifestLike, name: str) -> Mapping[str, object]:
    authorities = source_manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("37c-135 source manifest authority inventory is invalid")
    matches = [
        item
        for item in authorities
        if isinstance(item, Mapping) and item.get("name") == name
    ]
    if len(matches) != 1:
        raise ValueError(f"37c-135 source manifest must bind one {name!r} authority")
    return matches[0]


def _load_base_converter(source_manifest: SourceManifestLike):
    authority = _authority(source_manifest, BASE_CONVERTER_AUTHORITY)
    if (
        authority.get("path") != BASE_CONVERTER_PATH
        or authority.get("role") != "base-converter-dependency"
    ):
        raise ValueError("37c-135 base converter authority path or role drifted")
    path = source_manifest.repository_root / BASE_CONVERTER_PATH
    path = path.resolve(strict=True)
    content = path.read_bytes()
    if (
        authority.get("bytes") != len(content)
        or authority.get("sha256") != _sha(content)
    ):
        raise ValueError("37c-135 base converter dependency digest drifted")
    module_name = f"_ocd_37c135_base_converter_{_sha(content)}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValueError("37c-135 base converter cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    loaded = Path(module.__file__).resolve(strict=True)
    if not loaded.samefile(path):
        raise ValueError("37c-135 base converter loaded from a shadow path")
    if (
        getattr(module, "CONVERTER_ID", None)
        != "ocd-lib071-selected-proofread-text-to-tei"
        or getattr(module, "CONVERTER_VERSION", None) != "4"
    ):
        raise ValueError("37c-135 base converter identity or version drifted")
    return module


def _source_rows(content: bytes) -> list[dict[str, object]]:
    """Split CR/LF-delimited UTF-8 text and keep every original terminator."""

    content.decode("utf-8")
    parts = re.split(rb"(\r\n|\r|\n)", content)
    if content == b"":
        return []
    if len(parts) % 2 == 0:
        raise ValueError("37c-135 source has an incomplete line delimiter")
    ending_by_bytes = {value: key for key, value in _EOL_BYTES.items() if value}
    rows: list[dict[str, object]] = []
    for index in range(0, len(parts) - 1, 2):
        ending = ending_by_bytes.get(parts[index + 1])
        if ending is None:
            raise ValueError("37c-135 source has an unsupported line delimiter")
        rows.append(
            {
                "line_number": len(rows) + 1,
                "text": parts[index].decode("utf-8"),
                "ending": ending,
            }
        )
    if parts[-1] != b"":
        rows.append(
            {
                "line_number": len(rows) + 1,
                "text": parts[-1].decode("utf-8"),
                "ending": "none",
            }
        )
    rebuilt = b"".join(
        str(row["text"]).encode("utf-8")
        + _EOL_BYTES[str(row["ending"])]
        for row in rows
    )
    if rebuilt != content:
        raise ValueError("37c-135 source-line scan did not reassemble exact bytes")
    return rows


def _source_marker_spans(
    content: bytes, rows: list[dict[str, object]] | None = None
) -> tuple[list[dict[str, object]], dict[int, list[dict[str, object]]]]:
    """Pair only balanced, nonempty, unambiguous underscore spans."""

    rows = _source_rows(content) if rows is None else rows
    full_text = content.decode("utf-8")
    line_offsets: list[int] = []
    offset = 0
    for row in rows:
        line_offsets.append(offset)
        offset += len(str(row["text"])) + len(_EOL_TEXT[str(row["ending"])])
    if offset != len(full_text):
        raise ValueError("37c-135 source line offsets do not cover the source text")

    markers: list[dict[str, object]] = []
    for row, line_offset in zip(rows, line_offsets, strict=True):
        text = str(row["text"])
        line_number = int(row["line_number"])
        for index, character in enumerate(text):
            if character == "_":
                markers.append(
                    {
                        "line_number": line_number,
                        "column": index + 1,
                        "offset": line_offset + index,
                    }
                )
    if len(markers) % 2:
        raise ValueError("37c-135 source has an unmatched underscore marker")

    spans: list[dict[str, object]] = []
    marker_events: dict[int, list[dict[str, object]]] = {}
    for span_number, (opening, closing) in enumerate(
        zip(markers[::2], markers[1::2], strict=True), 1
    ):
        start_line = int(opening["line_number"])
        end_line = int(closing["line_number"])
        start_column = int(opening["column"])
        end_column = int(closing["column"])
        value = full_text[int(opening["offset"]) + 1 : int(closing["offset"])]
        if not value or "_" in value:
            raise ValueError("37c-135 source has an empty or ambiguous underscore span")
        if any(
            str(rows[index - 1]["text"]) == ""
            for index in range(start_line + 1, end_line)
        ):
            raise ValueError("37c-135 underscore span crosses a blank source line")

        fragments: list[dict[str, object]] = []
        for line_number in range(start_line, end_line + 1):
            row = rows[line_number - 1]
            row_text = str(row["text"])
            fragment_start = start_column + 1 if line_number == start_line else 1
            fragment_end = end_column - 1 if line_number == end_line else len(row_text)
            if fragment_end < fragment_start:
                raise ValueError("37c-135 source has an empty emphasis line fragment")
            fragment_text = row_text[fragment_start - 1 : fragment_end]
            if not fragment_text:
                raise ValueError("37c-135 source has an empty emphasis line fragment")
            fragments.append(
                {
                    "line_number": line_number,
                    "start_column": fragment_start,
                    "end_column": fragment_end,
                    "text": fragment_text,
                    "text_sha256": _sha(fragment_text.encode("utf-8")),
                }
            )
        reconstructed_value = "".join(
            str(fragment["text"])
            + (
                _EOL_TEXT[str(rows[int(fragment["line_number"]) - 1]["ending"])]
                if int(fragment["line_number"]) < end_line
                else ""
            )
            for fragment in fragments
        )
        if reconstructed_value != value:
            raise ValueError("37c-135 underscore fragments do not match source text")

        span_id = f"drummond-underscore-{span_number:05d}"
        span = {
            "span_id": span_id,
            "start_line": start_line,
            "start_column": start_column,
            "end_line": end_line,
            "end_column": end_column,
            "content": value,
            "content_sha256": _sha(value.encode("utf-8")),
            "fragments": fragments,
        }
        spans.append(span)
        marker_events.setdefault(start_line, []).append(
            {"column": start_column, "role": "open", "span_id": span_id}
        )
        marker_events.setdefault(end_line, []).append(
            {"column": end_column, "role": "close", "span_id": span_id}
        )

    for events in marker_events.values():
        events.sort(key=lambda item: int(item["column"]))
        if len({int(item["column"]) for item in events}) != len(events):
            raise ValueError("37c-135 source has ambiguous coincident underscore markers")
    return spans, marker_events


def _append_text(parent: etree._Element, value: str) -> None:
    if not value:
        return
    if len(parent):
        last = parent[-1]
        last.tail = (last.tail or "") + value
    else:
        parent.text = (parent.text or "") + value


def _delimiter(parent: etree._Element, span_id: str) -> etree._Element:
    element = etree.SubElement(
        parent,
        f"{{{TEI_NS}}}c",
        type="emphasis-delimiter",
        corresp=f"#{span_id}",
    )
    element.text = "_"
    return element


def _hi_fragment(
    parent: etree._Element, span_id: str, *, first_fragment: bool
) -> etree._Element:
    element = etree.SubElement(
        parent,
        f"{{{TEI_NS}}}hi",
        rend="italic",
        ana="#source-underscore",
    )
    if first_fragment:
        element.set(XML_ID, span_id)
    else:
        element.set("corresp", f"#{span_id}")
    return element


def _apply_source_markup(
    tei_root: etree._Element,
    rows: list[dict[str, object]],
    spans: list[dict[str, object]],
    marker_events: dict[int, list[dict[str, object]]],
) -> None:
    segments: dict[int, list[etree._Element]] = {}
    for segment in tei_root.xpath(
        ".//tei:seg[@type='source-line']",
        namespaces={"tei": TEI_NS},
    ):
        try:
            line_number = int(segment.get("n", ""))
        except ValueError as exc:
            raise ValueError("37c-135 source-line segment has an invalid line number") from exc
        segments.setdefault(line_number, []).append(segment)

    active_span: str | None = None
    for row in rows:
        line_number = int(row["line_number"])
        source_text = str(row["text"])
        events = marker_events.get(line_number, [])
        if not events and active_span is None:
            continue
        matching = segments.get(line_number, [])
        if len(matching) != 1:
            raise ValueError(
                f"37c-135 emphasis source line {line_number} has no unique source-line segment"
            )
        segment = matching[0]
        if segment.text != source_text or len(segment):
            raise ValueError(
                f"37c-135 base converter text differs at marked source line {line_number}"
            )
        segment.text = None
        cursor = 0
        active_hi: etree._Element | None = None
        if active_span is not None:
            active_hi = _hi_fragment(segment, active_span, first_fragment=False)

        for event in events:
            column = int(event["column"])
            marker_index = column - 1
            role = str(event["role"])
            span_id = str(event["span_id"])
            _append_text_to_active_or_segment(
                segment,
                active_hi,
                source_text[cursor:marker_index],
            )
            if role == "open":
                if active_span is not None or active_hi is not None:
                    raise ValueError("37c-135 source underscore spans unexpectedly overlap")
                _delimiter(segment, span_id)
                active_hi = _hi_fragment(segment, span_id, first_fragment=True)
                active_span = span_id
            elif role == "close":
                if active_span != span_id or active_hi is None:
                    raise ValueError("37c-135 source underscore close marker has no opener")
                _delimiter(segment, span_id)
                active_span = None
                active_hi = None
            else:
                raise ValueError("37c-135 source underscore event has an unknown role")
            cursor = marker_index + 1

        _append_text_to_active_or_segment(segment, active_hi, source_text[cursor:])
        if "".join(segment.itertext()) != source_text:
            raise ValueError(
                f"37c-135 inline markup changed exact source text at line {line_number}"
            )
    if active_span is not None:
        raise ValueError("37c-135 source underscore span was not closed")

    expected_span_count = len(spans)
    actual_ids = {
        element.get(XML_ID)
        for element in tei_root.xpath(
            ".//tei:hi[@ana='#source-underscore']",
            namespaces={"tei": TEI_NS},
        )
        if element.get(XML_ID)
    }
    if len(actual_ids) != expected_span_count:
        raise ValueError("37c-135 source underscore TEI span IDs are incomplete")


def _append_text_to_active_or_segment(
    segment: etree._Element,
    active_hi: etree._Element | None,
    value: str,
) -> None:
    if not value:
        return
    if active_hi is not None:
        active_hi.text = (active_hi.text or "") + value
    else:
        _append_text(segment, value)


def _convert(source_manifest: SourceManifestLike) -> Mapping[str, bytes]:
    source_manifest.verify()
    record = source_manifest.record
    if (
        record.get("ticket_id") != "37c-135"
        or record.get("work_id") != "drummond-greatest-thing"
        or record.get("source_id") != "gutenberg-37c-135-pg16739"
    ):
        raise ValueError("37c-135 marker adapter rejects an out-of-scope source manifest")
    converter = record.get("converter")
    if not isinstance(converter, Mapping) or (
        converter.get("id") != CONVERTER_ID
        or converter.get("version") != CONVERTER_VERSION
        or converter.get("implementation_path")
        != "build/tei/drummond_greatest_thing_37c135_reconstruction.py"
    ):
        raise ValueError("37c-135 marker converter binding drifted")

    profile = _strict_json(
        source_manifest.authority_path("reconstruction-profile").read_bytes(),
        "37c-135 reconstruction profile",
    )
    works = profile.get("works")
    if not isinstance(works, list) or len(works) != 1 or not isinstance(works[0], dict):
        raise ValueError("37c-135 marker profile must bind exactly one work")
    work = works[0]
    marker_policy = work.get("source_underscore_markup")
    if not isinstance(marker_policy, Mapping) or (
        marker_policy.get("contract") != MARKUP_CONTRACT
        or marker_policy.get("delimiter") != "_"
        or marker_policy.get("marker_count") != 362
        or marker_policy.get("span_count") != 181
    ):
        raise ValueError("37c-135 source underscore mapping policy is absent or drifted")

    source_authority = _authority(source_manifest, "primary-source")
    source_path = source_manifest.authority_path("primary-source")
    content = source_path.read_bytes()
    if (
        source_authority.get("path") != "raw/gutenberg/pg16739.txt"
        or source_authority.get("bytes") != len(content)
        or source_authority.get("sha256") != _sha(content)
        or _sha(content) != "12f442db074bfd81db981dfb7c423120e830feb2019b2c0db253692e23624048"
    ):
        raise ValueError("37c-135 primary source does not match its exact retained bytes")
    rows = _source_rows(content)
    spans, marker_events = _source_marker_spans(content, rows)
    marker_count = sum(len(events) for events in marker_events.values())
    if marker_count != 362 or len(spans) != 181:
        raise ValueError("37c-135 source underscore census differs from the bound policy")

    base_converter = _load_base_converter(source_manifest)
    produced = dict(base_converter._convert(source_manifest))
    tei_bytes = produced.get("content.tei.xml")
    accountability_bytes = produced.get("source-accountability.json")
    provenance_bytes = produced.get("provenance.json")
    if not isinstance(tei_bytes, bytes) or not isinstance(accountability_bytes, bytes):
        raise ValueError("37c-135 base converter omitted a required member")
    if not isinstance(provenance_bytes, bytes):
        raise ValueError("37c-135 base converter omitted provenance")

    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
    tei_root = etree.fromstring(tei_bytes, parser=parser)
    _apply_source_markup(tei_root, rows, spans, marker_events)
    produced["content.tei.xml"] = etree.tostring(
        tei_root,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=False,
    )

    accountability = _strict_json(accountability_bytes, "37c-135 source accountability")
    work_rows = accountability.get("works")
    if not isinstance(work_rows, list) or len(work_rows) != 1 or not isinstance(work_rows[0], dict):
        raise ValueError("37c-135 source accountability must bind exactly one work")
    work_rows[0]["source_underscore_markup"] = {
        "contract": MARKUP_CONTRACT,
        "marker_count": marker_count,
        "span_count": len(spans),
        "spans": spans,
    }
    produced["source-accountability.json"] = _canonical(accountability)

    provenance = _strict_json(provenance_bytes, "37c-135 provenance")
    provenance["source_underscore_markup"] = {
        "contract": MARKUP_CONTRACT,
        "marker_count": marker_count,
        "span_count": len(spans),
        "representation": (
            "Literal underscore delimiters are retained in <c> elements; "
            "source-marked text is represented by <hi rend=\"italic\"> "
            "fragments linked by xml:id/corresp."
        ),
        "accountability_pointer": "/works/0/source_underscore_markup",
    }
    produced["provenance.json"] = _canonical(provenance)
    return produced


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
