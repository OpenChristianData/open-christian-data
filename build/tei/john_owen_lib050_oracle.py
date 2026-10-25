"""Producer-independent retained-source oracle for LIB-050."""

from __future__ import annotations

import ast
import base64
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import platform
import re
import sys
from typing import Any, Mapping
from urllib.parse import quote

import jsonschema
from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-john-owen-lib050-retained-xml-oracle"
ORACLE_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
MEMBERS = {
    "README.source.md",
    "content.tei.xml",
    "manifest.json",
    "provenance.json",
    "source-accountability.json",
    "unresolved.jsonl",
}
TEI = {"tei": TEI_NS}
READABLE_TAGS = {
    "a": "ref",
    "argument": "p",
    "attr": "ab",
    "blockquote": "quote",
    "br": "lb",
    "cite": "quote",
    "date": "date",
    "div": "div",
    "div1": "div",
    "div2": "div",
    "div3": "div",
    "div4": "div",
    "em": "hi",
    "foreign": "foreign",
    "h1": "ab",
    "h2": "ab",
    "h3": "ab",
    "h4": "ab",
    "hr": "milestone",
    "i": "hi",
    "img": "graphic",
    "insertIndex": "milestone",
    "l": "l",
    "li": "item",
    "name": "name",
    "note": "note",
    "p": "p",
    "pb": "pb",
    "scripCom": "note",
    "scripContext": "ab",
    "scripRef": "ref",
    "span": "seg",
    "sup": "hi",
    "table": "table",
    "td": "cell",
    "th": "cell",
    "tr": "row",
    "ul": "list",
    "verse": "lg",
}

