"""Deterministic retained-CCEL XML reconstruction for LIB-050."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Any, Mapping
from urllib.parse import quote

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest


CONVERTER_ID = "ocd-john-owen-lib050-retained-xml-to-tei"
CONVERTER_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
MEMBERS = frozenset(
    {
        "README.source.md",
        "content.tei.xml",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    }
)

_READABLE_ELEMENT_NAMES = {
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


def _parse(content: bytes) -> etree._ElementTree:
    try:
        return etree.parse(
            __import__("io").BytesIO(content),
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
        raise ValueError("retained LIB-050 XML is not parseable") from exc


def _node_kind(node: etree._Element) -> str:
    if node.tag is etree.Comment:
        return "comment"
    if node.tag is etree.PI:
        return "processing-instruction"
    if isinstance(node.tag, str):
        return "element"
    raise ValueError("unsupported retained XML node")


def _document_nodes(tree: etree._ElementTree) -> list[tuple[str, etree._Element]]:
    root = tree.getroot()
    before: list[etree._Element] = []
    node = root.getprevious()
    while node is not None:
        before.append(node)
        node = node.getprevious()
    after: list[etree._Element] = []
    node = root.getnext()
    while node is not None:
        after.append(node)
        node = node.getnext()
    result: list[tuple[str, etree._Element]] = [
        ("pre-root", item) for item in reversed(before)
    ]

    def append_tree(current: etree._Element) -> None:
        result.append(("tree", current))
        for child in current:
            append_tree(child)

    append_tree(root)
    result.extend(("post-root", item) for item in after)
    return result


def _node_records(tree: etree._ElementTree, member_id: str) -> tuple[dict[str, Any], ...]:
    scoped_nodes = _document_nodes(tree)
    ordinal_by_identity = {
        id(node): ordinal for ordinal, (_scope, node) in enumerate(scoped_nodes, 1)
    }
    records: list[dict[str, Any]] = []
    for ordinal, (scope, node) in enumerate(scoped_nodes, 1):
        parent = node.getparent()
        siblings = list(parent) if parent is not None else [node]
        kind = _node_kind(node)
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
            "parent_ordinal": ordinal_by_identity.get(id(parent)),
            "sibling_ordinal": siblings.index(node) + 1,
        }
        record["payload_sha256"] = _sha(_canonical(record))
        records.append(record)
    return tuple(records)


def _first(tree: etree._ElementTree, expression: str) -> str:
    return "".join(str(value) for value in tree.xpath(expression)).strip()


def _metadata(tree: etree._ElementTree) -> dict[str, Any]:
    root = tree.getroot()
    comments = [
        node.text or ""
        for _scope, node in _document_nodes(tree)
        if _node_kind(node) == "comment"
    ]
    return {
        "title": _first(
            tree, "/ThML/ThML.head/electronicEdInfo/DC/DC.Title[not(@sub)]/text()"
        ),
        "creator": _first(
            tree, "/ThML/ThML.head/electronicEdInfo/DC/DC.Creator[@sub='Author'][1]/text()"
        ),
        "electronic_publisher": _first(
            tree, "/ThML/ThML.head/electronicEdInfo/DC/DC.Publisher/text()"
        ),
        "print_source": _first(tree, "/ThML/ThML.head/printSourceInfo/published/text()"),
        "rights": _first(tree, "/ThML/ThML.head/electronicEdInfo/DC/DC.Rights/text()"),
        "status": _first(tree, "/ThML/ThML.head/electronicEdInfo/status/text()"),
        "editorial_comments": _first(
            tree, "/ThML/ThML.head/electronicEdInfo/editorialComments/text()"
        ),
        "source_url": _first(
            tree,
            "/ThML/ThML.head/electronicEdInfo/DC/DC.Identifier[@scheme='URL']/text()",
        ),
        "xml_version": tree.docinfo.xml_version,
        "encoding": tree.docinfo.encoding,
        "doctype": tree.docinfo.doctype,
        "root_qname": str(root.tag),
        "root_attributes": [[str(name), value] for name, value in root.attrib.items()],
        "root_namespace_declarations": [
            ["" if name is None else name, value] for name, value in root.nsmap.items()
        ],
        "ccel_copyright_comment_present": any(
            "Copyright Christian Classics Ethereal Library" in text for text in comments
        ),
    }


def _token(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    return normalized.lower() or "unspecified"


def _source_attribute_analysis(source: etree._Element) -> str:
    return " ".join(
        f"urn:ocd:thml-attribute:{quote(str(name), safe='')}:{quote(value, safe='')}"
        for name, value in source.attrib.items()
    )


def _span_renditions(source: etree._Element) -> list[str]:
    renditions: list[str] = []
    if source_class := source.get("class"):
        renditions.append(f"class-{_token(source_class)}")
    if style := source.get("style"):
        normalized_style = re.sub(r"\s+", "", style.casefold())
        if "font-variant:small-caps" in normalized_style:
            renditions.append("small-caps")
        elif "font-style:italic" in normalized_style:
            renditions.append("italic")
        elif "font-weight:bold" in normalized_style:
            renditions.append("bold")
        else:
            renditions.append(f"style-{_token(style)}")
    return renditions


def _native_source_ids(
    tree: etree._ElementTree, work_id: str
) -> tuple[dict[int, str], dict[str, str]]:
    """Build stable, work-scoped native IDs for retained source IDs."""

    by_node: dict[int, str] = {}
    by_source_id: dict[str, str] = {}
    for _scope, node in _document_nodes(tree):
        if _node_kind(node) != "element" or not node.get("id"):
            continue
        source_id = str(node.get("id"))
        if source_id in by_source_id:
            raise ValueError(f"duplicate retained LIB-050 source id: {source_id}")
        native_id = f"{work_id}--{source_id}"
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", native_id):
            raise ValueError(f"retained LIB-050 source id is not XML-safe: {source_id}")
        by_source_id[source_id] = native_id
        by_node[id(node)] = native_id
    return by_node, by_source_id


def _rewrite_local_fragment(
    value: str, native_ids_by_source_id: Mapping[str, str]
) -> str:
    """Rewrite a retained local fragment while preserving any query prefix."""

    prefix, separator, fragment = value.partition("#")
    if not separator or fragment not in native_ids_by_source_id:
        return value
    return f"{prefix}#{native_ids_by_source_id[fragment]}"


def _readable_attributes(
    source: etree._Element,
    source_name: str,
    feature_id: str,
    native_ids_by_node: Mapping[int, str] | None = None,
    native_ids_by_source_id: Mapping[str, str] | None = None,
) -> dict[str, str]:
    attributes = {"corresp": f"#{feature_id}"}
    if native_id := (native_ids_by_node or {}).get(id(source)):
        attributes[XML_ID] = native_id
    if source_name in {"div", "div1", "div2", "div3", "div4"}:
        attributes["type"] = "source-division"
        attributes["subtype"] = _token(source.get("type") or source_name)
    elif source_name == "argument":
        attributes["rend"] = "argument"
    elif source_name == "attr":
        attributes["type"] = "source-attribute-text"
    elif source_name == "blockquote":
        attributes["type"] = "source-blockquote"
    elif source_name in {"em", "i"}:
        attributes["rend"] = "italic"
    elif source_name == "sup":
        attributes["rend"] = "superscript"
    elif source_name == "hr":
        attributes["unit"] = "horizontal-rule"
    elif source_name == "insertIndex":
        attributes["unit"] = "source-insert-index"
        if source_type := source.get("type"):
            attributes["subtype"] = _token(source_type)
    elif source_name == "note":
        attributes["type"] = "source-note"
        for name in ("place", "n", "resp"):
            if value := source.get(name):
                attributes[name] = value
        if anchored := source.get("anchored"):
            normalized = anchored.casefold()
            if normalized in {"yes", "true", "1"}:
                attributes["anchored"] = "true"
            elif normalized in {"no", "false", "0"}:
                attributes["anchored"] = "false"
            else:
                raise ValueError(
                    f"unsupported retained LIB-050 note anchored value: {anchored}"
                )
    elif source_name == "scripCom":
        attributes["type"] = "scripture-comment"
        if source_type := source.get("type"):
            attributes["subtype"] = _token(source_type)
        if passage := source.get("passage"):
            attributes["n"] = passage
        if reference := source.get("osisRef") or source.get("passage"):
            attributes["target"] = f"urn:osis:{reference.replace(' ', '%20')}"
    elif source_name == "scripContext":
        attributes["type"] = "scripture-context"
        if version := source.get("version"):
            attributes["subtype"] = _token(version)
            attributes["n"] = version
    elif source_name == "scripRef":
        attributes["type"] = "scripture"
        osis_ref = source.get("osisRef")
        passage = source.get("passage")
        if osis_ref:
            attributes["target"] = f"urn:osis:{osis_ref.replace(' ', '%20')}"
        elif passage and _LITERAL_ONLY_PASSAGES.get(source.get("id")) == passage:
            attributes["n"] = passage
        elif passage:
            attributes["target"] = f"urn:osis:{passage.replace(' ', '%20')}"
    elif source_name == "a" and source.get("href"):
        attributes["target"] = _rewrite_local_fragment(
            str(source.get("href")), native_ids_by_source_id or {}
        )
    elif source_name == "span":
        attributes["type"] = "source-span"
        renditions = _span_renditions(source)
        if source_class := source.get("class"):
            attributes["subtype"] = f"class-{_token(source_class)}"
            if source.get("lang") is None:
                if source_class.casefold() == "greek":
                    attributes[XML_LANG] = "grc"
                elif source_class.casefold() == "hebrew":
                    attributes[XML_LANG] = "he"
        if renditions:
            attributes["rend"] = " ".join(renditions)
    elif source_name in {"h1", "h2", "h3", "h4"}:
        attributes["type"] = "source-heading"
        attributes["subtype"] = source_name
    elif source_name == "verse":
        attributes["type"] = _token(source.get("type") or "verse")
    elif source_name == "date":
        if value := source.get("value"):
            # TEI @when accepts ISO dates and gYear values.  Retained ThML
            # also uses short numeric labels (for example ``107``) as source
            # display values; preserve those verbatim without emitting an
            # invalid TEI date value.
            if re.fullmatch(r"-?\d{4}(?:-\d{2}(?:-\d{2})?)?", value):
                attributes["when"] = value
            else:
                attributes["n"] = value
    elif source_name == "img":
        if source.get("src"):
            attributes["url"] = str(source.get("src"))
        if source.get("alt"):
            attributes["n"] = str(source.get("alt"))
        if source.get("width"):
            attributes["width"] = str(source.get("width"))
    elif source_name == "th":
        attributes["role"] = "label"
        if source.get("colspan"):
            attributes["cols"] = str(source.get("colspan"))
        if source.get("rowspan"):
            attributes["rows"] = str(source.get("rowspan"))
    if source_name == "p":
        alignment = source.get("align")
        style = source.get("style")
        if alignment:
            attributes["rend"] = f"align-{_token(alignment)}"
        elif style:
            match = re.fullmatch(r"\s*text-align\s*:\s*([^;]+)\s*;?\s*", style)
            attributes["rend"] = (
                f"align-{_token(match.group(1))}" if match else f"style-{_token(style)}"
            )
    if source_name in {"cite", "name"} and (title := source.get("title")):
        attributes["n"] = title
    if source_name == "pb" and source.get("n"):
        attributes["n"] = str(source.get("n"))
    if language := source.get("lang"):
        attributes[XML_LANG] = language
    analysis = _source_attribute_analysis(source)
    if analysis:
        attributes["ana"] = analysis
    return attributes


def _readable_node(
    source: etree._Element,
    feature_ids: Mapping[int, str],
    native_ids_by_node: Mapping[int, str],
    native_ids_by_source_id: Mapping[str, str],
) -> etree._Element:
    feature_id = feature_ids[id(source)]
    kind = _node_kind(source)
    if kind != "element":
        milestone = _element(
            "milestone",
            {
                "unit": (
                    "source-comment"
                    if kind == "comment"
                    else "source-processing-instruction"
                ),
                "corresp": f"#{feature_id}",
            },
        )
        milestone.tail = source.tail
        return milestone

    source_name = str(source.tag)
    if source_name in {"tbody", "thead"}:
        raise ValueError(
            f"retained LIB-050 {source_name} must be flattened by its table"
        )
    target_name = _READABLE_ELEMENT_NAMES.get(source_name)
    if target_name is None:
        raise ValueError(
            f"unsupported retained LIB-050 readable element: {source_name}"
        )
    target = _element(
        target_name,
        _readable_attributes(
            source,
            source_name,
            feature_id,
            native_ids_by_node,
            native_ids_by_source_id,
        ),
        source.text,
    )
    for child in source:
        if (
            source_name == "table"
            and isinstance(child.tag, str)
            and child.tag in {"tbody", "thead"}
        ):
            if (child.text or "").strip() or (child.tail or "").strip():
                raise ValueError(
                    f"retained LIB-050 {child.tag} carries visible text outside table rows"
                )
            wrapper_analysis = _source_attribute_analysis(child)
            target_analysis = target.get("ana")
            target.set(
                "ana",
                " ".join(
                    value
                    for value in (
                        target_analysis,
                        f"#{feature_ids[id(child)]}",
                        wrapper_analysis,
                    )
                    if value
                ),
            )
            for row in child:
                target.append(
                    _readable_node(
                        row,
                        feature_ids,
                        native_ids_by_node,
                        native_ids_by_source_id,
                    )
                )
            continue
        target.append(
            _readable_node(
                child,
                feature_ids,
                native_ids_by_node,
                native_ids_by_source_id,
            )
        )
    target.tail = source.tail
    return target


def _readable_transcription(
    tree: etree._ElementTree,
    records: tuple[dict[str, Any], ...],
    work_id: str,
) -> etree._Element:
    document_nodes = [node for _scope, node in _document_nodes(tree)]
    if len(document_nodes) != len(records):
        raise ValueError("retained LIB-050 readable feature census drifted")
    feature_ids = {
        id(node): str(record["feature_id"])
        for node, record in zip(document_nodes, records, strict=True)
    }
    native_ids_by_node, native_ids_by_source_id = _native_source_ids(tree, work_id)
    bodies = tree.xpath("/ThML/ThML.body")
    if len(bodies) != 1:
        raise ValueError("retained LIB-050 source must contain one ThML.body")
    source_body = bodies[0]
    attributes = {
        "type": "readable-transcription",
        "corresp": f"#{feature_ids[id(source_body)]}",
    }
    if native_id := native_ids_by_node.get(id(source_body)):
        attributes[XML_ID] = native_id
    if source_body.get(XML_SPACE):
        attributes[XML_SPACE] = str(source_body.get(XML_SPACE))
    if source_body.attrib:
        attributes["ana"] = _source_attribute_analysis(source_body)
    readable = _element("div", attributes, source_body.text)
    for child in source_body:
        readable.append(
            _readable_node(
                child,
                feature_ids,
                native_ids_by_node,
                native_ids_by_source_id,
            )
        )
    return readable


def _load_profile(source_manifest: SourceManifest) -> dict[str, Any]:
    value = json.loads(source_manifest.authority_path("reconstruction-profile").read_bytes())
    if (
        value.get("contract") != "ocd-john-owen-lib050-profile-v1"
        or value.get("profile_id") != "john-owen-lib050-ten-retained-xml-v1"
        or len(value.get("works", [])) != 10
        or len(value.get("adjacent_retained_member_accounting", [])) != 32
    ):
        raise ValueError("LIB-050 reconstruction profile closure drift")
    return value


def _evidence(
    source_manifest: SourceManifest,
    profile: Mapping[str, Any],
    prepared: list[tuple[Mapping[str, Any], bytes, etree._ElementTree, tuple[dict[str, Any], ...]]],
) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    work_rows = []
    for work, content, tree, records in prepared:
        kinds = {kind: sum(row["kind"] == kind for row in records) for kind in ("element", "comment", "processing-instruction")}
        work_rows.append(
            {
                "work_id": work["work_id"],
                "authority_name": work["authority_name"],
                "path": work["path"],
                "bytes": len(content),
                "sha256": _sha(content),
                "node_count": len(records),
                "node_kind_counts": kinds,
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
        "total_node_count": sum(row["node_count"] for row in work_rows),
        "works": work_rows,
        "adjacent_retained_member_accounting": profile[
            "adjacent_retained_member_accounting"
        ],
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
            for row in work_rows
        ],
        "canonical_data_written": False,
        "canonical_ir_written": False,
    }
    ages_ids = [
        row["work_id"]
        for row in work_rows
        if "AGES Software" in row["metadata"]["editorial_comments"]
    ]
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
            "scope": [row["work_id"] for row in work_rows],
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


def _tei(
    prepared: list[tuple[Mapping[str, Any], bytes, etree._ElementTree, tuple[dict[str, Any], ...]]]
) -> bytes:
    corpus = _element("teiCorpus", {"xml:id": "john-owen-lib050-candidate"})
    corpus_header = _element("teiHeader")
    corpus_file_desc = _element("fileDesc")
    corpus_title_stmt = _element("titleStmt")
    corpus_title_stmt.append(
        _element("title", text="LIB-050 John Owen retained-source cohort")
    )
    corpus_file_desc.append(corpus_title_stmt)
    corpus_publication = _element("publicationStmt")
    corpus_publication.append(_element("publisher", text="Open Christian Data"))
    corpus_availability = _element("availability", {"status": "restricted"})
    corpus_availability.append(
        _element("p", text="Nonaccepted technical reconstruction; publication not ready.")
    )
    corpus_publication.append(corpus_availability)
    corpus_file_desc.append(corpus_publication)
    corpus_source_desc = _element("sourceDesc")
    corpus_source_desc.append(
        _element("p", text="Ten exact retained CCEL ThML XML authorities; sourced via CCEL.org.")
    )
    corpus_file_desc.append(corpus_source_desc)
    corpus_header.append(corpus_file_desc)
    corpus.append(corpus_header)
    for work, content, tree, records in prepared:
        metadata = _metadata(tree)
        tei = _element("TEI", {"xml:id": str(work["work_id"])})
        header = _element("teiHeader")
        file_desc = _element("fileDesc")
        title_stmt = _element("titleStmt")
        title_stmt.append(_element("title", text=metadata["title"]))
        title_stmt.append(_element("author", text=metadata["creator"]))
        resp_stmt = _element("respStmt")
        resp_stmt.append(_element("resp", text="Retained electronic edition and ThML markup"))
        resp_stmt.append(_element("name", text=metadata["electronic_publisher"]))
        title_stmt.append(resp_stmt)
        file_desc.append(title_stmt)
        publication = _element("publicationStmt")
        publication.append(_element("publisher", text="Open Christian Data"))
        availability = _element("availability", {"status": "restricted"})
        availability.append(
            _element(
                "p",
                text="Nonaccepted technical reconstruction; human rights, edition, and textual review required; publication not ready.",
            )
        )
        publication.append(availability)
        file_desc.append(publication)
        source_desc = _element("sourceDesc")
        bibl = _element("bibl", {"type": "retained-electronic-witness"})
        bibl.append(_element("title", text=metadata["title"]))
        bibl.append(_element("author", text=metadata["creator"]))
        bibl.append(_element("publisher", text=metadata["electronic_publisher"]))
        bibl.append(_element("note", {"type": "print-source"}, metadata["print_source"]))
        bibl.append(_element("note", {"type": "rights"}, metadata["rights"]))
        bibl.append(_element("note", {"type": "editorial-comments"}, metadata["editorial_comments"]))
        bibl.append(_element("idno", {"type": "CCEL-path"}, metadata["source_url"]))
        source_desc.append(bibl)
        file_desc.append(source_desc)
        header.append(file_desc)
        tei.append(header)
        text = _element("text")
        body = _element("body")
        division = _element("div", {"type": "retained-source-member"})
        division.append(_element("head", text=metadata["title"]))
        division.append(_readable_transcription(tree, records, str(work["work_id"])))
        evidence = _element("div", {"type": "retained-evidence"})
        evidence.append(
            _element(
                "ab",
                {"type": "exact-retained-source-bytes", "subtype": "base64", "n": _sha(content)},
                base64.b64encode(content).decode("ascii"),
            )
        )
        transcription = _element("div", {"type": "complete-xml-node-transcription"})
        for record in records:
            transcription.append(
                _element(
                    "ab",
                    {
                        "xml:id": str(record["feature_id"]),
                        "type": "source-xml-node",
                        "subtype": str(record["kind"]),
                        "n": str(record["ordinal"]),
                    },
                    json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                )
            )
        evidence.append(transcription)
        division.append(evidence)
        body.append(division)
        text.append(body)
        tei.append(text)
        corpus.append(tei)
    return etree.tostring(corpus, encoding="UTF-8", xml_declaration=True, pretty_print=False)


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    profile = _load_profile(source_manifest)
    prepared = []
    for work in profile["works"]:
        content = source_manifest.authority_path(work["authority_name"]).read_bytes()
        if len(content) != work["bytes"] or _sha(content) != work["sha256"]:
            raise ValueError(f"LIB-050 retained source drift: {work['work_id']}")
        tree = _parse(content)
        prepared.append((work, content, tree, _node_records(tree, work["member_id"])))
    accountability, provenance, unresolved = _evidence(
        source_manifest, profile, prepared
    )
    result = {
        "content.tei.xml": _tei(prepared),
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": unresolved,
        "README.source.md": source_manifest.authority_path("source-local-readme").read_bytes(),
    }
    if set(result) != MEMBERS:
        raise ValueError("LIB-050 candidate member closure drift")
    return result


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION

__all__: tuple[str, ...] = ()
