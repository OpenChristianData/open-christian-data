"""Independent lxml correspondence check for the N18328 liturgy offices."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from lxml import etree

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.native_content_check import observe_content

TEI = "http://www.tei-c.org/ns/1.0"
NS = {"t": TEI}
PROFILE = "ocd-liturgies-n18328-offices-v1"
IDENTITY = {
    "work_id": "convicts-visitor",
    "textual_form_id": "convicts-visitor-tcp-retained",
    "edition_id": "convicts-visitor-tcp-electronic",
}
ROOT = Path(__file__).resolve().parents[3]
SCHEMA = ROOT / "schemas/v2/categories/liturgies.schema.json"
COMMON = ROOT / "schemas/v2/public-row.schema.json"
NATIVE = ROOT / "schemas/v2/native-content.schema.json"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _observe(node: etree._Element) -> tuple[dict[str, Any], str]:
    return observe_content(etree.tostring(node, with_tail=False))


def _expected(
    path: Path, *, identity: Mapping[str, str], language: str,
    representation_revision: str, edition_title: str,
    projection_profile: str | None, source_url: str | None,
    source_sha256: str | None, retained_sha256: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if projection_profile != PROFILE or dict(identity) != IDENTITY or language != "en":
        raise ValueError("N18328 office checker requires its exact profile, identity, and language")
    raw = path.read_bytes()
    if any(token in raw.upper() for token in (b"<!DOCTYPE", b"<!ENTITY", b"<!--")) or re.search(rb"<\?(?!xml(?:\s|\?>))", raw, re.I):
        raise ValueError("N18328 office checker excludes declarations, comments, and instructions")
    root = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
    if etree.QName(root).localname != "TEI" or etree.QName(root).namespace != TEI:
        raise ValueError("N18328 root differs")
    children = list(root)
    if [etree.QName(node).localname for node in children] != ["teiHeader", "text"]:
        raise ValueError("N18328 header/text envelope differs")
    text = children[1]
    if [etree.QName(node).localname for node in text] != ["front", "body"]:
        raise ValueError("N18328 text parts differ")
    front, body = list(text)
    front_children = list(front)
    if len(front_children) != 2 or [(etree.QName(node).localname, node.get("type")) for node in front_children] != [("div", "title_page"), ("div", "preface")]:
        raise ValueError("N18328 front matter differs")
    if len(body) != 1 or etree.QName(body[0]).localname != "div" or dict(body[0].attrib) != {"type": "text"}:
        raise ValueError("N18328 outer body division differs")
    outer = body[0]
    units = list(outer)
    if [(etree.QName(node).localname, node.get("type")) for node in units] != [("pb", None), ("head", None), ("div", "office"), ("div", "office"), ("div", "office")]:
        raise ValueError("N18328 opening and office sequence differs")
    if " ".join("".join(units[1].itertext()).split()) != "PENITENTIAL OFFICES.":
        raise ValueError("N18328 shared head differs")
    for container in (root, text, front, body, outer):
        if (container.text or "").strip() or any((child.tail or "").strip() for child in container):
            raise ValueError("N18328 envelope has unassigned visible text")
    counts = (23, 62, 30)
    divisions = (4, 15, 18)
    for index, office in enumerate(units[2:], 1):
        if dict(office.attrib) != {"n": str(index), "type": "office"}:
            raise ValueError(f"N18328 office {index} identity differs")
        if len(office) == 0 or etree.QName(office[0]).localname != "head":
            raise ValueError(f"N18328 office {index} heading differs")
        speeches = office.xpath(".//t:sp", namespaces=NS)
        if len(speeches) != counts[index - 1] or len(office.xpath(".//t:div", namespaces=NS)) != divisions[index - 1]:
            raise ValueError(f"N18328 office {index} source shape differs")
        if any(any(attribute in speech.attrib for attribute in ("corresp", "sameAs", "who")) for speech in speeches):
            raise ValueError("N18328 response pointers require a reviewed mapping")
    from ocd_kernel.projection.categories.liturgies import _source_binding_lxml

    binding = _source_binding_lxml(root, source_url=source_url, source_sha256=source_sha256, retained_sha256=retained_sha256)
    rows = []
    anchors = []
    for index, office in enumerate(units[2:], 1):
        path_label = f"/TEI/text/body/div[1]/div[{index}]"
        token = _sha(path_label.encode("utf-8"))[:20]
        observed = [_observe(node) for node in (units[:2] if index == 1 else []) + [office]]
        structure = [item[0] for item in observed]
        text_value = "\n\n".join(item[1] for item in observed if item[1])
        title = _observe(office[0])[1]
        row = {
            **IDENTITY,
            "record_id": f"{IDENTITY['edition_id']}:liturgy-office:{token}",
            "sequence": index,
            "category": "liturgies",
            "language": "en",
            "text": text_value,
            "representation_revision": representation_revision,
            "provenance": {"edition_title": edition_title},
            "notes": [],
            "references": [],
            "row_profile": PROFILE,
            "office_id": token,
            "office_number": index,
            "office_title": title,
            "response_model": "ordered-source-speeches-without-explicit-links",
            "content_format": "ocd-native-content-v1",
            "structure": structure,
            "locator": {"kind": "liturgy-office", "text_part": "body", "outer_division": 1, "office": index},
        }
        if index == 1:
            row["front_matter"] = [_observe(node)[0] for node in front_children]
        rows.append(row)
        anchors.append({"record_id": row["record_id"], "tei_path": path_label,
                        "text_sha256": _sha(text_value.encode("utf-8")),
                        "structure_sha256": _sha(_json(structure)), "speech_count": counts[index - 1]})
    receipt = {
        "mapping_version": PROFILE,
        "assembler_version": "ocd-liturgies-assembler-provisional-v1",
        "projection_profile": PROFILE,
        "master_sha256": _sha(raw),
        "source_binding": binding,
        "policy_sha256": _sha(SCHEMA.read_bytes()),
        "common_schema_sha256": _sha(COMMON.read_bytes()),
        "native_schema_sha256": _sha(NATIVE.read_bytes()),
        "output_sha256": _sha(_json(rows)),
        "row_count": 3,
        "anchors": anchors,
        "shared_prelude": {"tei_paths": ["/TEI/text/body/div[1]/pb[1]", "/TEI/text/body/div[1]/head[1]"],
                           "attached_to": rows[0]["record_id"], "row_occurrences": 1},
        "front_matter": {"tei_paths": ["/TEI/text/front/div[1]", "/TEI/text/front/div[2]"],
                         "attached_to": rows[0]["record_id"], "row_occurrences": 1},
        "inventory": {"text_element_count": len(list(text.iter())),
                      "represented_element_count": sum(len(list(node.iter())) for node in [*front_children, *units]),
                      "speech_counts": list(counts)},
        "warnings": ["No explicit source response pointers; speaker labels and source order are preserved."],
        "exclusions": [{"tei_path": "/TEI/teiHeader", "reason": "private-bibliographic-header"}],
        "unsupported": [],
        "independent_check": {"status": "pending"},
    }
    return rows, receipt


def verify_document(
    tei_path: Path, rows: list[dict[str, Any]], receipt: Mapping[str, Any] | None = None,
    *, identity: Mapping[str, str], language: str, representation_revision: str,
    edition_title: str, projection_profile: str | None,
    source_url: str | None = None, source_sha256: str | None = None,
    retained_sha256: str | None = None,
) -> list[str]:
    """Recompute the partition, content, and receipt without the producer."""
    try:
        expected_rows, expected_receipt = _expected(
            Path(tei_path), identity=identity, language=language,
            representation_revision=representation_revision, edition_title=edition_title,
            projection_profile=projection_profile, source_url=source_url,
            source_sha256=source_sha256, retained_sha256=retained_sha256,
        )
        errors = []
        if rows != expected_rows:
            errors.append("N18328 source correspondence: office rows, prelude, roles, or order differ")
        if receipt is None or not isinstance(receipt, Mapping) or dict(receipt) != expected_receipt:
            errors.append("N18328 source correspondence receipt differs")
        from ocd_kernel.projection.categories.liturgies import _validator

        validator = _validator()
        for index, row in enumerate(rows if isinstance(rows, list) else [], 1):
            for error in validator.iter_errors(row):
                errors.append(f"N18328 schema row {index}: {error.message}")
        return errors
    except (OSError, ValueError, TypeError, KeyError, PipelineError, etree.XMLSyntaxError) as exc:
        return [str(exc)]
