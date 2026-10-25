"""Independent 37c-135 oracle for retained Project Gutenberg emphasis markers.

This checker derives underscore spans from the bound source independently of
the ticket-local converter. It checks every delimiter and inline fragment, then
delegates the unchanged block, heading, and source-line checks to the current
shared LIB-071 oracle through a constrained base-view adapter.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import platform
from pathlib import Path
import sys
from types import MappingProxyType
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from lxml import etree


ORACLE_ID = "ocd-37c-135-drummond-source-underscore-independent-oracle"
ORACLE_VERSION = "1"
BASE_ORACLE_PATH = "build/tei/gutenberg_proofread_selected_oracle.py"
BASE_ORACLE_AUTHORITY = "base-oracle-implementation"
BASE_CONVERTER_PATH = (
    "build/tei/gutenberg_evangelical_lib071_selected_reconstruction.py"
)
BASE_CONVERTER_AUTHORITY = "base-converter-implementation"
LOCAL_ORACLE_PATH = "build/tei/drummond_greatest_thing_37c135_oracle.py"
LOCAL_CONVERTER_PATH = (
    "build/tei/drummond_greatest_thing_37c135_reconstruction.py"
)
MARKUP_CONTRACT = "ocd-source-underscore-emphasis-v1"
SOURCE_PATH = "raw/gutenberg/pg16739.txt"
SOURCE_SHA256 = "12f442db074bfd81db981dfb7c423120e830feb2019b2c0db253692e23624048"
SOURCE_BYTES = 204970
SOURCE_ID = "gutenberg-37c-135-pg16739"
WORK_ID = "drummond-greatest-thing"
TICKET_ID = "37c-135"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_ENDING_TEXT = {"crlf": "\r\n", "lf": "\n", "cr": "\r", "none": ""}
_ENDING_BYTES = {key: value.encode("ascii") for key, value in _ENDING_TEXT.items()}
_BASE_AUTHORITY_NAMES = (
    "work-identity",
    "ticket-scope",
    "primary-source",
    "source-local-readme",
    "reconstruction-profile",
    "validation-policy",
    "source-accountability-schema",
    "tei-p5-xsd",
    "tei-p5-xsd-teix",
    "tei-p5-xsd-xml",
    "candidate-package-schema",
    "converter-implementation",
    "oracle-implementation",
)
_REQUIRED_MUTATIONS = {
    "source underscore delimiter deletion or movement",
    "source underscore emphasis carrier or target drift",
    "source underscore continuation fragment detachment",
    "source underscore accountability locator drift",
    "unmatched, empty, nested, or blank-delimited source underscore span",
}


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


def _authority(source_manifest: Any, name: str) -> Mapping[str, object]:
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


def _oracle_source_rows(content: bytes) -> list[dict[str, object]]:
    """Independently scan decoded text lines while retaining original endings."""

    decoded = content.decode("utf-8")
    rows: list[dict[str, object]] = []
    current: list[str] = []
    index = 0
    line_number = 1
    while index < len(decoded):
        character = decoded[index]
        if character not in "\r\n":
            current.append(character)
            index += 1
            continue
        if character == "\r" and index + 1 < len(decoded) and decoded[index + 1] == "\n":
            ending = "crlf"
            index += 2
        else:
            ending = "cr" if character == "\r" else "lf"
            index += 1
        rows.append(
            {"line_number": line_number, "text": "".join(current), "ending": ending}
        )
        line_number += 1
        current = []
    if current or not rows:
        rows.append(
            {"line_number": line_number, "text": "".join(current), "ending": "none"}
        )
    rebuilt = b"".join(
        str(row["text"]).encode("utf-8")
        + _ENDING_BYTES[str(row["ending"])]
        for row in rows
    )
    if rebuilt != content:
        raise ValueError("37c-135 independent oracle line scan did not reassemble bytes")
    return rows


def _oracle_marker_census(
    content: bytes, rows: list[dict[str, object]]
) -> tuple[list[dict[str, object]], dict[int, list[dict[str, object]]]]:
    """Derive marker spans without importing producer helpers."""

    decoded = content.decode("utf-8")
    offsets: dict[int, int] = {}
    offset = 0
    for row in rows:
        line_number = int(row["line_number"])
        offsets[line_number] = offset
        offset += (
            len(str(row["text"]))
            + len(_ENDING_TEXT[str(row["ending"])])
        )
    if offset != len(decoded):
        raise ValueError("37c-135 independent oracle offsets do not cover source")

    observed: list[dict[str, object]] = []
    for row in rows:
        line_number = int(row["line_number"])
        for column, character in enumerate(str(row["text"]), 1):
            if character == "_":
                observed.append(
                    {
                        "line_number": line_number,
                        "column": column,
                        "offset": offsets[line_number] + column - 1,
                    }
                )
    if len(observed) % 2:
        raise ValueError("37c-135 unmatched source underscore marker")

    pairs = list(zip(observed[::2], observed[1::2], strict=True))
    spans: list[dict[str, object]] = []
    events: dict[int, list[dict[str, object]]] = {}
    for span_number, (left, right) in enumerate(pairs, 1):
        first_line = int(left["line_number"])
        last_line = int(right["line_number"])
        first_column = int(left["column"])
        last_column = int(right["column"])
        text = decoded[int(left["offset"]) + 1 : int(right["offset"])]
        if not text or "_" in text:
            raise ValueError("37c-135 empty or nested source underscore span")
        if any(
            str(rows[line - 1]["text"]) == ""
            for line in range(first_line + 1, last_line)
        ):
            raise ValueError("37c-135 source underscore span crosses a blank line")

        pieces: list[dict[str, object]] = []
        for line_number in range(first_line, last_line + 1):
            row_text = str(rows[line_number - 1]["text"])
            piece_start = first_column + 1 if line_number == first_line else 1
            piece_end = last_column - 1 if line_number == last_line else len(row_text)
            if piece_end < piece_start:
                raise ValueError("37c-135 empty source underscore line fragment")
            piece_text = row_text[piece_start - 1 : piece_end]
            if piece_text == "":
                raise ValueError("37c-135 empty source underscore line fragment")
            pieces.append(
                {
                    "line_number": line_number,
                    "start_column": piece_start,
                    "end_column": piece_end,
                    "text": piece_text,
                    "text_sha256": _sha(piece_text.encode("utf-8")),
                }
            )
        rebuilt_text = "".join(
            str(piece["text"])
            + (
                _ENDING_TEXT[str(rows[int(piece["line_number"]) - 1]["ending"])]
                if int(piece["line_number"]) < last_line
                else ""
            )
            for piece in pieces
        )
        if rebuilt_text != text:
            raise ValueError("37c-135 source underscore fragments differ from source")

        span_id = f"drummond-underscore-{span_number:05d}"
        spans.append(
            {
                "span_id": span_id,
                "start_line": first_line,
                "start_column": first_column,
                "end_line": last_line,
                "end_column": last_column,
                "content": text,
                "content_sha256": _sha(text.encode("utf-8")),
                "fragments": pieces,
            }
        )
        events.setdefault(first_line, []).append(
            {"column": first_column, "role": "open", "span_id": span_id}
        )
        events.setdefault(last_line, []).append(
            {"column": last_column, "role": "close", "span_id": span_id}
        )

    for items in events.values():
        items.sort(key=lambda item: int(item["column"]))
        if len({int(item["column"]) for item in items}) != len(items):
            raise ValueError("37c-135 coincident source underscore markers are ambiguous")
    return spans, events


def _expected_inline_events(
    text: str,
    events: list[dict[str, object]],
    active_from_previous_line: str | None,
) -> tuple[list[tuple[str, str, Mapping[str, str]]], str | None]:
    expected: list[tuple[str, str, Mapping[str, str]]] = []
    active_span = active_from_previous_line
    active_is_first_fragment = False
    cursor = 0
    if not events and active_span is not None:
        expected.append(
            (
                "hi",
                text,
                {
                    "rend": "italic",
                    "ana": "#source-underscore",
                    "corresp": f"#{active_span}",
                },
            )
        )
        return expected, active_span

    for event in events:
        marker_index = int(event["column"]) - 1
        if active_span is None:
            plain = text[cursor:marker_index]
            if plain:
                expected.append(("text", plain, {}))
        else:
            marked = text[cursor:marker_index]
            if marked:
                attributes = {
                    "rend": "italic",
                    "ana": "#source-underscore",
                }
                if active_is_first_fragment:
                    attributes[XML_ID] = active_span
                else:
                    attributes["corresp"] = f"#{active_span}"
                expected.append(("hi", marked, attributes))

        role = str(event["role"])
        span_id = str(event["span_id"])
        if role == "open":
            if active_span is not None:
                raise ValueError("37c-135 source markers overlap in the oracle census")
            expected.append(
                (
                    "c",
                    "_",
                    {
                        "type": "emphasis-delimiter",
                        "corresp": f"#{span_id}",
                    },
                )
            )
            active_span = span_id
            active_is_first_fragment = True
        elif role == "close":
            if active_span != span_id:
                raise ValueError("37c-135 source close marker has no active oracle span")
            expected.append(
                (
                    "c",
                    "_",
                    {
                        "type": "emphasis-delimiter",
                        "corresp": f"#{span_id}",
                    },
                )
            )
            active_span = None
            active_is_first_fragment = False
        else:
            raise ValueError("37c-135 oracle saw an unsupported marker event")
        cursor = marker_index + 1

    remainder = text[cursor:]
    if active_span is None:
        if remainder:
            expected.append(("text", remainder, {}))
    elif remainder:
        attributes = {
            "rend": "italic",
            "ana": "#source-underscore",
        }
        if active_is_first_fragment:
            attributes[XML_ID] = active_span
        else:
            attributes["corresp"] = f"#{active_span}"
        expected.append(("hi", remainder, attributes))
    return expected, active_span


def _observed_inline_events(
    segment: etree._Element,
) -> list[tuple[str, str, Mapping[str, str]]]:
    observed: list[tuple[str, str, Mapping[str, str]]] = []
    if segment.text:
        observed.append(("text", segment.text, {}))
    for child in segment:
        if len(child):
            raise ValueError("37c-135 inline emphasis carrier contains nested markup")
        local_name = etree.QName(child).localname
        if local_name not in {"c", "hi"}:
            raise ValueError("37c-135 marked source line contains an unexpected element")
        observed.append(
            (
                local_name,
                child.text or "",
                {str(name): str(value) for name, value in child.attrib.items()},
            )
        )
        if child.tail:
            observed.append(("text", child.tail, {}))
    return observed


def _verify_marker_carriers(
    tei_bytes: bytes,
    rows: list[dict[str, object]],
    spans: list[dict[str, object]],
    marker_events: dict[int, list[dict[str, object]]],
) -> None:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
    root = etree.fromstring(tei_bytes, parser=parser)
    segments: dict[int, list[etree._Element]] = {}
    for segment in root.xpath(
        ".//tei:seg[@type='source-line']",
        namespaces={"tei": TEI_NS},
    ):
        try:
            line_number = int(segment.get("n", ""))
        except ValueError as exc:
            raise ValueError("37c-135 source-line segment has an invalid location") from exc
        segments.setdefault(line_number, []).append(segment)

    active_span: str | None = None
    actual_first_ids: list[str] = []
    for row in rows:
        line_number = int(row["line_number"])
        text = str(row["text"])
        events = marker_events.get(line_number, [])
        if not events and active_span is None:
            continue
        matches = segments.get(line_number, [])
        if len(matches) != 1:
            raise ValueError(
                f"37c-135 source emphasis line {line_number} lacks one bound TEI segment"
            )
        segment = matches[0]
        expected, active_span = _expected_inline_events(text, events, active_span)
        actual = _observed_inline_events(segment)
        if actual != expected:
            raise ValueError(
                f"37c-135 source underscore TEI carrier/order drift at line {line_number}"
            )
        if "".join(segment.itertext()) != text:
            raise ValueError(
                f"37c-135 source underscore TEI text differs at line {line_number}"
            )
        actual_first_ids.extend(
            child.get(XML_ID)
            for child in segment
            if etree.QName(child).localname == "hi"
            and child.get(XML_ID) is not None
        )
    if active_span is not None:
        raise ValueError("37c-135 TEI left a source underscore span open")
    expected_ids = [str(span["span_id"]) for span in spans]
    if actual_first_ids != expected_ids:
        raise ValueError("37c-135 TEI source underscore span identity/order drifted")


def _flatten_line_markup(tei_bytes: bytes) -> bytes:
    """Present the base oracle with its original text-only line carriers."""

    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
    root = etree.fromstring(tei_bytes, parser=parser)
    for segment in root.xpath(
        ".//tei:seg[@type='source-line']",
        namespaces={"tei": TEI_NS},
    ):
        text_parts = [segment.text or ""]
        for child in list(segment):
            if etree.QName(child).localname not in {"c", "hi"} or len(child):
                raise ValueError("37c-135 cannot safely flatten an unknown line carrier")
            text_parts.append(child.text or "")
            text_parts.append(child.tail or "")
            segment.remove(child)
        segment.text = "".join(text_parts)
    return etree.tostring(
        root,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=False,
    )


def _load_base_oracle(source_manifest: Any):
    authority = _authority(source_manifest, BASE_ORACLE_AUTHORITY)
    if (
        authority.get("path") != BASE_ORACLE_PATH
        or authority.get("role") != "base-oracle-dependency"
    ):
        raise ValueError("37c-135 shared oracle authority path or role drifted")
    path = source_manifest.repository_root / BASE_ORACLE_PATH
    path = path.resolve(strict=True)
    content = path.read_bytes()
    if authority.get("bytes") != len(content) or authority.get("sha256") != _sha(content):
        raise ValueError("37c-135 shared oracle dependency digest drifted")
    module_name = f"_ocd_37c135_base_oracle_{_sha(content)}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValueError("37c-135 shared oracle cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    loaded = Path(module.__file__).resolve(strict=True)
    if not loaded.samefile(path):
        raise ValueError("37c-135 shared oracle loaded from a shadow path")
    if (
        getattr(module, "ORACLE_ID", None)
        != "ocd-gutenberg-selected-proofread-independent-oracle"
        or getattr(module, "ORACLE_VERSION", None) != "3"
    ):
        raise ValueError("37c-135 shared oracle identity or version drifted")
    return module


def _base_oracle_closure_digest(base_oracle: Any) -> str:
    path = Path(base_oracle.__file__).resolve(strict=True)
    records = [
        {
            "path": BASE_ORACLE_PATH,
            "sha256": _sha(path.read_bytes()),
        }
    ]
    return _sha(_canonical(records))


class _BaseManifestView:
    """Constrain the shared oracle to its established source-only contract."""

    def __init__(self, source_manifest: Any, base_converter: Any, base_oracle: Any):
        self._source_manifest = source_manifest
        original = dict(source_manifest.record)
        by_name = {
            str(item.get("name")): dict(item)
            for item in original["authorities"]
            if isinstance(item, Mapping)
        }
        expected_names = set(_BASE_AUTHORITY_NAMES)
        records: list[Mapping[str, object]] = []
        for name in _BASE_AUTHORITY_NAMES:
            if name == "converter-implementation":
                dependency = by_name.get(BASE_CONVERTER_AUTHORITY)
                if dependency is None:
                    raise ValueError("37c-135 base converter dependency is not pinned")
                item = {
                    **dependency,
                    "name": name,
                    "role": "source-converter-implementation",
                    "path": BASE_CONVERTER_PATH,
                }
            elif name == "oracle-implementation":
                dependency = by_name.get(BASE_ORACLE_AUTHORITY)
                if dependency is None:
                    raise ValueError("37c-135 base oracle dependency is not pinned")
                item = {
                    **dependency,
                    "name": name,
                    "role": "independent-validator-implementation",
                    "path": BASE_ORACLE_PATH,
                }
            else:
                item = by_name.get(name)
                if item is None:
                    raise ValueError(f"37c-135 base oracle is missing {name!r}")
            records.append(MappingProxyType(dict(item)))
        if len(records) != len(expected_names):
            raise ValueError("37c-135 base-view authority inventory is not unique")
        original["authorities"] = tuple(records)

        converter_path = source_manifest.authority_path(BASE_CONVERTER_AUTHORITY)
        converter_bytes = converter_path.read_bytes()
        original["converter"] = {
            "id": base_converter.CONVERTER_ID,
            "version": base_converter.CONVERTER_VERSION,
            "callable": "_convert",
            "implementation_path": BASE_CONVERTER_PATH,
            "implementation_sha256": _sha(converter_bytes),
        }
        oracle_path = Path(base_oracle.__file__).resolve(strict=True)
        oracle_bytes = oracle_path.read_bytes()
        original["validator"] = {
            "id": base_oracle.ORACLE_ID,
            "version": base_oracle.ORACLE_VERSION,
            "callable": "_oracle",
            "implementation_path": BASE_ORACLE_PATH,
            "implementation_sha256": _sha(oracle_bytes),
            "import_closure_sha256": _base_oracle_closure_digest(base_oracle),
        }
        self.record = MappingProxyType(original)
        self.path = source_manifest.path
        self.repository_root = source_manifest.repository_root
        self.sha256 = source_manifest.sha256

    def verify(self) -> None:
        self._source_manifest.verify()

    def authority_path(self, name: str) -> Path:
        if name == "converter-implementation":
            return self._source_manifest.authority_path(BASE_CONVERTER_AUTHORITY)
        if name == "oracle-implementation":
            return self._source_manifest.authority_path(BASE_ORACLE_AUTHORITY)
        return self._source_manifest.authority_path(name)


class _BaseCandidateView:
    """Expose marker-free line text to the unchanged shared LIB-071 oracle."""

    def __init__(self, candidate: Any):
        self._candidate = candidate
        self.manifest = candidate.manifest
        self.sha256 = candidate.sha256

    def member_bytes(self, name: str) -> bytes:
        content = self._candidate.member_bytes(name)
        if name == "content.tei.xml":
            return _flatten_line_markup(content)
        return content


def _load_local_closure(source_manifest: Any, base_oracle: Any) -> str:
    local_path = Path(__file__).resolve(strict=True)
    base_path = Path(base_oracle.__file__).resolve(strict=True)
    base_authority = _authority(source_manifest, BASE_ORACLE_AUTHORITY)
    records = [
        {
            "path": LOCAL_ORACLE_PATH,
            "sha256": _sha(local_path.read_bytes()),
        },
        {
            "path": BASE_ORACLE_PATH,
            "sha256": _sha(base_path.read_bytes()),
        },
    ]
    if (
        base_authority.get("bytes") != len(base_path.read_bytes())
        or base_authority.get("sha256") != records[1]["sha256"]
    ):
        raise ValueError("37c-135 oracle closure has an unbound shared dependency")
    records.sort(key=lambda item: str(item["path"]))
    return _sha(_canonical(records))


def _manifest_bindings(source_manifest: Any) -> None:
    record = source_manifest.record
    if (
        record.get("ticket_id") != TICKET_ID
        or record.get("work_id") != WORK_ID
        or record.get("source_id") != SOURCE_ID
        or record.get("retained_source_path") != SOURCE_PATH
    ):
        raise ValueError("37c-135 independent oracle rejects an out-of-scope manifest")
    converter = record.get("converter")
    validator = record.get("validator")
    if not isinstance(converter, Mapping) or (
        converter.get("id") != "ocd-37c-135-drummond-source-underscore-to-tei"
        or converter.get("version") != "1"
        or converter.get("callable") != "_convert"
        or converter.get("implementation_path") != LOCAL_CONVERTER_PATH
    ):
        raise ValueError("37c-135 local converter binding is invalid")
    if not isinstance(validator, Mapping) or (
        validator.get("id") != ORACLE_ID
        or validator.get("version") != ORACLE_VERSION
        or validator.get("callable") != "_oracle"
        or validator.get("implementation_path") != LOCAL_ORACLE_PATH
    ):
        raise ValueError("37c-135 local oracle binding is invalid")
    base_converter = _authority(source_manifest, BASE_CONVERTER_AUTHORITY)
    base_oracle = _authority(source_manifest, BASE_ORACLE_AUTHORITY)
    if (
        base_converter.get("path") != BASE_CONVERTER_PATH
        or base_converter.get("role") != "base-converter-dependency"
        or base_oracle.get("path") != BASE_ORACLE_PATH
        or base_oracle.get("role") != "base-oracle-dependency"
    ):
        raise ValueError("37c-135 shared base implementation pins drifted")


def _verify_profile_and_policy(
    source_manifest: Any, spans: list[dict[str, object]], marker_events: Mapping[int, object]
) -> None:
    profile = _strict_json(
        source_manifest.authority_path("reconstruction-profile").read_bytes(),
        "37c-135 reconstruction profile",
    )
    works = profile.get("works")
    if not isinstance(works, list) or len(works) != 1 or not isinstance(works[0], dict):
        raise ValueError("37c-135 profile must bind exactly one work")
    marker_policy = works[0].get("source_underscore_markup")
    expected_policy = {
        "contract": MARKUP_CONTRACT,
        "delimiter": "_",
        "marker_count": 362,
        "span_count": 181,
        "interpretation": (
            "Balanced, nonempty Project Gutenberg underscore-delimited spans in this "
            "retained plain-text member are source-marked emphasis."
        ),
        "tei_mapping": (
            "Retain every literal underscore in source order as "
            "<c type=\"emphasis-delimiter\">; represent enclosed text with "
            "<hi rend=\"italic\" ana=\"#source-underscore\"> fragments. The first "
            "fragment carries xml:id and continuations carry corresp."
        ),
        "ambiguity_policy": (
            "Fail closed on unmatched, empty, nested, coincident, or blank-line-crossing "
            "underscore spans."
        ),
        "locator_contract": (
            "One-based Unicode codepoint line and column; span content retains exact "
            "source CRLF bytes after UTF-8 encoding."
        ),
    }
    if marker_policy != expected_policy or len(spans) != 181 or sum(
        len(items) for items in marker_events.values()
    ) != 362:
        raise ValueError("37c-135 bound source-markup policy or census drifted")

    policy = _strict_json(
        source_manifest.authority_path("validation-policy").read_bytes(),
        "37c-135 validation policy",
    )
    mutations = policy.get("rejected_mutations")
    if (
        not isinstance(mutations, list)
        or not _REQUIRED_MUTATIONS.issubset(set(mutations))
    ):
        raise ValueError("37c-135 validation policy omits marker-specific mutations")


def _verify_accountability(
    source_manifest: Any,
    candidate: Any,
    expected_spans: list[dict[str, object]],
) -> None:
    account_bytes = candidate.member_bytes("source-accountability.json")
    accountability = _strict_json(account_bytes, "37c-135 source accountability")
    schema_path = source_manifest.authority_path("source-accountability-schema")
    schema = _strict_json(schema_path.read_bytes(), "37c-135 accountability schema")
    errors = list(Draft202012Validator(schema).iter_errors(accountability))
    if errors:
        raise ValueError(
            f"37c-135 source-accountability schema rejected candidate: {errors[0].message}"
        )
    if account_bytes != _canonical(accountability):
        raise ValueError("37c-135 source accountability is not canonical JSON")
    work_rows = accountability.get("works")
    if not isinstance(work_rows, list) or len(work_rows) != 1:
        raise ValueError("37c-135 source accountability work inventory drifted")
    work = work_rows[0]
    if not isinstance(work, dict):
        raise ValueError("37c-135 source accountability work row is invalid")
    expected = {
        "contract": MARKUP_CONTRACT,
        "marker_count": 362,
        "span_count": len(expected_spans),
        "spans": expected_spans,
    }
    if work.get("source_underscore_markup") != expected:
        raise ValueError("37c-135 source underscore accountability locator drifted")


def _verify_actual_schema(source_manifest: Any, tei_bytes: bytes) -> None:
    xsd_path = source_manifest.authority_path("tei-p5-xsd")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
    schema_document = etree.parse(str(xsd_path), parser=parser)
    schema_root = schema_document.getroot()
    imports = {
        item.get("schemaLocation")
        for item in schema_root.findall("{http://www.w3.org/2001/XMLSchema}import")
    }
    if imports != {"tei_all_teix.xsd", "tei_all_xml.xsd"}:
        raise ValueError("37c-135 TEI schema dependency inventory drifted")
    for authority_name in ("tei-p5-xsd-teix", "tei-p5-xsd-xml"):
        authority = _authority(source_manifest, authority_name)
        imported = (
            xsd_path.parent / Path(str(authority["path"])).name
        ).resolve(strict=True)
        if imported != source_manifest.authority_path(authority_name):
            raise ValueError(f"37c-135 TEI schema import differs at {authority_name}")
    document = etree.fromstring(
        tei_bytes,
        parser=etree.XMLParser(resolve_entities=False, no_network=True, recover=False),
    )
    etree.XMLSchema(schema_document).assertValid(document)


def _closure_digest(source_manifest: Any, base_oracle: Any) -> str:
    return _load_local_closure(source_manifest, base_oracle)


def _oracle(source_manifest: Any, candidate: Any) -> Mapping[str, object]:
    """Verify source-marked emphasis plus the shared ticket's existing guarantees."""

    _manifest_bindings(source_manifest)
    base_oracle = _load_base_oracle(source_manifest)
    base_oracle._assert_raw_scope_before_read(
        source_manifest, {"source_path": SOURCE_PATH}
    )
    source_manifest.verify()
    candidate.verify_integrity()
    source_authority = _authority(source_manifest, "primary-source")
    source_bytes = source_manifest.authority_path("primary-source").read_bytes()
    if (
        source_authority.get("path") != SOURCE_PATH
        or source_authority.get("bytes") != SOURCE_BYTES
        or source_authority.get("sha256") != SOURCE_SHA256
        or len(source_bytes) != SOURCE_BYTES
        or _sha(source_bytes) != SOURCE_SHA256
    ):
        raise ValueError("37c-135 oracle requires the exact retained PG16739 member")
    rows = _oracle_source_rows(source_bytes)
    spans, marker_events = _oracle_marker_census(source_bytes, rows)
    if len(spans) != 181 or sum(len(items) for items in marker_events.values()) != 362:
        raise ValueError("37c-135 independent marker census differs from bound source")
    _verify_profile_and_policy(source_manifest, spans, marker_events)

    candidate_manifest = candidate.manifest
    converter_binding = source_manifest.record["converter"]
    if (
        candidate_manifest.get("contract") != "ocd-candidate-package-v1"
        or candidate_manifest.get("status") != "nonaccepted"
        or candidate_manifest.get("source_id") != SOURCE_ID
        or candidate_manifest.get("converter") != dict(converter_binding)
        or candidate_manifest.get("source_manifest", {}).get("path")
        != source_manifest.path.relative_to(source_manifest.repository_root).as_posix()
        or candidate_manifest.get("source_manifest", {}).get("sha256")
        != source_manifest.sha256
    ):
        raise ValueError("37c-135 candidate does not bind its local nonaccepted route")

    tei_bytes = candidate.member_bytes("content.tei.xml")
    _verify_marker_carriers(tei_bytes, rows, spans, marker_events)
    _verify_accountability(source_manifest, candidate, spans)
    _verify_actual_schema(source_manifest, tei_bytes)

    base_converter_authority = _authority(source_manifest, BASE_CONVERTER_AUTHORITY)
    base_converter_path = source_manifest.repository_root / BASE_CONVERTER_PATH
    base_converter_content = base_converter_path.read_bytes()
    if (
        base_converter_authority.get("bytes") != len(base_converter_content)
        or base_converter_authority.get("sha256") != _sha(base_converter_content)
    ):
        raise ValueError("37c-135 base converter changed after manifest verification")
    base_converter_spec = importlib.util.spec_from_file_location(
        f"_ocd_37c135_base_converter_view_{_sha(base_converter_content)}",
        base_converter_path,
    )
    if base_converter_spec is None or base_converter_spec.loader is None:
        raise ValueError("37c-135 base converter cannot be loaded by its oracle")
    base_converter_module = importlib.util.module_from_spec(base_converter_spec)
    base_converter_spec.loader.exec_module(base_converter_module)

    base_source_view = _BaseManifestView(
        source_manifest,
        base_converter_module,
        base_oracle,
    )
    base_candidate_view = _BaseCandidateView(candidate)
    base_result = base_oracle._oracle(base_source_view, base_candidate_view)
    if base_result.get("status") != "pass":
        raise ValueError("37c-135 shared LIB-071 base oracle rejected candidate")

    profile_authority = _authority(source_manifest, "reconstruction-profile")
    package_schema = source_manifest.record.get("package_schema")
    if not isinstance(package_schema, Mapping):
        raise ValueError("37c-135 package schema binding is invalid")
    xsd_authority = _authority(source_manifest, "tei-p5-xsd")
    policy_authority = _authority(source_manifest, "validation-policy")
    oracle_path = Path(__file__).resolve(strict=True)
    oracle_digest = _sha(oracle_path.read_bytes())
    closure_digest = _closure_digest(source_manifest, base_oracle)
    findings = [
        "the exact PG16739 source was scanned independently and all 181 balanced underscore spans were accounted for",
        "all literal underscore delimiters remain in source order and each marked fragment is represented as TEI italic emphasis",
        "all 17 spans crossing CRLF line endings retain their exact line and column locations and linked TEI fragments",
        "the independent shared LIB-071 oracle verified source blocks, headings, source-line order, attribution, unresolved scope, and exact source-byte reassembly",
        "the actual inline TEI validates against the manifest-bound TEI P5 schema",
        "candidate remains nonaccepted; human acceptance, rights clearance, and publication are not asserted",
    ]
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": oracle_digest,
        "import_closure_sha256": closure_digest,
        "runtime": (
            f"{platform.python_implementation()} {platform.python_version()} "
            f"({Path(sys.executable).resolve(strict=True)})"
        ),
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": profile_authority.get("sha256"),
        "package_schema_sha256": package_schema.get("sha256"),
        "source_sha256": _sha(source_bytes),
        "xsd_sha256": xsd_authority.get("sha256"),
        "policy_sha256": policy_authority.get("sha256"),
        "findings": findings,
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
