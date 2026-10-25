"""Independent HTML5 source accounting for the PG42957 candidate."""

from __future__ import annotations

from collections import Counter
from functools import lru_cache
from hashlib import sha256
import inspect
import json
from pathlib import Path
import platform
import sys
from typing import Any, Mapping
from zipfile import ZipFile

import html5lib
from lxml import etree

from ocd_kernel.lib.storage_topology import repository_relative_path
from ocd_kernel.reconstruction.contract import (
    CandidatePackage,
    SourceManifest,
    _validation_authority_bindings,
)


ORACLE_ID = "ocd-l879-pg42957-independent-html5-tei-oracle"
ORACLE_VERSION = "1"
TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
PRIMARY_SOURCE = (
    "raw/clean-ready-acquisition-to-tei/master-4/28/"
    "modern-scepticism-christian-evidence-society-1871/42957-h.htm"
)
GROUP_TYPES = {
    "project_gutenberg_header", "title_page", "preface", "contents",
    "lecture", "explanatory_paper", "footnotes", "notes_and_printer",
    "transcribers_notes", "project_gutenberg_footer",
}
BLOCK_TAGS = {
    "ab", "cell", "div", "head", "item", "l", "lg", "list", "note",
    "p", "quote", "row", "table",
}
EXPECTED_HEADS = [
    "DESIGN IN NATURE.",
    "PANTHEISM.",
    "POSITIVISM.",
    "SCIENCE AND REVELATION.",
    "THE NATURE AND VALUE OF THE MIRACULOUS TESTIMONY TO CHRISTIANITY.",
    "THE GRADUAL DEVELOPMENT OF REVELATION.",
    "THE ALLEGED HISTORICAL DIFFICULTIES OF THE OLD AND NEW TESTAMENTS, AND THE LIGHT THROWN ON THEM BY MODERN DISCOVERIES.",
    "MYTHICAL THEORIES OF CHRISTIANITY.",
    "THE EVIDENTIAL VALUE OF ST. PAUL'S EPISTLES.",
    "CHRIST'S TEACHING AND INFLUENCE ON THE WORLD.",
    "THE COMPLETENESS AND ADEQUACY OF THE EVIDENCES OF CHRISTIANITY.",
    "EXPLANATORY PAPER",
]


def _sha(value: bytes) -> str:
    return sha256(value).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _classes(node: Any) -> set[str]:
    return set((node.attrib.get("class", "")).split())


def _norm(value: str) -> str:
    return " ".join(value.split())


def _parent_map(body: Any) -> dict[Any, Any]:
    return {
        child: parent
        for parent in body.iter()
        for child in list(parent)
        if isinstance(child.tag, str)
    }


@lru_cache(maxsize=1)
def _parsed_source(source_bytes: bytes) -> Any:
    """Parse one hash-checked source once per process; callers only read the tree."""

    return html5lib.parse(
        source_bytes, treebuilder="etree", namespaceHTMLElements=False
    )


def _path_map(body: Any) -> dict[Any, list[int]]:
    result: dict[Any, list[int]] = {body: []}
    for parent in body.iter():
        for index, child in enumerate(list(parent)):
            if isinstance(child.tag, str):
                result[child] = result[parent] + [index]
    return result