_LITERAL_ONLY_PASSAGES = {
    "xix-p7.3": "Ps. xxii. 8, [margin,] xxxvii. 5",
    "xxii-p0.2": "Chap. iii. [iv. v. x.",
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _strict_json(content: bytes, label: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate key in {label}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(content.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {label}") from exc


def _parse_source(content: bytes) -> etree._ElementTree:
    try:
        return etree.parse(
            io.BytesIO(content),
            etree.XMLParser(
                resolve_entities=False,
                load_dtd=False,
                no_network=True,
                remove_comments=False,
                remove_pis=False,
                huge_tree=True,
            ),
        )
    except etree.XMLSyntaxError as exc:
        raise ValueError("LIB-050 retained XML parse failure") from exc


def _kind(node: etree._Element) -> str:
    if node.tag is etree.Comment:
        return "comment"
    if node.tag is etree.PI:
        return "processing-instruction"
    if isinstance(node.tag, str):
        return "element"
    raise ValueError("unsupported retained XML node")


def _document_nodes(tree: etree._ElementTree) -> list[tuple[str, etree._Element]]:
    root = tree.getroot()
    before = []
    node = root.getprevious()
    while node is not None:
        before.append(node)
        node = node.getprevious()
    after = []
    node = root.getnext()
    while node is not None:
        after.append(node)
        node = node.getnext()
    result = [("pre-root", item) for item in reversed(before)]

    def walk(current: etree._Element) -> None:
        result.append(("tree", current))
        for child in current:
            walk(child)

    walk(root)
    result.extend(("post-root", item) for item in after)
    return result


def _records(tree: etree._ElementTree, member_id: str) -> tuple[dict[str, Any], ...]:
    nodes = _document_nodes(tree)
    ordinals = {id(node): ordinal for ordinal, (_scope, node) in enumerate(nodes, 1)}
    result = []
    for ordinal, (scope, node) in enumerate(nodes, 1):
        parent = node.getparent()
        siblings = list(parent) if parent is not None else [node]
        kind = _kind(node)
        record = {
            "feature_id": f"{member_id}-node-{ordinal:06d}",
            "ordinal": ordinal,
            "scope": scope,
            "kind": kind,
            "qname": str(node.tag) if kind == "element" else None,
            "pi_target": node.target if kind == "processing-instruction" else None,
            "attributes": (
                [[str(name), value] for name, value in node.attrib.items()]
                if kind == "element"
                else []
            ),
            "namespace_declarations": (
                [["" if name is None else name, value] for name, value in node.nsmap.items()]
                if kind == "element"
                else []
            ),
            "text": node.text or "",
            "tail": node.tail or "",
            "parent_ordinal": ordinals.get(id(parent)),
            "sibling_ordinal": siblings.index(node) + 1,
        }
        record["payload_sha256"] = _sha(_canonical(record))
        result.append(record)
    return tuple(result)


def _first(tree: etree._ElementTree, expression: str) -> str:
    return "".join(str(value) for value in tree.xpath(expression)).strip()


def _metadata(tree: etree._ElementTree) -> dict[str, Any]:
    root = tree.getroot()
    comments = [node.text or "" for _scope, node in _document_nodes(tree) if _kind(node) == "comment"]
    return {
        "title": _first(tree, "/ThML/ThML.head/electronicEdInfo/DC/DC.Title[not(@sub)]/text()"),
        "creator": _first(tree, "/ThML/ThML.head/electronicEdInfo/DC/DC.Creator[@sub='Author'][1]/text()"),
        "electronic_publisher": _first(tree, "/ThML/ThML.head/electronicEdInfo/DC/DC.Publisher/text()"),
        "print_source": _first(tree, "/ThML/ThML.head/printSourceInfo/published/text()"),
        "rights": _first(tree, "/ThML/ThML.head/electronicEdInfo/DC/DC.Rights/text()"),
        "status": _first(tree, "/ThML/ThML.head/electronicEdInfo/status/text()"),
        "editorial_comments": _first(tree, "/ThML/ThML.head/electronicEdInfo/editorialComments/text()"),
        "source_url": _first(tree, "/ThML/ThML.head/electronicEdInfo/DC/DC.Identifier[@scheme='URL']/text()"),
        "xml_version": tree.docinfo.xml_version,
        "encoding": tree.docinfo.encoding,
        "doctype": tree.docinfo.doctype,
        "root_qname": str(root.tag),
        "root_attributes": [[str(name), value] for name, value in root.attrib.items()],
        "root_namespace_declarations": [["" if name is None else name, value] for name, value in root.nsmap.items()],
        "ccel_copyright_comment_present": any("Copyright Christian Classics Ethereal Library" in text for text in comments),
    }


def _expected_evidence(
    source_manifest: SourceManifest,
    profile: Mapping[str, Any],
    prepared: list[tuple[Mapping[str, Any], bytes, etree._ElementTree, tuple[dict[str, Any], ...]]],
) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    works = []
    for work, content, tree, records in prepared:
        works.append(
            {
                "work_id": work["work_id"],
                "authority_name": work["authority_name"],
                "path": work["path"],
                "bytes": len(content),
                "sha256": _sha(content),
                "node_count": len(records),
                "node_kind_counts": {kind: sum(row["kind"] == kind for row in records) for kind in ("element", "comment", "processing-instruction")},
                "attribute_count": sum(len(row["attributes"]) for row in records),
                "text_character_count": sum(len(row["text"]) for row in records),
                "tail_character_count": sum(len(row["tail"]) for row in records),
                "metadata": _metadata(tree),
                "omitted_node_count": 0,
                "duplicate_node_count": 0,
                "invented_node_count": 0,
            }
        )
    accountability = {
        "contract": "ocd-john-owen-lib050-source-accountability-v1",
        "profile_id": profile["profile_id"],
        "assigned_work_count": 10,
        "included_member_count": 10,
        "adjacent_member_count": 22,
        "total_node_count": sum(row["node_count"] for row in works),
        "works": works,
        "adjacent_retained_member_accounting": profile["adjacent_retained_member_accounting"],
    }
    provenance = {
        "contract": "ocd-john-owen-lib050-provenance-v1",
        "status": "nonaccepted",
        "publication_state": "not_ready",
        "source_id": source_manifest.record["source_id"],
        "source_credit": "sourced via CCEL.org",
        "rights": {
            "underlying_historic_works": "public-domain",
            "ccel_file_and_formatting": "restricted-human-review-required",
            "ages_electronic_base_assertion": "unresolved-for-eight-works",
            "publication_ready": False,
        },
        "works": [
            {
                "work_id": row["work_id"],
                "title": row["metadata"]["title"],
                "source_path": row["path"],
                "source_sha256": row["sha256"],
                "source_bytes": row["bytes"],
                "electronic_publisher": row["metadata"]["electronic_publisher"],
                "print_source": row["metadata"]["print_source"],
                "editorial_comments": row["metadata"]["editorial_comments"],
                "source_status": row["metadata"]["status"],
                "source_rights_text": row["metadata"]["rights"],
                "source_url": row["metadata"]["source_url"],
                "human_review": "required",
                "accepted_ir": "not_accepted",
                "publication": "not_ready",
            }
            for row in works
        ],
        "canonical_data_written": False,
        "canonical_ir_written": False,
    }
    ages_ids = [row["work_id"] for row in works if "AGES Software" in row["metadata"]["editorial_comments"]]
    unresolved = [
        {
            "id": "lib050-ages-electronic-base-rights",
            "scope": ages_ids,
            "status": "unresolved",
            "question": "What rights attach to the AGES-derived electronic base text?",
            "evidence": "Eight retained headers assert an AGES Software copyright while DC.Rights is empty.",
            "consequence": "Keep the candidate nonaccepted, restricted, and not publication-ready.",
        },
        {
            "id": "lib050-edition-and-proofreading",
            "scope": [row["work_id"] for row in works],
            "status": "unresolved",
            "question": "Has each retained electronic witness been accepted as the intended edition and text?",
            "evidence": "Retained CCEL headers identify differing Banner reprints and mixed proof-read states.",
            "consequence": "Human edition and textual review remains required.",
        },
        {
            "id": "lib050-poema-map-hole",
            "scope": ["raw/ccel/owen/poema.xml"],
            "status": "unresolved",
            "question": "Should the retained Latin Poema witness receive a future work identity?",
            "evidence": "poema.xml is retained but absent from the frozen WorkCatalog and ticket maps.",
            "consequence": "Exclude it from LIB-050 and surface the map hole to LIB-090 without changing maps here.",
        },
    ]
    return accountability, provenance, b"".join(_canonical(row) for row in unresolved)


def _expected_header(metadata: Mapping[str, Any]) -> etree._Element:
    def el(name: str, attrs: Mapping[str, str] | None = None, text: str | None = None) -> etree._Element:
        node = etree.Element(f"{{{TEI_NS}}}{name}")
        for key, value in (attrs or {}).items():
            node.set(key, value)
        node.text = text
        return node

    header = el("teiHeader")
    file_desc = el("fileDesc")
    title_stmt = el("titleStmt")
    title_stmt.append(el("title", text=str(metadata["title"])))
    title_stmt.append(el("author", text=str(metadata["creator"])))
    resp = el("respStmt")
    resp.append(el("resp", text="Retained electronic edition and ThML markup"))
    resp.append(el("name", text=str(metadata["electronic_publisher"])))
    title_stmt.append(resp)
    file_desc.append(title_stmt)
    publication = el("publicationStmt")
    publication.append(el("publisher", text="Open Christian Data"))
    availability = el("availability", {"status": "restricted"})
    availability.append(el("p", text="Nonaccepted technical reconstruction; human rights, edition, and textual review required; publication not ready."))
    publication.append(availability)
    file_desc.append(publication)
    source_desc = el("sourceDesc")
    bibl = el("bibl", {"type": "retained-electronic-witness"})
    bibl.append(el("title", text=str(metadata["title"])))
    bibl.append(el("author", text=str(metadata["creator"])))
    bibl.append(el("publisher", text=str(metadata["electronic_publisher"])))
    bibl.append(el("note", {"type": "print-source"}, str(metadata["print_source"])))
    bibl.append(el("note", {"type": "rights"}, str(metadata["rights"])))
    bibl.append(el("note", {"type": "editorial-comments"}, str(metadata["editorial_comments"])))
    bibl.append(el("idno", {"type": "CCEL-path"}, str(metadata["source_url"])))
    source_desc.append(bibl)
    file_desc.append(source_desc)
    header.append(file_desc)
    return header


def _expected_corpus_header() -> etree._Element:
    def el(name: str, attrs: Mapping[str, str] | None = None, text: str | None = None) -> etree._Element:
        node = etree.Element(f"{{{TEI_NS}}}{name}")
        for key, value in (attrs or {}).items():
            node.set(key, value)
        node.text = text
        return node

    header = el("teiHeader")
    file_desc = el("fileDesc")
    title_stmt = el("titleStmt")
    title_stmt.append(el("title", text="LIB-050 John Owen retained-source cohort"))
    file_desc.append(title_stmt)
    publication = el("publicationStmt")
    publication.append(el("publisher", text="Open Christian Data"))
    availability = el("availability", {"status": "restricted"})
    availability.append(el("p", text="Nonaccepted technical reconstruction; publication not ready."))
    publication.append(availability)
    file_desc.append(publication)
    source_desc = el("sourceDesc")
    source_desc.append(el("p", text="Ten exact retained CCEL ThML XML authorities; sourced via CCEL.org."))
    file_desc.append(source_desc)
    header.append(file_desc)
    return header


def _normalized_visible_text(element: etree._Element) -> str:
    return " ".join("".join(element.itertext()).split())


def _source_subtype(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    return normalized.lower() or "unspecified"


def _native_source_id(work_id: str, source_id: str) -> str:
    return f"{work_id}--{source_id}"


def _rewrite_local_fragment(value: str, work_id: str) -> str:
    prefix, separator, fragment = value.partition("#")
    if not separator:
        return value
    return f"{prefix}#{_native_source_id(work_id, fragment)}"


def _expected_source_attribute_analysis(source_node: etree._Element) -> str:
    return " ".join(
        f"urn:ocd:thml-attribute:{quote(str(name), safe='')}:{quote(value, safe='')}"
        for name, value in source_node.attrib.items()
    )


def _expected_span_renditions(source_node: etree._Element) -> list[str]:
    renditions: list[str] = []
    source_class = source_node.get("class")
    if source_class:
        renditions.append(f"class-{_source_subtype(str(source_class))}")
    style = source_node.get("style")
    if style:
        normalized_style = re.sub(r"\s+", "", str(style).casefold())
        if "font-variant:small-caps" in normalized_style:
            renditions.append("small-caps")
        elif "font-style:italic" in normalized_style:
            renditions.append("italic")
        elif "font-weight:bold" in normalized_style:
            renditions.append("bold")
        else:
            renditions.append(f"style-{_source_subtype(str(style))}")
    return renditions


def _expected_readable_attributes(
    source_node: etree._Element,
    feature_id: str,
    record_by_node: Mapping[int, Mapping[str, Any]],
    work_id: str,
) -> dict[str, str] | None:
    kind = _kind(source_node)
    if kind != "element":
        return {
            "unit": (
                "source-comment"
                if kind == "comment"
                else "source-processing-instruction"
            ),
            "corresp": f"#{feature_id}",
        }
    source_name = str(source_node.tag)
    if source_name in {"tbody", "thead"}:
        return None
    if source_name == "ThML.body":
        expected = {"type": "readable-transcription", "corresp": f"#{feature_id}"}
        if source_node.get("id"):
            expected[XML_ID] = _native_source_id(work_id, str(source_node.get("id")))
        if source_node.get(XML_SPACE):
            expected[XML_SPACE] = str(source_node.get(XML_SPACE))
        analysis = _expected_source_attribute_analysis(source_node)
        if analysis:
            expected["ana"] = analysis
        return expected
    expected = {"corresp": f"#{feature_id}"}
    if source_node.get("id"):
        expected[XML_ID] = _native_source_id(work_id, str(source_node.get("id")))
    if source_name in {"div", "div1", "div2", "div3", "div4"}:
        expected.update(
            {
                "type": "source-division",
                "subtype": _source_subtype(source_node.get("type") or source_name),
            }
        )
    elif source_name == "argument":
        expected["rend"] = "argument"
    elif source_name == "attr":
        expected["type"] = "source-attribute-text"
    elif source_name == "blockquote":
        expected["type"] = "source-blockquote"
    elif source_name in {"em", "i"}:
        expected["rend"] = "italic"
    elif source_name == "sup":
        expected["rend"] = "superscript"
    elif source_name == "hr":
        expected["unit"] = "horizontal-rule"
    elif source_name == "insertIndex":
        expected["unit"] = "source-insert-index"
        if source_type := source_node.get("type"):
            expected["subtype"] = _source_subtype(str(source_type))
    elif source_name == "note":
        expected["type"] = "source-note"
        for name in ("place", "n", "resp"):
            value = source_node.get(name)
            if value:
                expected[name] = str(value)
        anchored = source_node.get("anchored")
        if anchored:
            normalized = anchored.casefold()
            if normalized in {"yes", "true", "1"}:
                expected["anchored"] = "true"
            elif normalized in {"no", "false", "0"}:
                expected["anchored"] = "false"
            else:
                raise ValueError(
                    f"unsupported retained LIB-050 note anchored value: {anchored}"
                )
    elif source_name == "scripCom":
        expected["type"] = "scripture-comment"
        source_type = source_node.get("type")
        if source_type:
            expected["subtype"] = _source_subtype(str(source_type))
        passage = source_node.get("passage")
        if passage:
            expected["n"] = str(passage)
        reference = source_node.get("osisRef") or passage
        if reference:
            expected["target"] = f"urn:osis:{str(reference).replace(' ', '%20')}"
    elif source_name == "scripContext":
        expected["type"] = "scripture-context"
        version = source_node.get("version")
        if version:
            expected["subtype"] = _source_subtype(str(version))
            expected["n"] = str(version)
    elif source_name == "scripRef":
        expected["type"] = "scripture"
        osis_ref = source_node.get("osisRef")
        passage = source_node.get("passage")
        if osis_ref:
            expected["target"] = f"urn:osis:{str(osis_ref).replace(' ', '%20')}"
        elif passage and _LITERAL_ONLY_PASSAGES.get(source_node.get("id")) == passage:
            expected["n"] = str(passage)
        elif passage:
            expected["target"] = f"urn:osis:{str(passage).replace(' ', '%20')}"
    elif source_name == "a" and source_node.get("href"):
        expected["target"] = _rewrite_local_fragment(
            str(source_node.get("href")), work_id
        )
    elif source_name == "span":
        expected["type"] = "source-span"
        source_class = source_node.get("class")
        if source_class:
            expected["subtype"] = f"class-{_source_subtype(str(source_class))}"
            if source_node.get("lang") is None:
                if source_class.casefold() == "greek":
                    expected[XML_LANG] = "grc"
                elif source_class.casefold() == "hebrew":
                    expected[XML_LANG] = "he"
        renditions = _expected_span_renditions(source_node)
        if renditions:
            expected["rend"] = " ".join(renditions)
    elif source_name in {"h1", "h2", "h3", "h4"}:
        expected["type"] = "source-heading"
        expected["subtype"] = source_name
    elif source_name == "verse":
        expected["type"] = _source_subtype(source_node.get("type") or "verse")
    elif source_name == "date":
        value = source_node.get("value")
        if value:
            if re.fullmatch(r"-?\d{4}(?:-\d{2}(?:-\d{2})?)?", value):
                expected["when"] = str(value)
            else:
                expected["n"] = str(value)
    elif source_name == "img":
        if source_node.get("src"):
            expected["url"] = str(source_node.get("src"))
        if source_node.get("alt"):
            expected["n"] = str(source_node.get("alt"))
        if source_node.get("width"):
            expected["width"] = str(source_node.get("width"))
    elif source_name == "th":
        expected["role"] = "label"
        if source_node.get("colspan"):
            expected["cols"] = str(source_node.get("colspan"))
        if source_node.get("rowspan"):
            expected["rows"] = str(source_node.get("rowspan"))
    if source_name == "p":
        alignment = source_node.get("align")
        style = source_node.get("style")
        if alignment:
            expected["rend"] = f"align-{_source_subtype(str(alignment))}"
        elif style:
            match = re.fullmatch(r"\s*text-align\s*:\s*([^;]+)\s*;?\s*", style)
            expected["rend"] = (
                f"align-{_source_subtype(match.group(1))}"
                if match
                else f"style-{_source_subtype(str(style))}"
            )
    if source_name in {"cite", "name"} and source_node.get("title"):
        expected["n"] = str(source_node.get("title"))
    if source_name == "pb" and source_node.get("n"):
        expected["n"] = str(source_node.get("n"))
    if source_node.get("lang"):
        expected[XML_LANG] = str(source_node.get("lang"))
    source_analysis = _expected_source_attribute_analysis(source_node)
    if source_name == "table":
        wrapper_analysis: list[str] = []
        for child in source_node:
            if isinstance(child.tag, str) and child.tag in {"tbody", "thead"}:
                wrapper_analysis.append(f"#{record_by_node[id(child)]['feature_id']}")
                analysis = _expected_source_attribute_analysis(child)
                if analysis:
                    wrapper_analysis.append(analysis)
        source_analysis = " ".join(
            value for value in (source_analysis, *wrapper_analysis) if value
        )
    if source_analysis:
        expected["ana"] = source_analysis
    return expected


def _verify_readable_transcription(
    source_tree: etree._ElementTree,
    records: tuple[dict[str, Any], ...],
    division: etree._Element,
    work_id: str,
) -> None:
    readable = division.xpath(
        "./tei:div[@type='readable-transcription']", namespaces=TEI
    )
    source_bodies = source_tree.xpath("/ThML/ThML.body")
    if len(readable) != 1 or len(source_bodies) != 1:
        raise ValueError("LIB-050 readable transcription boundary drift")
    source_body = source_bodies[0]
    transcription = readable[0]
    if _normalized_visible_text(transcription) != _normalized_visible_text(source_body):
        raise ValueError("LIB-050 readable wording, order, or mixed-content drift")

    document_nodes = [node for _scope, node in _document_nodes(source_tree)]
    if len(document_nodes) != len(records):
        raise ValueError("LIB-050 oracle source-node census drift")
    record_by_node = {
        id(node): record
        for node, record in zip(document_nodes, records, strict=True)
    }
    source_body_nodes = list(source_body.iter())
    expected_ids = {
        str(record_by_node[id(node)]["feature_id"]) for node in source_body_nodes
    }
    observed: dict[str, list[etree._Element]] = {}
    for node in transcription.iter():
        for attribute in ("corresp", "ana"):
            for pointer in (node.get(attribute) or "").split():
                if pointer.startswith("#"):
                    observed.setdefault(pointer[1:], []).append(node)
    duplicate_ids = sorted(key for key, nodes in observed.items() if len(nodes) != 1)
    if set(observed) != expected_ids or duplicate_ids:
        missing_ids = sorted(expected_ids - set(observed))
        invented_ids = sorted(set(observed) - expected_ids)
        raise ValueError(
            "LIB-050 readable carrier target omission, duplication, or invention: "
            f"missing={missing_ids[:3]!r}, invented={invented_ids[:3]!r}, "
            f"duplicated={duplicate_ids[:3]!r}"
        )

    source_ids = {
        str(node.get("id")): node
        for node in source_body_nodes
        if _kind(node) == "element"
        and node.get("id")
        and str(node.tag) not in {"tbody", "thead"}
    }
    expected_native_ids = {
        _native_source_id(work_id, source_id) for source_id in source_ids
    }
    observed_native_ids: dict[str, list[etree._Element]] = {}
    for target in transcription.iter():
        native_id = target.get(XML_ID)
        if native_id:
            observed_native_ids.setdefault(native_id, []).append(target)
    duplicate_native_ids = sorted(
        key for key, nodes in observed_native_ids.items() if len(nodes) != 1
    )
    if set(observed_native_ids) != expected_native_ids or duplicate_native_ids:
        missing_ids = sorted(expected_native_ids - set(observed_native_ids))
        invented_ids = sorted(set(observed_native_ids) - expected_native_ids)
        raise ValueError(
            "LIB-050 native source ID target omission, duplication, or invention: "
            f"missing={missing_ids[:3]!r}, invented={invented_ids[:3]!r}, "
            f"duplicated={duplicate_native_ids[:3]!r}"
        )

    for source_node in source_body_nodes:
        if _kind(source_node) != "element" or not source_node.get("href"):
            continue
        href = str(source_node.get("href"))
        prefix, separator, fragment = href.partition("#")
        if not separator or fragment not in source_ids:
            raise ValueError("LIB-050 source href fragment has no retained target")
        record = record_by_node[id(source_node)]
        target = observed[str(record["feature_id"])][0]
        expected_target = f"{prefix}#{_native_source_id(work_id, fragment)}"
        if target.get("target") != expected_target:
            raise ValueError("LIB-050 native local link target rewrite drift")
        target_id = expected_target.partition("#")[2]
        if target_id not in observed_native_ids:
            raise ValueError("LIB-050 native local link target does not resolve")

    expected_attribute_tokens = Counter(
        token
        for source_node in source_body_nodes
        if _kind(source_node) == "element"
        for token in _expected_source_attribute_analysis(source_node).split()
    )
    observed_attribute_tokens = Counter(
        token
        for target in transcription.iter()
        for token in (target.get("ana") or "").split()
        if token.startswith("urn:ocd:thml-attribute:")
    )
    if observed_attribute_tokens != expected_attribute_tokens:
        raise ValueError("LIB-050 readable source-attribute token census drift")

    for source_node in source_body_nodes:
        record = record_by_node[id(source_node)]
        target = observed[str(record["feature_id"])][0]
        kind = _kind(source_node)
        expected_name = (
            "milestone"
            if kind != "element"
            else READABLE_TAGS.get(str(source_node.tag))
        )
        if str(source_node.tag) == "ThML.body":
            expected_name = "div"
        if str(source_node.tag) in {"tbody", "thead"}:
            expected_name = "table"
        if expected_name is None:
            raise ValueError(
                f"LIB-050 unsupported readable source element: {source_node.tag}"
            )
        if etree.QName(target).localname != expected_name:
            raise ValueError("LIB-050 readable TEI structure mapping drift")
        expected_attributes = _expected_readable_attributes(
            source_node, str(record["feature_id"]), record_by_node, work_id
        )
        if expected_attributes is not None and dict(target.attrib) != expected_attributes:
            raise ValueError(
                "LIB-050 readable TEI attribute mapping drift at "
                f"{record['feature_id']} ({source_node.tag}): "
                f"expected={expected_attributes!r}, observed={dict(target.attrib)!r}"
            )
        if kind == "element" and str(source_node.tag) not in {"tbody", "thead"}:
            if (target.text or "") != (source_node.text or ""):
                raise ValueError(
                    "LIB-050 readable direct-text drift at "
                    f"{record['feature_id']} ({source_node.tag})"
                )
            if str(source_node.tag) != "ThML.body" and (target.tail or "") != (
                source_node.tail or ""
            ):
                raise ValueError(
                    "LIB-050 readable tail-text drift at "
                    f"{record['feature_id']} ({source_node.tag})"
                )
        elif kind != "element" and (
            (target.text or "")
            or (target.tail or "") != (source_node.tail or "")
        ):
            raise ValueError("LIB-050 readable comment or PI carrier drift")

    for source_node in source_body_nodes:
        source_name = str(source_node.tag) if _kind(source_node) == "element" else ""
        if source_name in {"tbody", "thead"}:
            continue
        record = record_by_node[id(source_node)]
        target = observed[str(record["feature_id"])][0]
        kind = _kind(source_node)
        if kind != "element":
            expected_children: list[etree._Element] = []
        else:
            source_children = list(source_node)
            if source_name == "table":
                flattened: list[etree._Element] = []
                for child in source_children:
                    if isinstance(child.tag, str) and child.tag in {"tbody", "thead"}:
                        flattened.extend(list(child))
                    else:
                        flattened.append(child)
                source_children = flattened
            expected_children = [
                observed[str(record_by_node[id(child)]["feature_id"])][0]
                for child in source_children
            ]
        if list(target) != expected_children:
            raise ValueError(
                "LIB-050 readable parent or sibling relationship drift at "
                f"{record['feature_id']} ({source_name or kind})"
            )


def _verify_tei(
    candidate: CandidatePackage,
    prepared: list[tuple[Mapping[str, Any], bytes, etree._ElementTree, tuple[dict[str, Any], ...]]],
    xsd_path: Path,
) -> None:
    serialized = candidate.member_bytes("content.tei.xml")
    declaration = b"<?xml version='1.0' encoding='UTF-8'?>"
    if not serialized.startswith(declaration + b"\n<") or not serialized.endswith(b">"):
        raise ValueError("LIB-050 TEI serialization envelope drift")
    try:
        tree = etree.parse(
            io.BytesIO(serialized),
            etree.XMLParser(
                resolve_entities=False,
                no_network=True,
                remove_comments=False,
                remove_pis=False,
                huge_tree=True,
            ),
        )
    except etree.XMLSyntaxError as exc:
        raise ValueError("LIB-050 candidate TEI parse failure") from exc
    try:
        etree.XMLSchema(etree.parse(str(xsd_path))).assertValid(tree)
    except etree.DocumentInvalid as exc:
        raise ValueError("LIB-050 candidate fails TEI P5 XSD") from exc
    root = tree.getroot()
    if (
        tree.docinfo.doctype
        or root.getprevious() is not None
        or root.getnext() is not None
        or root.tag != f"{{{TEI_NS}}}teiCorpus"
        or dict(root.attrib) != {XML_ID: "john-owen-lib050-candidate"}
        or len(root) != 11
        or root.text
        or root.tail
    ):
        raise ValueError("LIB-050 TEI corpus topology drift")
    if etree.tostring(root[0], method="c14n", with_comments=True) != etree.tostring(
        _expected_corpus_header(), method="c14n", with_comments=True
    ):
        raise ValueError("LIB-050 corpus header drift")
    for tei, (work, content, source_tree, records) in zip(
        root[1:], prepared, strict=True
    ):
        if (
            tei.tag != f"{{{TEI_NS}}}TEI"
            or dict(tei.attrib) != {XML_ID: work["work_id"]}
            or len(tei) != 2
            or tei.text
            or tei.tail
        ):
            raise ValueError("LIB-050 TEI work identity or topology drift")
        expected_header = _expected_header(_metadata(source_tree))
        if etree.tostring(tei[0], method="c14n", with_comments=True) != etree.tostring(
            expected_header, method="c14n", with_comments=True
        ):
            raise ValueError(
                "LIB-050 TEI header metadata, publisher, responsibility, print, or rights drift"
            )
        text_node = tei[1]
        if (
            text_node.tag != f"{{{TEI_NS}}}text"
            or text_node.attrib
            or text_node.text
            or text_node.tail
            or len(text_node) != 1
        ):
            raise ValueError("LIB-050 TEI text topology drift")
        body = text_node[0]
        if (
            body.tag != f"{{{TEI_NS}}}body"
            or body.attrib
            or body.text
            or body.tail
            or len(body) != 1
        ):
            raise ValueError("LIB-050 TEI body topology drift")
        division = body[0]
        if (
            division.tag != f"{{{TEI_NS}}}div"
            or dict(division.attrib) != {"type": "retained-source-member"}
            or division.text
            or division.tail
            or len(division) != 3
        ):
            raise ValueError("LIB-050 TEI retained-source topology drift")
        head, readable_node, evidence_node = division
        metadata = _metadata(source_tree)
        if (
            head.tag != f"{{{TEI_NS}}}head"
            or head.attrib
            or head.text != metadata["title"]
            or head.tail
            or len(head)
            or readable_node.tag != f"{{{TEI_NS}}}div"
            or readable_node.get("type") != "readable-transcription"
            or not readable_node.get("corresp")
            or evidence_node.tag != f"{{{TEI_NS}}}div"
            or dict(evidence_node.attrib) != {"type": "retained-evidence"}
            or evidence_node.text
            or evidence_node.tail
            or len(evidence_node) != 2
        ):
            raise ValueError("LIB-050 TEI retained-source child topology drift")
        _verify_readable_transcription(
            source_tree, records, division, str(work["work_id"])
        )
        raw_node, transcript_node = evidence_node
        if (
            raw_node.tag != f"{{{TEI_NS}}}ab"
            or dict(raw_node.attrib)
            != {
                "type": "exact-retained-source-bytes",
                "subtype": "base64",
                "n": _sha(content),
            }
            or raw_node.tail
            or len(raw_node)
            or transcript_node.tag != f"{{{TEI_NS}}}div"
            or dict(transcript_node.attrib)
            != {"type": "complete-xml-node-transcription"}
            or transcript_node.text
            or transcript_node.tail
        ):
            raise ValueError("LIB-050 exact retained-byte binding drift")
        try:
            decoded = base64.b64decode(
                (raw_node.text or "").encode("ascii"), validate=True
            )
        except (UnicodeEncodeError, ValueError) as exc:
            raise ValueError("LIB-050 retained-byte base64 drift") from exc
        if decoded != content:
            raise ValueError("LIB-050 retained-byte omission or invention")
        nodes = list(transcript_node)
        if len(nodes) != len(records):
            raise ValueError("LIB-050 XML node omission, duplication, or invention")
        for node, expected in zip(nodes, records, strict=True):
            attrs = {
                "xml:id": node.get(XML_ID),
                **{
                    key: value
                    for key, value in node.attrib.items()
                    if key != XML_ID
                },
            }
            expected_attrs = {
                "xml:id": expected["feature_id"],
                "type": "source-xml-node",
                "subtype": expected["kind"],
                "n": str(expected["ordinal"]),
            }
            if (
                etree.QName(node).localname != "ab"
                or attrs != expected_attrs
                or len(node)
                or node.tail
                or _strict_json((node.text or "").encode(), "TEI node record")
                != expected
            ):
                raise ValueError(
                    "LIB-050 QName, attributes, order, text, tail, namespace, comment, or PI drift"
                )


def _first_party_module_path(root: Path, module: str) -> Path | None:
    direct = root.joinpath(*module.split(".")).with_suffix(".py")
    package = root.joinpath(*module.split("."), "__init__.py")
    return direct if direct.is_file() else package if package.is_file() else None


def _closure_paths(root: Path, policy: Mapping[str, Any]) -> tuple[Path, ...]:
    forbidden = tuple(policy.get("forbidden_oracle_imports", []))
    pending = ["build.tei.john_owen_lib050_oracle"]
    modules: dict[str, Path] = {}
    while pending:
        module = pending.pop()
        if module in modules:
            continue
        path = _first_party_module_path(root, module)
        if path is None:
            continue
        modules[module] = path
        parsed = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(parsed):
            names = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"__import__", "eval", "exec"}:
                raise ValueError("LIB-050 oracle closure contains dynamic execution")
            for name in names:
                if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden):
                    raise ValueError(f"LIB-050 oracle closure contains forbidden import {name}")
                found = _first_party_module_path(root, name)
                if found is not None:
                    pending.append(name)
    return tuple(sorted(set(modules.values()), key=lambda path: path.as_posix()))


def _closure_digest(root: Path, policy: Mapping[str, Any]) -> str:
    return _sha(_canonical([{"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())} for path in _closure_paths(root, policy)]))


def _source_set_sha(source_manifest: SourceManifest) -> str:
    members = sorted(
        ({"name": item["name"], "path": item["path"], "bytes": item["bytes"], "sha256": item["sha256"]} for item in source_manifest.record["authorities"] if item["role"] == "primary-source"),
        key=lambda item: (item["path"], item["name"]),
    )
    return _sha(_canonical({"contract": "ocd-source-member-set-v1", "members": members}))


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    package_schema = _strict_json(source_manifest.authority_path("candidate-package-schema").read_bytes(), "candidate package schema")
    raw_candidate_manifest = _strict_json(
        (candidate.path / "manifest.json").read_bytes(), "candidate manifest"
    )
    jsonschema.Draft202012Validator(package_schema).validate(raw_candidate_manifest)
    actual_members = {path.name for path in candidate.path.iterdir() if path.is_file()}
    if actual_members != MEMBERS:
        raise ValueError("LIB-050 candidate filesystem member drift")
    if set(candidate.member_names) != MEMBERS or candidate.manifest.get("status") != "nonaccepted":
        raise ValueError("LIB-050 candidate member or status drift")
    if candidate.manifest.get("source_manifest") != {"path": source_manifest.path.relative_to(root).as_posix(), "sha256": source_manifest.sha256} or candidate.manifest.get("converter") != source_manifest.record["converter"] or candidate.manifest.get("package_schema") != source_manifest.record["package_schema"]:
        raise ValueError("LIB-050 candidate authority binding drift")
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _strict_json(profile_bytes, "LIB-050 profile")
    policy = _strict_json(policy_bytes, "LIB-050 policy")
    expected_core = {"candidate_status": "nonaccepted", "publication_state": "not_ready", "required_member_names": sorted(MEMBERS), "required_work_count": 10, "required_source_member_count": 10, "required_adjacent_member_count": 22}
    if {key: sorted(policy[key]) if key == "required_member_names" else policy[key] for key in expected_core} != expected_core:
        raise ValueError("LIB-050 validation policy closure drift")
    works = profile.get("works")
    adjacent = profile.get("adjacent_retained_member_accounting")
    if not isinstance(works, list) or len(works) != 10 or not isinstance(adjacent, list) or len(adjacent) != 32 or sum(row["disposition"].startswith("included") for row in adjacent) != 10 or sum(row["disposition"].startswith("excluded") for row in adjacent) != 22:
        raise ValueError("LIB-050 profile census drift")
    prepared = []
    for work in works:
        identity = _strict_json(source_manifest.authority_path(work["identity_authority_name"]).read_bytes(), "work identity")
        if identity != {"contract": "ocd-reconstruction-work-identity-v1", "work_id": work["work_id"]}:
            raise ValueError("LIB-050 work identity binding drift")
        content = source_manifest.authority_path(work["authority_name"]).read_bytes()
        if len(content) != work["bytes"] or _sha(content) != work["sha256"]:
            raise ValueError("LIB-050 wrong or stale retained source")
        tree = _parse_source(content)
        prepared.append((work, content, tree, _records(tree, work["member_id"])))
    _verify_tei(candidate, prepared, source_manifest.authority_path("tei-p5-xsd"))
    expected_accountability, expected_provenance, expected_unresolved = _expected_evidence(source_manifest, profile, prepared)
    accountability = _strict_json(candidate.member_bytes("source-accountability.json"), "source accountability")
    jsonschema.Draft202012Validator(_strict_json(source_manifest.authority_path("source-accountability-schema").read_bytes(), "accountability schema")).validate(accountability)
    if candidate.member_bytes("source-accountability.json") != _canonical(expected_accountability):
        raise ValueError("LIB-050 source accounting omission, duplication, order, type, or extra-field drift")
    if candidate.member_bytes("provenance.json") != _canonical(expected_provenance):
        raise ValueError("LIB-050 metadata, identity, rights, type, status, or extra-field drift")
    if candidate.member_bytes("unresolved.jsonl") != expected_unresolved:
        raise ValueError("LIB-050 unresolved evidence drift")
    if candidate.member_bytes("README.source.md") != source_manifest.authority_path("source-local-readme").read_bytes():
        raise ValueError("LIB-050 source attribution README drift")
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).resolve().read_bytes()),
        "import_closure_sha256": _closure_digest(root, policy),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": _sha(source_manifest.authority_path("candidate-package-schema").read_bytes()),
        "source_sha256": _source_set_sha(source_manifest),
        "xsd_sha256": _sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(policy_bytes),
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()

__all__: tuple[str, ...] = ()
