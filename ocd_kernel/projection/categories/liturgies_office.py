"""Opt-in source-bound projection of N18328's three complete offices.

The public units are the named offices, not inferred service steps. Ordered
native content retains every speech and label without inventing response links.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from typing import Any, Mapping

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection import native_content

NS = "{http://www.tei-c.org/ns/1.0}"
PROFILE = "ocd-liturgies-n18328-offices-v1"
MAPPING_VERSION = PROFILE
ASSEMBLER_VERSION = "ocd-liturgies-assembler-provisional-v1"
IDENTITY = {
    "work_id": "convicts-visitor",
    "textual_form_id": "convicts-visitor-tcp-retained",
    "edition_id": "convicts-visitor-tcp-electronic",
}
OFFICE_SPEECH_COUNTS = (23, 62, 30)
OFFICE_DIVISION_COUNTS = (4, 15, 18)
ROOT = Path(__file__).resolve().parents[3]
SCHEMA = ROOT / "schemas/v2/categories/liturgies.schema.json"
COMMON = ROOT / "schemas/v2/public-row.schema.json"
NATIVE = ROOT / "schemas/v2/native-content.schema.json"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _parts(root: ET.Element) -> tuple[list[ET.Element], list[ET.Element]]:
    if root.tag != NS + "TEI" or [node.tag for node in root] != [NS + "teiHeader", NS + "text"]:
        raise PipelineError("N18328 office profile requires one TEI header and text")
    text = root.find(NS + "text")
    if text is None or [node.tag for node in text] != [NS + "front", NS + "body"]:
        raise PipelineError("N18328 office profile requires front then body")
    front, body = list(text)
    if ([node.tag for node in front] != [NS + "div", NS + "div"]
            or [node.get("type") for node in front] != ["title_page", "preface"]):
        raise PipelineError("N18328 front matter differs from title page and preface")
    if len(body) != 1 or body[0].tag != NS + "div" or body[0].attrib != {"type": "text"}:
        raise PipelineError("N18328 body requires one source text division")
    outer = body[0]
    children = list(outer)
    if len(children) != 5 or [node.tag for node in children] != [NS + "pb", NS + "head", NS + "div", NS + "div", NS + "div"]:
        raise PipelineError("N18328 body requires opening page, heading, and three offices")
    if " ".join("".join(children[1].itertext()).split()) != "PENITENTIAL OFFICES.":
        raise PipelineError("N18328 shared heading differs")
    for node in (root, text, front, body, outer):
        if (node.text or "").strip() or any((child.tail or "").strip() for child in node):
            raise PipelineError("N18328 envelope has unassigned visible text")
    for index, office in enumerate(children[2:], 1):
        if office.attrib != {"n": str(index), "type": "office"}:
            raise PipelineError(f"N18328 office {index} identity differs")
        if not len(office) or office[0].tag != NS + "head":
            raise PipelineError(f"N18328 office {index} has no leading head")
        if sum(node.tag == NS + "sp" for node in office.iter()) != OFFICE_SPEECH_COUNTS[index - 1]:
            raise PipelineError(f"N18328 office {index} speech count differs")
        if sum(node.tag == NS + "div" for node in office.iter()) - 1 != OFFICE_DIVISION_COUNTS[index - 1]:
            raise PipelineError(f"N18328 office {index} division count differs")
        for speech in office.iter(NS + "sp"):
            if any(key in speech.attrib for key in ("corresp", "sameAs", "who")):
                raise PipelineError("N18328 speech links require a reviewed response mapping")
    return list(front), children


def project_document(
    tei_path: Path, *, identity: Mapping[str, str], language: str,
    representation_revision: str, edition_title: str,
    projection_profile: str | None,
    source_url: str | None = None, source_sha256: str | None = None,
    retained_sha256: str | None = None,
) -> dict[str, Any]:
    """Project exactly this declared office pattern with ElementTree."""
    if projection_profile != PROFILE or dict(identity) != IDENTITY or language != "en":
        raise PipelineError("N18328 office projection requires its exact profile, identity, and language")
    path = Path(tei_path)
    raw = path.read_bytes()
    if any(token in raw.upper() for token in (b"<!DOCTYPE", b"<!ENTITY", b"<!--")) or re.search(rb"<\?(?!xml(?:\s|\?>))", raw, re.I):
        raise PipelineError("N18328 office profile excludes declarations, comments, and instructions")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise PipelineError(f"invalid N18328 TEI: {exc}") from exc
    front, children = _parts(root)
    from ocd_kernel.projection.categories.liturgies import _source_binding_et, _validate_rows

    binding = _source_binding_et(root, source_url=source_url, source_sha256=source_sha256, retained_sha256=retained_sha256)
    rows: list[dict[str, Any]] = []
    anchors: list[dict[str, Any]] = []
    for number, office in enumerate(children[2:], 1):
        office_path = f"/TEI/text/body/div[1]/div[{number}]"
        office_id = _sha(office_path.encode("utf-8"))[:20]
        structure = [native_content.project_content(node) for node in (children[:2] if number == 1 else []) + [office]]
        readable = "\n\n".join(filter(None, (native_content.readable_content(node) for node in structure)))
        title = native_content.readable_content(native_content.project_content(office[0]))
        row = {
            **IDENTITY,
            "record_id": f"{IDENTITY['edition_id']}:liturgy-office:{office_id}",
            "sequence": number,
            "category": "liturgies",
            "language": language,
            "text": readable,
            "representation_revision": representation_revision,
            "provenance": {"edition_title": edition_title},
            "notes": [],
            "references": [],
            "row_profile": PROFILE,
            "office_id": office_id,
            "office_number": number,
            "office_title": title,
            "response_model": "ordered-source-speeches-without-explicit-links",
            "content_format": "ocd-native-content-v1",
            "structure": structure,
            "locator": {"kind": "liturgy-office", "text_part": "body", "outer_division": 1, "office": number},
        }
        if number == 1:
            row["front_matter"] = [native_content.project_content(node) for node in front]
        rows.append(row)
        anchors.append({"record_id": row["record_id"], "tei_path": office_path,
                        "text_sha256": _sha(readable.encode("utf-8")),
                        "structure_sha256": _sha(_canonical(structure)),
                        "speech_count": OFFICE_SPEECH_COUNTS[number - 1]})
    _validate_rows(rows)
    receipt = {
        "mapping_version": MAPPING_VERSION,
        "assembler_version": ASSEMBLER_VERSION,
        "projection_profile": PROFILE,
        "master_sha256": _sha(raw),
        "source_binding": binding,
        "policy_sha256": _sha(SCHEMA.read_bytes()),
        "common_schema_sha256": _sha(COMMON.read_bytes()),
        "native_schema_sha256": _sha(NATIVE.read_bytes()),
        "output_sha256": _sha(_canonical(rows)),
        "row_count": 3,
        "anchors": anchors,
        "shared_prelude": {"tei_paths": ["/TEI/text/body/div[1]/pb[1]", "/TEI/text/body/div[1]/head[1]"],
                           "attached_to": rows[0]["record_id"], "row_occurrences": 1},
        "front_matter": {"tei_paths": ["/TEI/text/front/div[1]", "/TEI/text/front/div[2]"],
                         "attached_to": rows[0]["record_id"], "row_occurrences": 1},
        "inventory": {"text_element_count": sum(1 for _ in root.find(NS + "text").iter()),
                      "represented_element_count": sum(1 for node in [*front, *children] for _ in node.iter()),
                      "speech_counts": list(OFFICE_SPEECH_COUNTS)},
        "warnings": ["No explicit source response pointers; speaker labels and source order are preserved."],
        "exclusions": [{"tei_path": "/TEI/teiHeader", "reason": "private-bibliographic-header"}],
        "unsupported": [],
        "independent_check": {"status": "pending"},
    }
    return {"rows": rows, "receipt": receipt, "mapping_version": MAPPING_VERSION,
            "assembler_version": ASSEMBLER_VERSION, "master_sha256": receipt["master_sha256"],
            "source_binding": binding, "anchors": anchors, "inventory": receipt["inventory"],
            "warnings": receipt["warnings"], "exclusions": receipt["exclusions"],
            "unsupported": [], "independent_check": receipt["independent_check"]}