def _source_snapshot(source_bytes: bytes) -> dict[str, Any]:
    """Build a complete ordered HTML5 element ledger and feature census."""

    tree = _parsed_source(source_bytes)
    body_nodes = [node for node in tree.iter() if node.tag == "body"]
    if len(body_nodes) != 1:
        raise ValueError(f"expected one parsed body, found {len(body_nodes)}")
    body = body_nodes[0]
    nodes = [body, *[node for node in body.iter() if node is not body and isinstance(node.tag, str)]]
    paths = _path_map(body)
    parents = _parent_map(body)
    ledger = []
    for ordinal, node in enumerate(nodes):
        parent = parents.get(node)
        ledger.append(
            {
                "ordinal": ordinal,
                "path": paths[node],
                "parent_path": paths[parent] if parent is not None else None,
                "tag": node.tag,
                "attributes": dict(sorted(node.attrib.items())),
                "text_sha256": _sha((node.text or "").encode("utf-8")),
                "tail_sha256": _sha((node.tail or "").encode("utf-8")),
                "subtree_text_sha256": _sha(
                    "".join(node.itertext()).encode("utf-8")
                ),
            }
        )
    tag_counts = Counter(node.tag for node in nodes)
    class_counts = Counter(
        item for node in nodes for item in _classes(node)
    )
    ids = [node.get("id") for node in nodes if node.get("id")]
    links = [node.get("href") for node in nodes if node.tag == "a" and node.get("href")]
    fragment_targets = [value[1:] for value in links if value.startswith("#")]
    id_set = set(ids)
    page_markers = []
    for node in nodes:
        if node.tag != "span" or "pagenum" not in _classes(node):
            continue
        anchors = [child for child in list(node) if child.tag == "a" and child.get("id")]
        if len(anchors) != 1:
            raise ValueError("each page marker must contain one identified anchor")
        page_markers.append(
            {"id": anchors[0].get("id"), "n": _norm("".join(node.itertext()))}
        )
    notes = [
        {
            "id": node.get("id"),
            "text_sha256": _sha("".join(node.itertext()).encode("utf-8")),
        }
        for node in nodes
        if node.tag == "div" and "footnote" in _classes(node)
    ]
    note_refs = [
        {
            "id": node.get("id"),
            "target": node.get("href"),
            "text": _norm("".join(node.itertext())),
        }
        for node in nodes
        if node.tag == "a" and "fnanchor" in _classes(node)
    ]
    poetry = [
        _norm("".join(node.itertext()))
        for node in nodes
        if node.tag == "div" and "poetry-container" in _classes(node)
    ]
    tables = []
    for table in (node for node in nodes if node.tag == "table"):
        tables.append(
            [
                [_norm("".join(cell.itertext())) for cell in row if cell.tag in {"td", "th"}]
                for row in table.iter()
                if row.tag == "tr"
            ]
        )
    direct_children = list(body)
    lecture_heads = []
    cursor = 0
    for expected in EXPECTED_HEADS:
        for position in range(cursor, len(direct_children)):
            child = direct_children[position]
            if child.tag == "h2" and _norm("".join(child.itertext())) == expected:
                lecture_heads.append(expected)
                cursor = position + 1
                break
    body_text = _norm("".join(body.itertext()))
    headings = [
        {"tag": node.tag, "text": _norm("".join(node.itertext())), "id": node.get("id")}
        for node in nodes
        if node.tag in {"h1", "h2", "h3"}
    ]
    title_headings = [item for item in headings if item["tag"] == "h1"]
    return {
        "body_direct_child_count": len(body),
        "body_element_count_including_body": len(nodes),
        "tag_counts": dict(sorted(tag_counts.items())),
        "class_counts": dict(sorted(class_counts.items())),
        "element_ledger": ledger,
        "text_characters": len(body_text),
        "text_sha256": _sha(body_text.encode("utf-8")),
        "ids_in_order": ids,
        "ids_unique": len(ids) == len(id_set),
        "links_in_order": links,
        "unresolved_fragment_targets": sorted(set(fragment_targets) - id_set),
        "headings": headings,
        "title_heading_count": len(title_headings),
        "title_heading": title_headings[0]["text"] if len(title_headings) == 1 else None,
        "lecture_heads": lecture_heads,
        "page_markers": page_markers,
        "footnotes": notes,
        "footnote_references": note_refs,
        "poetry_texts": poetry,
        "tables": tables,
        "transcribers_notes": [
            _norm("".join(node.itertext()))
            for node in nodes
            if node.tag == "div" and "transnote" in _classes(node)
        ],
        "opening_text": _norm("".join(list(body)[0].itertext())),
        "closing_text": _norm("".join(list(body)[-1].itertext())),
    }


