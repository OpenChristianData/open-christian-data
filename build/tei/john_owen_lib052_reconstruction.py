"""Deterministic retained-CCEL XML reconstruction for LIB-052."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import re
from typing import Any, Mapping
from urllib.parse import quote

from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct


CONVERTER_ID = "ocd-john-owen-lib052-retained-xml-to-tei"
CONVERTER_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
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
    "br": "lb",
    "cite": "quote",
    "div": "div",
    "div1": "div",
    "div2": "div",
    "div3": "div",
    "em": "hi",
    "h1": "ab",
    "h2": "ab",
    "h3": "ab",
    "hr": "milestone",
    "i": "hi",
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
    "tr": "row",
    "ul": "list",
    "verse": "lg",
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
        raise ValueError("retained LIB-052 XML is not parseable") from exc


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


def _node_records(
    tree: etree._ElementTree, member_id: str
) -> tuple[dict[str, Any], ...]:
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
                [
                    ["" if name is None else name, value]
                    for name, value in node.nsmap.items()
                ]
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
            tree,
            "/ThML/ThML.head/electronicEdInfo/DC/DC.Creator[@sub='Author'][1]/text()",
        ),
        "electronic_publisher": _first(
            tree, "/ThML/ThML.head/electronicEdInfo/DC/DC.Publisher/text()"
        ),
        "print_source": _first(
            tree, "/ThML/ThML.head/printSourceInfo/published/text()"
        ),
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
    token = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    return token.lower() or "unspecified"


def _source_attribute_analysis(source: etree._Element) -> str:
    """Carry every original attribute into readable TEI as exact URI tokens."""

    return " ".join(
        f"urn:ocd:thml-attribute:{quote(str(name), safe='')}:{quote(value, safe='')}"
        for name, value in source.attrib.items()
    )


def _readable_attributes(
    source: etree._Element, source_name: str, feature_id: str
) -> dict[str, str]:
    attributes = {"corresp": f"#{feature_id}"}
    if source_name in {"div", "div1", "div2", "div3"}:
        attributes["type"] = "source-division"
        attributes["subtype"] = _token(source.get("type") or source_name)
    elif source_name == "argument":
        attributes["rend"] = "argument"
    elif source_name == "attr":
        attributes["type"] = "source-attribute-text"
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
                    f"unsupported retained LIB-052 note anchored value: {anchored}"
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
        if reference := source.get("osisRef") or source.get("passage"):
            attributes["target"] = f"urn:osis:{reference.replace(' ', '%20')}"
    elif source_name == "a" and source.get("href"):
        attributes["target"] = str(source.get("href"))
    elif source_name == "span":
        attributes["type"] = "source-span"
        renditions: list[str] = []
        if source_class := source.get("class"):
            attributes["subtype"] = f"class-{_token(source_class)}"
            renditions.append(f"class-{_token(source_class)}")
            if source.get("lang") is None:
                if source_class.casefold() == "greek":
                    attributes["{http://www.w3.org/XML/1998/namespace}lang"] = "grc"
                elif source_class.casefold() == "hebrew":
                    attributes["{http://www.w3.org/XML/1998/namespace}lang"] = "he"
        if style := source.get("style"):
            renditions.append(f"style-{_token(style)}")
        if renditions:
            attributes["rend"] = " ".join(renditions)
    elif source_name in {"h1", "h2", "h3"}:
        attributes["type"] = "source-heading"
        attributes["subtype"] = source_name
    elif source_name == "verse":
        attributes["type"] = "verse"
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
        attributes["{http://www.w3.org/XML/1998/namespace}lang"] = language
    analysis = _source_attribute_analysis(source)
    if analysis:
        attributes["ana"] = analysis
    return attributes


def _readable_node(
    source: etree._Element, feature_ids: Mapping[int, str]
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
    if source_name == "tbody":
        raise ValueError("retained LIB-052 tbody must be flattened by its table")
    target_name = _READABLE_ELEMENT_NAMES.get(source_name)
    if target_name is None:
        raise ValueError(
            f"unsupported retained LIB-052 readable element: {source_name}"
        )
    target = _element(
        target_name, _readable_attributes(source, source_name, feature_id), source.text
    )
    for child in source:
        if (
            source_name == "table"
            and isinstance(child.tag, str)
            and child.tag == "tbody"
        ):
            if (child.text or "").strip() or (child.tail or "").strip():
                raise ValueError(
                    "retained LIB-052 tbody carries visible text outside table rows"
                )
            tbody_analysis = _source_attribute_analysis(child)
            source_analysis = target.get("ana")
            target.set(
                "ana",
                " ".join(
                    value
                    for value in (
                        f"#{feature_ids[id(child)]}",
                        tbody_analysis,
                        source_analysis,
                    )
                    if value
                ),
            )
            for row in child:
                converted = _readable_node(row, feature_ids)
                target.append(converted)
            continue
        target.append(_readable_node(child, feature_ids))
    target.tail = source.tail
    return target


def _readable_transcription(
    tree: etree._ElementTree, records: tuple[dict[str, Any], ...]
) -> etree._Element:
    document_nodes = [node for _scope, node in _document_nodes(tree)]
    if len(document_nodes) != len(records):
        raise ValueError("retained LIB-052 readable feature census drifted")
    feature_ids = {
        id(node): str(record["feature_id"])
        for node, record in zip(document_nodes, records, strict=True)
    }
    bodies = tree.xpath("/ThML/ThML.body")
    if len(bodies) != 1:
        raise ValueError("retained LIB-052 source must contain one ThML.body")
    readable = _element(
        "div",
        {
            "type": "readable-transcription",
            "corresp": f"#{feature_ids[id(bodies[0])]}",
            **(
                {XML_SPACE: str(bodies[0].get(XML_SPACE))}
                if bodies[0].get(XML_SPACE)
                else {}
            ),
            **(
                {"ana": _source_attribute_analysis(bodies[0])}
                if bodies[0].attrib
                else {}
            ),
        },
    )
    readable.text = bodies[0].text
    for child in bodies[0]:
        readable.append(_readable_node(child, feature_ids))
    return readable


def _load_profile(source_manifest: SourceManifest) -> dict[str, Any]:
    value = json.loads(
        source_manifest.authority_path("reconstruction-profile").read_bytes()
    )
    if (
        value.get("contract") != "ocd-john-owen-lib052-profile-v1"
        or value.get("profile_id") != "john-owen-lib052-ten-retained-xml-v1"
        or len(value.get("works", [])) != 10
        or len(value.get("adjacent_retained_member_accounting", [])) != 32
    ):
        raise ValueError("LIB-052 reconstruction profile closure drift")
    return value


def _evidence(
    source_manifest: SourceManifest,
    profile: Mapping[str, Any],
    prepared: list[
        tuple[Mapping[str, Any], bytes, etree._ElementTree, tuple[dict[str, Any], ...]]
    ],
) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    work_rows = []
    for work, content, tree, records in prepared:
        kinds = {
            kind: sum(row["kind"] == kind for row in records)
            for kind in ("element", "comment", "processing-instruction")
        }
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
        "contract": "ocd-john-owen-lib052-source-accountability-v1",
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
        "contract": "ocd-john-owen-lib052-provenance-v1",
        "status": "nonaccepted",
        "publication_state": "not_ready",
        "source_id": source_manifest.record["source_id"],
        "source_credit": "sourced via CCEL.org",
        "rights": {
            "underlying_historic_works": "public-domain",
            "ccel_file_and_formatting": "restricted-human-review-required",
            "ages_electronic_base_assertion": "unresolved-for-seven-works",
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
            "id": "lib052-ages-electronic-base-rights",
            "scope": ages_ids,
            "status": "unresolved",
            "question": "What rights attach to the AGES-derived electronic base text?",
            "evidence": "Seven retained headers assert an AGES Software copyright while DC.Rights is empty.",
            "consequence": "Keep the candidate nonaccepted, restricted, and not publication-ready.",
        },
        {
            "id": "lib052-edition-and-proofreading",
            "scope": [row["work_id"] for row in work_rows],
            "status": "unresolved",
            "question": "Has each retained electronic witness been accepted as the intended edition and text?",
            "evidence": "Retained CCEL headers identify differing Banner reprints and mixed proof-read states.",
            "consequence": "Human edition and textual review remains required.",
        },
        {
            "id": "lib052-poema-map-hole",
            "scope": ["raw/ccel/owen/poema.xml"],
            "status": "unresolved",
            "question": "Should the retained Latin Poema witness receive a future work identity?",
            "evidence": "poema.xml is retained but absent from the frozen WorkCatalog and ticket maps.",
            "consequence": "Exclude it from LIB-052 and surface the map hole to LIB-090 without changing maps here.",
        },
    ]
    return accountability, provenance, b"".join(_canonical(row) for row in unresolved)


def _tei(
    prepared: list[
        tuple[Mapping[str, Any], bytes, etree._ElementTree, tuple[dict[str, Any], ...]]
    ],
) -> bytes:
    corpus = _element("teiCorpus", {"xml:id": "john-owen-lib052-candidate"})
    corpus_header = _element("teiHeader")
    corpus_file_desc = _element("fileDesc")
    corpus_title_stmt = _element("titleStmt")
    corpus_title_stmt.append(
        _element("title", text="LIB-052 John Owen retained-source cohort")
    )
    corpus_file_desc.append(corpus_title_stmt)
    corpus_publication = _element("publicationStmt")
    corpus_publication.append(_element("publisher", text="Open Christian Data"))
    corpus_availability = _element("availability", {"status": "restricted"})
    corpus_availability.append(
        _element(
            "p", text="Nonaccepted technical reconstruction; publication not ready."
        )
    )
    corpus_publication.append(corpus_availability)
    corpus_file_desc.append(corpus_publication)
    corpus_source_desc = _element("sourceDesc")
    corpus_source_desc.append(
        _element(
            "p",
            text="Ten exact retained CCEL ThML XML authorities; sourced via CCEL.org.",
        )
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
        resp_stmt.append(
            _element("resp", text="Retained electronic edition and ThML markup")
        )
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
        bibl.append(
            _element("note", {"type": "print-source"}, metadata["print_source"])
        )
        bibl.append(_element("note", {"type": "rights"}, metadata["rights"]))
        bibl.append(
            _element(
                "note", {"type": "editorial-comments"}, metadata["editorial_comments"]
            )
        )
        bibl.append(_element("idno", {"type": "CCEL-path"}, metadata["source_url"]))
        source_desc.append(bibl)
        file_desc.append(source_desc)
        header.append(file_desc)
        tei.append(header)
        text = _element("text")
        body = _element("body")
        division = _element("div", {"type": "retained-source-member"})
        division.append(_element("head", text=metadata["title"]))
        division.append(_readable_transcription(tree, records))
        evidence = _element("div", {"type": "exact-source-evidence"})
        evidence.append(
            _element(
                "ab",
                {
                    "type": "exact-retained-source-bytes",
                    "subtype": "base64",
                    "n": _sha(content),
                },
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
                    json.dumps(
                        record,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                )
            )
        evidence.append(transcription)
        division.append(evidence)
        body.append(division)
        text.append(body)
        tei.append(text)
        corpus.append(tei)
    return etree.tostring(
        corpus, encoding="UTF-8", xml_declaration=True, pretty_print=False
    )


def _canonical_path_spelling(value: str | Path) -> Path:
    """Return an absolute path after normalizing supported Windows namespaces."""
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise ValueError("LIB-052 candidate destination has an invalid path spelling")
    if os.name != "nt":
        return Path(os.path.abspath(raw))

    spelling = raw.replace("/", "\\")
    lowered = spelling.lower()
    if lowered.startswith(("\\\\.\\", "\\??\\", "\\\\??\\")):
        raise ValueError(
            "LIB-052 candidate destination uses an unsupported device path"
        )
    if lowered.startswith("\\\\?\\"):
        tail = spelling[4:]
        if tail.lower().startswith("unc\\"):
            unc_tail = tail[4:]
            parts = unc_tail.split("\\")
            if len(parts) < 2 or not parts[0] or not parts[1]:
                raise ValueError(
                    "LIB-052 candidate destination has a malformed extended UNC path"
                )
            spelling = "\\\\" + unc_tail
        elif re.match(r"^[A-Za-z]:\\", tail):
            spelling = tail
        else:
            raise ValueError(
                "LIB-052 candidate destination uses an unsupported extended path"
            )
    elif lowered.startswith(("\\\\?", "\\\\.")):
        raise ValueError("LIB-052 candidate destination has a malformed device path")

    if spelling.startswith("\\\\"):
        parts = spelling[2:].split("\\")
        if len(parts) < 2 or not parts[0] or not parts[1]:
            raise ValueError("LIB-052 candidate destination has a malformed UNC path")
        local_names = {
            "localhost",
            "127.0.0.1",
            "::1",
            "[::1]",
            "0:0:0:0:0:0:0:1",
            "[0:0:0:0:0:0:0:1]",
        }
        for name in (os.environ.get("COMPUTERNAME"), platform.node()):
            if name:
                local_names.add(name.rstrip(".").casefold())
        server = parts[0].rstrip(".").casefold()
        share = parts[1]
        if server in local_names and re.fullmatch(r"[A-Za-z]\$", share):
            suffix = "\\".join(parts[2:])
            spelling = f"{share[0].upper()}:\\{suffix}"

    drive_absolute = re.match(r"^[A-Za-z]:\\", spelling)
    if re.match(r"^[A-Za-z]:", spelling) and drive_absolute is None:
        raise ValueError("LIB-052 candidate destination uses a drive-relative path")
    allowed_colons = 1 if drive_absolute is not None else 0
    if spelling.count(":") != allowed_colons:
        raise ValueError("LIB-052 candidate destination uses ADS or an extra colon")
    try:
        return Path(os.path.abspath(spelling))
    except (OSError, ValueError) as exc:
        raise ValueError("LIB-052 candidate destination path is invalid") from exc


def _is_within(path: Path, root: Path) -> bool:
    try:
        common = os.path.commonpath((str(path), str(root)))
        return os.path.normcase(common) == os.path.normcase(str(root))
    except ValueError:
        return False


def _protected_output_roots(repository_root: Path) -> tuple[Path, ...]:
    topology = json.loads((repository_root / ".ocd-storage.json").read_bytes())
    library_value = topology.get("library_root")
    if not isinstance(library_value, str) or not Path(library_value).is_absolute():
        raise ValueError("LIB-052 storage topology has no absolute library_root")
    library_root = Path(library_value).resolve(strict=True)
    repository_root = repository_root.resolve(strict=True)
    worktrees_root = (Path.home() / ".codex" / "worktrees").resolve(strict=False)
    repository_roots = (repository_root, worktrees_root) + tuple(
        (repository_root / name).resolve(strict=False)
        for name in (
            "raw",
            "data",
            "ir",
            "reports",
            "exports",
            "acceptance",
            "publication",
        )
    )
    durable_roots = tuple(
        (library_root / name).resolve(strict=True)
        for name in ("raw", "reports", "exports")
    )
    return repository_roots + durable_roots


def guard_candidate_destination(
    source_manifest: SourceManifest, destination: str | Path
) -> Path:
    """Reject protected lexical and resolved destinations without probing writes."""
    requested = _canonical_path_spelling(destination)
    resolved = _canonical_path_spelling(requested.resolve(strict=False))
    for root in _protected_output_roots(source_manifest.repository_root):
        protected = _canonical_path_spelling(root)
        if _is_within(requested, protected) or _is_within(resolved, protected):
            raise ValueError(
                "LIB-052 candidate destination is inside protected storage"
            )
    return requested


def reconstruct_candidate(
    source_manifest: SourceManifest, destination: str | Path
) -> CandidatePackage:
    """Run the guarded LIB-052 reconstruction route at caller-selected output."""
    return reconstruct(
        source_manifest,
        guard_candidate_destination(source_manifest, destination),
        _convert,
    )


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    profile = _load_profile(source_manifest)
    prepared = []
    for work in profile["works"]:
        content = source_manifest.authority_path(work["authority_name"]).read_bytes()
        if len(content) != work["bytes"] or _sha(content) != work["sha256"]:
            raise ValueError(f"LIB-052 retained source drift: {work['work_id']}")
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
        "README.source.md": source_manifest.authority_path(
            "source-local-readme"
        ).read_bytes(),
    }
    if set(result) != MEMBERS:
        raise ValueError("LIB-052 candidate member closure drift")
    return result


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION

__all__: tuple[str, ...] = ()
