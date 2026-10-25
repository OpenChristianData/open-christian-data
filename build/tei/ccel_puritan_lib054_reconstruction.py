"""Deterministic retained-CCEL XML reconstruction for frozen LIB-054."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping
from urllib.parse import quote

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest


CONVERTER_ID = "ocd-ccel-puritan-lib054-retained-xml-to-tei"
CONVERTER_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
NON_ELEMENT_EVENT_RE = re.compile(
    r"(?P<doctype><!DOCTYPE\s[^[>]*(?:\[[^]]*\])?>)"
    r"|(?P<comment><!--[\s\S]*?-->)"
    r"|(?P<pi><\?(?!xml(?:\s|\?>))[\s\S]*?\?>)",
    flags=re.IGNORECASE,
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _prepared_xml(content: bytes) -> bytes:
    text = content.decode("utf-8")
    return re.sub(
        r"<!DOCTYPE\s[^[>]*(?:\[[^]]*\])?>",
        "",
        text,
        flags=re.DOTALL,
    ).encode("utf-8")


def _parse(content: bytes) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    try:
        return etree.fromstring(_prepared_xml(content), parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError("retained LIB-054 XML is not parseable") from exc


def _non_element_events(content: bytes, work_id: str) -> list[dict[str, object]]:
    """Return exact lexical non-element events in source document order."""
    text = content.decode("utf-8")
    events: list[dict[str, object]] = []
    for ordinal, match in enumerate(NON_ELEMENT_EVENT_RE.finditer(text), 1):
        kind = str(match.lastgroup)
        lexical = match.group(0)
        events.append(
            {
                "work_id": work_id,
                "source_event_ordinal": ordinal,
                "kind": kind,
                "lexical": lexical,
                "sha256": _sha(lexical.encode("utf-8")),
            }
        )
    return events


def _local(qname: str) -> str:
    return etree.QName(qname).localname


def _selector(element: etree._Element) -> str:
    parts: list[str] = []
    current = element
    while True:
        parent = current.getparent()
        qname = str(current.tag)
        if parent is None:
            parts.append(f"{qname}[1]")
            break
        peers = [
            child
            for child in parent
            if isinstance(child.tag, str) and child.tag == current.tag
        ]
        parts.append(f"{qname}[{peers.index(current) + 1}]")
        current = parent
    return "/" + "/".join(reversed(parts))


def _features(content: bytes, work_id: str) -> list[dict[str, object]]:
    root = _parse(content)
    elements = [node for node in root.iter() if isinstance(node.tag, str)]
    ordinals = {id(node): index for index, node in enumerate(elements, 1)}
    result: list[dict[str, object]] = []
    for index, element in enumerate(elements, 1):
        parent = element.getparent()
        siblings = (
            [child for child in parent if isinstance(child.tag, str)]
            if parent is not None
            else [element]
        )
        result.append(
            {
                "feature_id": f"{work_id}-feature-{index:05d}",
                "source_selector": _selector(element),
                "source_qname": str(element.tag),
                "source_attributes": [
                    {"qname": str(name), "value": value}
                    for name, value in element.attrib.items()
                ],
                "source_direct_text": element.text or "",
                "source_tail_text": element.tail or "",
                "source_parent_ordinal": ordinals[id(parent)]
                if parent is not None
                else None,
                "source_child_ordinal": siblings.index(element) + 1,
                "tei_xml_id": f"{work_id}-feature-{index:05d}",
                "work_id": work_id,
                "disposition": "represented",
                "tei_selector": f"#{work_id}-feature-{index:05d}",
            }
        )
    return result


def _metadata(content: bytes) -> list[dict[str, object]]:
    root = _parse(content)
    heads = [
        node
        for node in root.iter()
        if isinstance(node.tag, str) and _local(node.tag) == "ThML.head"
    ]
    if not heads:
        return []
    if len(heads) != 1:
        raise ValueError("LIB-054 retained XML has multiple ThML heads")
    return [
        {
            "qname": str(node.tag),
            "attributes": [
                {"qname": str(name), "value": value}
                for name, value in node.attrib.items()
            ],
            "text": node.text or "",
        }
        for node in heads[0].iter()
        if isinstance(node.tag, str)
    ]


def _element(
    name: str,
    attributes: Mapping[str, str] | None = None,
    text: str | None = None,
) -> etree._Element:
    node = etree.Element(f"{{{TEI_NS}}}{name}")
    for key, value in (attributes or {}).items():
        node.set(XML_ID if key == "xml:id" else key, value)
    node.text = text
    return node


def _work_tei(
    work: Mapping[str, object], content: bytes, features: list[dict[str, object]]
) -> etree._Element:
    work_id = str(work["work_id"])
    tei = _element("TEI", {"xml:id": work_id})
    header = _element("teiHeader")
    file_desc = _element("fileDesc")
    title_stmt = _element("titleStmt")
    title_stmt.append(_element("title", text=str(work["title"])))
    title_stmt.append(_element("author", text=str(work["author"])))
    resp = _element("respStmt")
    resp.append(_element("resp", text="Retained XML source provider"))
    resp.append(_element("name", text="Christian Classics Ethereal Library"))
    title_stmt.append(resp)
    file_desc.append(title_stmt)
    publication = _element("publicationStmt")
    publication.append(_element("publisher", text="Open Christian Data"))
    availability = _element("availability", {"status": "restricted"})
    availability.append(
        _element(
            "p",
            text="Nonaccepted technical reconstruction; rights review and publication authorization are absent.",
        )
    )
    publication.append(availability)
    file_desc.append(publication)
    source_desc = _element("sourceDesc")
    bibl = _element("bibl", {"type": "retained-witness"})
    bibl.append(_element("title", text=str(work["title"])))
    bibl.append(_element("author", text=str(work["author"])))
    bibl.append(
        _element("ref", {"target": str(work["source_url"])}, str(work["source_path"]))
    )
    bibl.append(_element("note", {"type": "source-sha256"}, _sha(content)))
    source_desc.append(bibl)
    file_desc.append(source_desc)
    header.append(file_desc)
    tei.append(header)
    text = _element("text")
    body = _element("body")
    division = _element(
        "div", {"xml:id": f"{work_id}-source", "type": "retained-source-member"}
    )
    division.append(_element("head", text=str(work["title"])))
    division.append(
        _element(
            "note",
            {
                "type": "exact-retained-source-bytes",
                "subtype": "base64",
                "n": _sha(content),
            },
            base64.b64encode(content).decode("ascii"),
        )
    )
    transcription = _element("div", {"type": "parsed-xml-feature-transcription"})
    for feature in features:
        block = _element(
            "ab",
            {
                "xml:id": str(feature["tei_xml_id"]),
                "type": "source-xml-element",
                "subtype": _local(str(feature["source_qname"])),
                "n": str(feature["source_child_ordinal"]),
                "corresp": "urn:source-xpath:"
                + quote(str(feature["source_selector"]), safe=""),
            },
        )
        block.append(
            _element("seg", {"type": "direct-text"}, str(feature["source_direct_text"]))
        )
        block.append(
            _element("seg", {"type": "tail-text"}, str(feature["source_tail_text"]))
        )
        transcription.append(block)
    division.append(transcription)
    body.append(division)
    text.append(body)
    tei.append(text)
    return tei


def _candidate_readme() -> bytes:
    return (
        "# LIB-054 source note\n\n"
        "This nonaccepted technical candidate embeds the exact bytes of ten retained CCEL XML witnesses and inventories every parsed XML element.\n\n"
        "The source files were sourced via CCEL.org. Do not sell CCEL files or derivatives of their formatting. The required data-side CCEL attribution notice is at `data/structured-text/README.md`.\n\n"
        "No print collation, human textual acceptance, rights acceptance, canonical IR acceptance, or publication authorization is claimed.\n"
    ).encode("utf-8")


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    source_manifest.verify()
    profile = _strict_json(
        source_manifest.authority_path("reconstruction-profile").read_bytes(),
        "LIB-054 profile",
    )
    works = profile.get("works")
    excluded = profile.get("excluded_members")
    if (
        not isinstance(works, list)
        or len(works) != 10
        or not isinstance(excluded, list)
        or len(excluded) != 5
    ):
        raise ValueError("LIB-054 profile cardinality mismatch")
    authorities = {
        str(item["name"]): item for item in source_manifest.record["authorities"]
    }
    contents: dict[str, bytes] = {}
    features: list[dict[str, object]] = []
    included: list[dict[str, object]] = []
    metadata: dict[str, list[dict[str, object]]] = {}
    non_element_events: list[dict[str, object]] = []
    for work in works:
        work_id = str(work["work_id"])
        authority = authorities.get(str(work["authority_name"]))
        if (
            authority is None
            or authority.get("role") != "primary-source"
            or authority.get("path") != work.get("source_path")
        ):
            raise ValueError(f"LIB-054 source binding drifted for {work_id}")
        content = source_manifest.authority_path(
            str(work["authority_name"])
        ).read_bytes()
        rows = _features(content, work_id)
        if (
            len(content) != work["bytes"]
            or _sha(content) != work["sha256"]
            or len(rows) != work["element_count"]
        ):
            raise ValueError(f"LIB-054 retained authority drifted for {work_id}")
        contents[work_id] = content
        features.extend(rows)
        non_element_events.extend(_non_element_events(content, work_id))
        metadata[work_id] = _metadata(content)
        included.append(
            {
                "work_id": work_id,
                "path": authority["path"],
                "bytes": len(content),
                "sha256": _sha(content),
                "element_count": len(rows),
                "disposition": "included",
            }
        )
    family = sorted(
        path.relative_to(source_manifest.repository_root).as_posix()
        for directory in profile["family_directories"]
        for path in (source_manifest.repository_root / str(directory)).glob("*.xml")
    )
    configured = sorted(
        [str(row["path"]) for row in included] + [str(row["path"]) for row in excluded]
    )
    if family != configured or len(family) != 15:
        raise ValueError("LIB-054 complete retained-family census drifted")
    census = {
        "included": included,
        "excluded": excluded,
        "counts": {"included": 10, "excluded": 5, "retained_family_total": 15},
    }
    comment_count = sum(row["kind"] == "comment" for row in non_element_events)
    processing_instruction_count = sum(
        row["kind"] == "pi" for row in non_element_events
    )
    processing_instruction_source_count = len(
        {row["work_id"] for row in non_element_events if row["kind"] == "pi"}
    )
    doctype_declaration_count = sum(
        row["kind"] == "doctype" for row in non_element_events
    )
    if (
        comment_count != 44
        or processing_instruction_count != 6
        or processing_instruction_source_count != 3
        or doctype_declaration_count != 8
    ):
        raise ValueError("LIB-054 non-element event census drifted")
    accountability = {
        "contract": "ocd-ccel-puritan-lib054-source-accountability-v1",
        "schema": "lib054.source-accountability.schema.json",
        "profile_id": profile["profile_id"],
        "source_member_count": 10,
        "excluded_member_count": 5,
        "retained_family_member_count": 15,
        "work_count": 10,
        "source_bytes": sum(len(item) for item in contents.values()),
        "feature_count": len(features),
        "qualified_attribute_count": sum(
            str(attr["qname"]).startswith("{")
            for row in features
            for attr in row["source_attributes"]
        ),
        "comment_count": comment_count,
        "processing_instruction_count": processing_instruction_count,
        "processing_instruction_source_count": processing_instruction_source_count,
        "doctype_declaration_count": doctype_declaration_count,
        "omitted_feature_count": 0,
        "duplicate_feature_count": 0,
        "member_census": census,
        "crosswalk": features,
        "non_element_events": non_element_events,
    }
    provenance = {
        "contract": "ocd-ccel-puritan-lib054-provenance-v1",
        "status": "nonaccepted",
        "publication": "not_ready",
        "ticket": "LIB-054",
        "work_ids": [work["work_id"] for work in works],
        "source_metadata": metadata,
        "rights": {
            "publication_authorized": False,
            "status": "human-review-required",
            "ccel_permission_authority": "ccel-permission",
            "source_attribution_authority": "source-local-readme",
            "data_attribution_deliverable": "data/structured-text/README.md",
        },
        "identity": {
            "status": "retained-witness-only",
            "print_collation": "not performed",
            "canonical_identity_decided": False,
        },
    }
    corpus = _element("teiCorpus", {"xml:id": "ccel-puritan-lib054-corpus"})
    header = _element("teiHeader")
    file_desc = _element("fileDesc")
    title_stmt = _element("titleStmt")
    title_stmt.append(
        _element("title", text="LIB-054: ten retained CCEL XML witnesses")
    )
    file_desc.append(title_stmt)
    publication = _element("publicationStmt")
    publication.append(_element("publisher", text="Open Christian Data"))
    availability = _element("availability", {"status": "restricted"})
    availability.append(
        _element("p", text="Nonaccepted candidate; not publication-ready.")
    )
    publication.append(availability)
    file_desc.append(publication)
    source_desc = _element("sourceDesc")
    source_desc.append(
        _element(
            "p",
            text="Ten exact retained CCEL XML authorities across ten frozen work identities.",
        )
    )
    file_desc.append(source_desc)
    header.append(file_desc)
    corpus.append(header)
    for work in works:
        work_id = str(work["work_id"])
        corpus.append(
            _work_tei(
                work,
                contents[work_id],
                [row for row in features if row["work_id"] == work_id],
            )
        )
    return {
        "content.tei.xml": etree.tostring(
            corpus, encoding="UTF-8", xml_declaration=True, pretty_print=False
        ),
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(
            _canonical(item) for item in profile["unresolved"]
        ),
        "README.source.md": _candidate_readme(),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()

__all__: tuple[str, ...] = ()