def _target_tag(node: Any, parents: Mapping[Any, Any]) -> str:
    tag = node.tag.lower()
    classes = _classes(node)
    parent = parents.get(node)
    parent_classes = _classes(parent) if parent is not None else set()
    if tag == "span" and "pagenum" in classes:
        return "ref"
    if tag == "span":
        return "l" if {"poetry", "stanza"} & parent_classes else "hi"
    if tag in {"i", "em", "b", "strong"}:
        return "hi"
    if tag == "a":
        return "ref" if node.get("href") or (node.text or "").strip() else "anchor"
    if tag in {"h1", "h2", "h3"}:
        return "head"
    if tag == "p":
        return "l" if {"poetry", "stanza"} & parent_classes else "p"
    if tag == "br":
        return "lb"
    if tag == "hr":
        return "milestone"
    if tag == "table":
        return "table"
    if tag == "tr":
        return "row"
    if tag in {"td", "th"}:
        return "cell"
    if tag in {"ul", "ol"}:
        return "list"
    if tag == "li":
        return "item"
    if tag == "div":
        if "footnote" in classes:
            return "note"
        if {"footnotes", "transnote"} & classes:
            return "div"
        if {"poetry-container", "poetry"} & classes:
            return "quote"
        if "stanza" in classes:
            return "lg"
        if "sig-container" in classes:
            return "p"
        if "sig" in classes or "sig" in parent_classes:
            return "seg"
        if {"i0", "i8", "in0", "in2"} & classes:
            return "l"
        if "tb" in classes:
            return "ab"
        return "ab"
    raise ValueError(f"unmapped retained source element {tag}")


def _expected_tag_sequence(body: Any, parents: Mapping[Any, Any]) -> list[set[str]]:
    sequence: list[set[str]] = []
    for node in body.iter():
        if node is body:
            continue
        if not isinstance(node.tag, str):
            continue
        # html5lib inserts this wrapper while parsing source table rows; the
        # retained lexical source and converter have no tbody carrier.
        if node.tag == "tbody":
            continue
        parent = parents.get(node)
        if node.tag == "a" and parent is not None:
            if parent.tag == "span" and "pagenum" in _classes(parent):
                continue
        target = _target_tag(node, parents)
        sequence.append({"head", "ab"} if node.tag in {"h1", "h2", "h3"} else {target})
    return sequence


def _tei_raw_text(element: etree._Element) -> str:
    pieces = [element.text or ""]
    for child in element:
        pieces.append(_tei_raw_text(child))
        if child.tail is not None:
            pieces.append(child.tail)
        elif etree.QName(child).localname in BLOCK_TAGS:
            pieces.append(" ")
    return "".join(pieces)


def _tei_text(element: etree._Element) -> str:
    """Normalize once after projecting all TEI text and block boundaries."""

    return _norm(_tei_raw_text(element))


def _closure_sha() -> str:
    contract_path = Path(inspect.getsourcefile(SourceManifest)).resolve(strict=True)
    return _sha(
        _canonical(
            {
                "oracle": _sha(Path(__file__).read_bytes()),
                "reconstruction-contract": _sha(contract_path.read_bytes()),
            }
        )
    )


def _json(manifest: SourceManifest, name: str) -> dict[str, Any]:
    value = json.loads(manifest.authority_path(name).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _oracle(manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    findings: list[str] = []
    try:
        profile = _json(manifest, "profile")
        source_path = manifest.authority_path("primary-source")
        source_bytes = source_path.read_bytes()
        source_members = [
            item for item in manifest.record["authorities"]
            if item.get("role") in {"primary-source", "retained-source-member"}
        ]
        receipt = _json(manifest, "source-receipt")
        expected_receipt = {
            item["name"]: (item["bytes"], item["sha256"])
            for item in receipt["retained_members"]
        }
        bound_members = {
            Path(item["path"]).name: (item["bytes"], item["sha256"])
            for item in source_members
        }
        if len(source_members) != 8 or expected_receipt != bound_members:
            findings.append("retained acquisition member set differs from its receipt")
        for item in source_members:
            payload = manifest.authority_path(item["name"]).read_bytes()
            if len(payload) != item["bytes"] or _sha(payload) != item["sha256"]:
                findings.append(f"retained member digest differs: {item['name']}")
        if repository_relative_path(manifest.repository_root, source_path) != PRIMARY_SOURCE:
            findings.append("primary source path differs")
        if len(source_bytes) != 847314 or _sha(source_bytes) != (
            "e8130d330cc70a9f1169ef888869dbd7b146ff78b5b1bef0e8d56cc5995206e8"
        ):
            findings.append("primary source bytes differ")
        snapshot = _source_snapshot(source_bytes)
        if profile.get("source_body") != snapshot:
            findings.append("complete HTML5 source profile differs from the retained source")
        if (
            snapshot["text_characters"] != 731071
            or snapshot["text_sha256"] != "b209892366efef6da858b515d2bd640323499b0d5496db766b0cb4755c0d354c"
            or snapshot["title_heading_count"] != 1
            or not snapshot["ids_unique"]
            or snapshot["unresolved_fragment_targets"]
            or snapshot["lecture_heads"] != EXPECTED_HEADS
            or len(snapshot["page_markers"]) != 526
            or len(snapshot["footnotes"]) != 181
            or len(snapshot["footnote_references"]) != 362
            or len(snapshot["poetry_texts"]) != 22
            or len(snapshot["tables"]) != 1
            or len(snapshot["tables"][0]) != 26
            or sum(len(row) for row in snapshot["tables"][0]) != 40
            or len(snapshot["transcribers_notes"]) != 1
            or snapshot["closing_text"] != "*** END OF THE PROJECT GUTENBERG EBOOK 42957 ***"
        ):
            findings.append("source text or source-feature boundary census differs")

        zip_authority = next(
            item for item in manifest.record["authorities"]
            if item.get("name") == "pg42957-h.zip"
        )
        direct_html = next(
            item for item in source_members if Path(item["path"]).name == "pg42957-images.html"
        )
        with ZipFile(manifest.authority_path(zip_authority["name"])) as archive:
            names = [item.filename for item in archive.infolist() if not item.is_dir()]
            image_hash = _sha(archive.read("images/cover.jpg"))
            html_payload = archive.read("pg42957-images.html")
        if (
            set(names) != {"images/cover.jpg", "pg42957-images.html"}
            or len(names) != len(set(names))
            or _sha(html_payload) != direct_html["sha256"]
            or image_hash != receipt["cover_member_sha256"]
            or set(names) != set(receipt["container_members"])
        ):
            findings.append("retained Gutenberg HTML ZIP does not reconcile to direct members")

        root = etree.fromstring(
            candidate.member_bytes("content.tei.xml"),
            etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True),
        )
        if root.tag != f"{{{TEI}}}TEI":
            findings.append("candidate does not have exactly one TEI root")
        xsd = etree.XMLSchema(etree.parse(str(manifest.authority_path("tei-validation-schema"))))
        if not xsd.validate(root):
            findings.extend(f"TEI XSD: {item}" for item in xsd.error_log)
        rng = etree.RelaxNG(etree.parse(str(manifest.authority_path("tei-p5-relaxng"))))
        if not rng.validate(root):
            findings.extend(f"TEI P5 Relax NG: {item}" for item in rng.error_log)

        document_text = root.find(f"{{{TEI}}}text")
        if document_text is None:
            findings.append("TEI text element is missing")
        else:
            body_text = _tei_text(document_text)
            if (
                len(body_text) != snapshot["text_characters"]
                or _sha(body_text.encode("utf-8")) != snapshot["text_sha256"]
            ):
                findings.append("complete normalized body text differs")
            structure = [document_text.find(f"{{{TEI}}}{name}") for name in ("front", "body", "back")]
            if any(item is None for item in structure):
                findings.append("front/body/back structure is incomplete")
            body = structure[1]
            if body is not None:
                divisions = body.findall(f"{{{TEI}}}div")
                if (
                    len(divisions) != 12
                    or [item.get("type") for item in divisions]
                    != ["lecture"] * 11 + ["explanatory_paper"]
                    or [
                        _norm("".join((item.find(f"{{{TEI}}}head") if item.find(f"{{{TEI}}}head") is not None else item).itertext()))
                        for item in divisions
                    ]
                    != EXPECTED_HEADS
                ):
                    findings.append("eleven-lecture and explanatory-paper divisions differ")

            front = structure[0]
            if front is not None and [item.get("type") for item in front.findall(f"{{{TEI}}}div")] != [
                "project_gutenberg_header", "title_page", "preface", "contents"
            ]:
                findings.append("front matter division sequence differs")
            back = structure[2]
            if back is not None and [item.get("type") for item in back.findall(f"{{{TEI}}}div")] != [
                "footnotes", "notes_and_printer", "transcribers_notes", "project_gutenberg_footer"
            ]:
                findings.append("back matter division sequence differs")

            actual_sequence = [
                {etree.QName(node).localname}
                for node in document_text.iterdescendants()
                if node.tag != f"{{{TEI}}}front"
                and node.tag != f"{{{TEI}}}body"
                and node.tag != f"{{{TEI}}}back"
                and not (
                    etree.QName(node).localname == "div"
                    and node.get("type") in GROUP_TYPES
                    and node.getparent() is not None
                    and etree.QName(node.getparent()).localname in {"front", "body", "back"}
                )
            ]
            html_doc = _parsed_source(source_bytes)
            html_body = next(node for node in html_doc.iter() if node.tag == "body")
            html_parents = _parent_map(html_body)
            expected_sequence = _expected_tag_sequence(html_body, html_parents)
            sequence_mismatch = len(actual_sequence) != len(expected_sequence) or any(
                not actual.issubset(expected)
                for expected, actual in zip(expected_sequence, actual_sequence)
            )
            if sequence_mismatch:
                mismatch = next(
                    (i for i, (expected, actual) in enumerate(zip(expected_sequence, actual_sequence)) if not actual.issubset(expected)),
                    min(len(expected_sequence), len(actual_sequence)),
                )
                findings.append(
                    f"ordered HTML carrier mapping differs at {mismatch} "
                    f"(expected={len(expected_sequence)}, actual={len(actual_sequence)})"
                )

            source_ids = snapshot["ids_in_order"]
            tei_ids = [node.get(XML_ID) for node in document_text.iterdescendants() if node.get(XML_ID)]
            if tei_ids != source_ids:
                findings.append("source identifiers are missing, duplicated, or reordered")
            id_nodes = {node.get(XML_ID): node for node in document_text.iterdescendants() if node.get(XML_ID)}
            html_doc = _parsed_source(source_bytes)
            html_body = next(node for node in html_doc.iter() if node.tag == "body")
            html_parents = _parent_map(html_body)
            source_by_id = {node.get("id"): node for node in html_body.iter() if node.get("id")}
            if set(id_nodes) != set(source_by_id):
                findings.append("source and TEI identifier sets differ")
            for identifier in source_ids:
                source_node = source_by_id.get(identifier)
                tei_node = id_nodes.get(identifier)
                if source_node is None or tei_node is None:
                    continue
                source_text = _norm("".join(source_node.itertext()))
                tei_node_text = _norm("".join(tei_node.itertext()))
                if source_text != tei_node_text:
                    findings.append(f"identified source text differs at {identifier}")
                    break
                if source_node.tag == "a" and source_node.get("href") != tei_node.get("target"):
                    findings.append(f"identified source link target differs at {identifier}")
                    break
                if source_node.tag == "a" and "fnanchor" in _classes(source_node) and tei_node.get("type") != "note_reference":
                    findings.append(f"note reference role differs at {identifier}")
                    break
                if source_node.tag == "span" and "pagenum" in _classes(source_node):
                    if tei_node.get("type") != "page_milestone":
                        findings.append(f"page marker role differs at {identifier}")
                        break

            expected_links = snapshot["links_in_order"]
            actual_links = [node.get("target") for node in document_text.iterdescendants() if node.get("target") is not None]
            if actual_links != expected_links:
                findings.append("source hyperlinks or their order differ")
            expected_pages = snapshot["page_markers"]
            actual_pages = [
                {"id": node.get(XML_ID), "n": node.get("n")}
                for node in document_text.iterdescendants()
                if node.get("type") == "page_milestone"
            ]
            if actual_pages != expected_pages:
                findings.append("page milestone identity, label, or order differs")
            expected_notes = [item["id"] for item in snapshot["footnotes"]]
            actual_notes = [node.get(XML_ID) for node in document_text.iterdescendants() if node.tag == f"{{{TEI}}}note"]
            if actual_notes != expected_notes:
                findings.append("footnote identity, attachment, or order differs")
            expected_refs = [(item["id"], item["target"]) for item in snapshot["footnote_references"]]
            actual_refs = [
                (node.get(XML_ID), node.get("target"))
                for node in document_text.iterdescendants()
                if node.get("type") == "note_reference"
            ]
            if actual_refs != expected_refs:
                findings.append("footnote reference identity, target, or order differs")
            source_poetry = snapshot["poetry_texts"]
            tei_parents = _parent_map(document_text)
            tei_poetry = []
            for node in document_text.iterdescendants():
                if node.tag != f"{{{TEI}}}quote" or node.get("type") != "poetry":
                    continue
                parent = tei_parents.get(node)
                nested_poetry = False
                while parent is not None and parent is not document_text:
                    if parent.tag == f"{{{TEI}}}quote" and parent.get("type") == "poetry":
                        nested_poetry = True
                        break
                    parent = tei_parents.get(parent)
                if not nested_poetry:
                    tei_poetry.append(_tei_text(node))
            if tei_poetry != source_poetry:
                findings.append("poetry block text or order differs")
            source_tables = snapshot["tables"]
            tei_tables = [
                [
                    [_norm("".join(cell.itertext())) for cell in row.findall(f"{{{TEI}}}cell")]
                    for row in table.findall(f".//{{{TEI}}}row")
                ]
                for table in document_text.iterdescendants()
                if node_tag_is(table, TEI, "table")
            ]
            if tei_tables != source_tables:
                findings.append("table row/cell text or order differs")

        config = _json(manifest, "source-config")
        identity = _json(manifest, "work-identity")
        state = _json(manifest, "target-state")
        acquisition = _json(manifest, "acquisition-record")
        title_nodes = root.xpath(
            "./t:teiHeader/t:fileDesc/t:titleStmt/t:title", namespaces={"t": TEI}
        )
        authors = root.xpath(
            "./t:teiHeader/t:fileDesc/t:titleStmt/t:author", namespaces={"t": TEI}
        )
        if len(title_nodes) != 1 or _norm("".join(title_nodes[0].itertext())) != config["title"]:
            findings.append("single TEI title does not bind the retained volume title")
        if authors or config.get("author") is not None or config.get("author_id") is not None:
            findings.append("aggregate author is not source-established")
        if (
            manifest.record.get("work_id") != identity["work_id"]
            or manifest.record.get("edition_id") != identity["textual_forms"][0]["editions"][0]["edition_id"]
            or manifest.record.get("acquisition_id") != acquisition["acquisition_id"]
            or acquisition["edition_id"] != manifest.record.get("edition_id")
            or manifest.record.get("textual_form_id") != identity["textual_forms"][0]["textual_form_id"]
        ):
            findings.append("source-manifest work/edition/form/acquisition binding differs")
        expected_targets = {
            (manifest.record["acquisition_id"], "acquisition", "acquired"),
            (manifest.record["edition_id"], "edition", "acquired"),
        }
        actual_targets = {
            (item.get("target_id"), item.get("target_type"), item.get("stage"))
            for item in state.get("targets", [])
        }
        if not expected_targets.issubset(actual_targets):
            findings.append("current state lacks acquired source-linked edition/acquisition")
        account = json.loads(candidate.member_bytes("source-accountability.json"))
        work_boundary = account.get("work_boundary", {})
        if work_boundary.get("candidate_tei_count") != 1 or account.get("work_id") != manifest.record["work_id"]:
            findings.append("source accountability does not bind one candidate TEI to one work")
        if (
            work_boundary.get("top_level_title_count") != 1
            or profile.get("top_level_title_count") != snapshot["title_heading_count"]
        ):
            findings.append("source-accountability work-boundary count differs")
        provenance = json.loads(candidate.member_bytes("provenance.json"))
        if (
            provenance.get("work_id") != manifest.record["work_id"]
            or provenance.get("edition_id") != manifest.record["edition_id"]
            or provenance.get("acquisition_id") != manifest.record["acquisition_id"]
            or provenance.get("candidate_tei_count") != 1
            or provenance.get("acceptance_status") != "nonaccepted"
        ):
            findings.append("candidate provenance identity or status differs")
        if candidate.manifest.get("status") != "nonaccepted":
            findings.append("candidate package is not nonaccepted")
        if manifest.record["validator"].get("import_closure_sha256") != _closure_sha():
            findings.append("independent oracle import closure differs")
    except (
        OSError, ValueError, KeyError, TypeError, StopIteration, etree.XMLSyntaxError,
        json.JSONDecodeError,
    ) as exc:
        findings.append(str(exc))

    result: dict[str, object] = {
        "status": "pass" if not findings else "fail",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": _closure_sha(),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": manifest.sha256,
        "candidate_sha256": candidate.sha256,
        **_validation_authority_bindings(manifest),
        "findings": sorted(findings),
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


def node_tag_is(node: etree._Element, namespace: str, local: str) -> bool:
    return node.tag == f"{{{namespace}}}{local}"


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
