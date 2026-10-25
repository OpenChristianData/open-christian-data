"""Producer-independent retained-source oracle for LIB-026."""

from __future__ import annotations

import ast
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import platform
import re
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-anf01-irenaeus-source-to-tei-oracle"
ORACLE_VERSION = "1"
SOURCE_PATH = "raw/ccel/anf/anf01.xml"
SOURCE_SHA256 = "8012ea0e35b497d2fbd783f9d4fd7b3a27d98c6dc66fd427b50d7312e6dd45af"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
SELECTED = ("ix.ii", "ix.iii", "ix.iv", "ix.vi", "ix.vii")
ALL_DIV1 = ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix")
ALL_DIV2 = (
    "ix.i",
    "ix.ii",
    "ix.iii",
    "ix.iv",
    "ix.v",
    "ix.vi",
    "ix.vii",
    "ix.viii",
)
TAG_MAP = {
    "br": "lb",
    "div2": "div",
    "div3": "div",
    "h2": "head",
    "h3": "head",
    "hr": "milestone",
    "i": "hi",
    "index": "index",
    "l": "l",
    "note": "note",
    "p": "p",
    "pb": "pb",
    "q": "q",
    "scripRef": "ref",
    "span": "seg",
    "verse": "lg",
}
EXPECTED_COUNTS = {
    "br": 9,
    "div2": 5,
    "div3": 173,
    "h2": 5,
    "h3": 173,
    "hr": 6,
    "i": 845,
    "index": 627,
    "l": 21,
    "note": 2_138,
    "p": 2_890,
    "pb": 252,
    "q": 1,
    "scripRef": 1_564,
    "span": 444,
    "verse": 6,
}
MEMBERS = {
    "manifest.json",
    "content.tei.xml",
    "source-accountability.json",
    "provenance.json",
    "unresolved.jsonl",
    "README.source.md",
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

    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _source_tree(content: bytes) -> etree._ElementTree:
    return etree.parse(
        io.BytesIO(content),
        etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            remove_comments=False,
            huge_tree=True,
        ),
    )


def _scope(
    tree: etree._ElementTree,
) -> tuple[list[etree._Element], etree._Element, list[etree._Element]]:
    body = tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError("ANF1 source lacks ThML.body")
    div1 = [
        child
        for child in body
        if isinstance(child.tag, str) and child.tag == "div1"
    ]
    if tuple(item.get("id") for item in div1) != ALL_DIV1:
        raise ValueError("ANF1 div1 census drift")
    irenaeus = div1[-1]
    div2 = [
        child
        for child in irenaeus
        if isinstance(child.tag, str) and child.tag == "div2"
    ]
    if tuple(item.get("id") for item in div2) != ALL_DIV2:
        raise ValueError("Irenaeus div2 census drift")
    selected = [item for item in div2 if item.get("id") in SELECTED]
    if tuple(item.get("id") for item in selected) != SELECTED:
        raise ValueError("Against Heresies selected scope drift")
    return div1, irenaeus, selected


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "-", value)


def _selector(node: etree._Element) -> str:
    parts: list[str] = []
    current: etree._Element | None = node
    while current is not None and current.tag != "ThML.body":
        if not isinstance(current.tag, str):
            break
        parent = current.getparent()
        if parent is None:
            break
        peers = [
            child
            for child in parent
            if isinstance(child.tag, str) and child.tag == current.tag
        ]
        parts.append(f"{current.tag}[{peers.index(current) + 1}]")
        current = parent
    return "ThML.body/" + "/".join(reversed(parts))


def _target_tag(source: etree._Element) -> str:
    if source.tag == "span" and source.get("lang"):
        return "foreign"
    return TAG_MAP[str(source.tag)]


def _expected_attributes(source: etree._Element, number: int) -> dict[str, str]:
    source_id = source.get("id")
    attrs = {
        "xml:id": "anf01-"
        + (_safe_id(source_id) if source_id else f"feature-{number:05d}")
    }
    tag = str(source.tag)
    for name, value in source.attrib.items():
        if name == "n" and tag in {"div2", "div3", "note", "pb"}:
            attrs["n"] = value
        elif name == "class" and tag in {"p", "span", "hr"}:
            attrs["rend"] = value
        elif name == "place" and tag == "note":
            attrs["place"] = value
        elif name == "href" and tag == "pb":
            attrs["facs"] = value
        elif name == "passage" and tag == "scripRef":
            attrs["cRef"] = value
        elif name == "osisRef" and tag == "scripRef":
            attrs["target"] = value
        elif name == "lang" and tag == "span":
            attrs["xml:lang"] = "grc" if value == "EL" else value.lower()
        elif name == "type" and tag == "verse":
            attrs["type"] = value
    if tag == "i":
        attrs["rend"] = "italic"
    elif tag == "scripRef":
        attrs["type"] = "scripture"
    elif tag == "hr":
        attrs["unit"] = "horizontal-rule"
    return attrs


def _expected_dispositions(source: etree._Element) -> list[dict[str, str]]:
    result = []
    tag = str(source.tag)
    for name, value in source.attrib.items():
        destination = "source-accountability"
        method = "preserved-exactly"
        if name == "id":
            destination, method = "@xml:id", "deterministic-prefix"
        elif name == "n" and tag in {"div2", "div3", "note", "pb"}:
            destination = "@n"
        elif name == "class" and tag in {"p", "span", "hr"}:
            destination = "@rend"
        elif name == "place" and tag == "note":
            destination = "@place"
        elif name == "href" and tag == "pb":
            destination = "@facs"
        elif name == "passage" and tag == "scripRef":
            destination = "@cRef"
        elif name == "osisRef" and tag == "scripRef":
            destination = "@target"
        elif name == "lang" and tag == "span":
            destination, method = "@xml:lang", "declared-language-code-map"
        elif name == "type" and tag == "verse":
            destination = "@type"
        elif name == "title" and tag.startswith("div"):
            destination = "child::head[1]"
        result.append(
            {
                "source_attribute": name,
                "source_value": value,
                "destination": destination,
                "method": method,
            }
        )
    return result


def _expected_rows(selected: list[etree._Element]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    def visit(
        node: etree._Element,
        parent_feature_id: str | None,
        parent_tei_id: str,
        child_ordinal: int,
    ) -> None:
        number = len(rows) + 1
        feature_id = f"anf01-irenaeus-feature-{number:05d}"
        tei_attrs = _expected_attributes(node, number)
        direct = (node.text or "").encode("utf-8")
        tail = (node.tail or "").encode("utf-8")
        row: dict[str, object] = {
            "feature_id": feature_id,
            "source_selector": _selector(node),
            "source_tag": node.tag,
            "source_xml_id": node.get("id"),
            "attributes": dict(node.attrib),
            "direct_text": node.text or "",
            "tail_text": node.tail or "",
            "direct_text_bytes": len(direct),
            "tail_text_bytes": len(tail),
            "direct_text_sha256": _sha(direct),
            "tail_text_sha256": _sha(tail),
            "tei_tag": _target_tag(node),
            "tei_xml_id": tei_attrs["xml:id"],
            "tei_parent_id": parent_tei_id,
            "tei_child_ordinal": child_ordinal,
            "tei_attributes": tei_attrs,
            "attribute_dispositions": _expected_dispositions(node),
            "disposition": "represented",
            "tei_selector": f"#{tei_attrs['xml:id']}",
            "parent_feature_id": parent_feature_id,
            "source_title_head": (
                node.get("title") if str(node.tag).startswith("div") else None
            ),
        }
        rows.append(row)
        title_offset = 1 if row["source_title_head"] is not None else 0
        source_ordinal = 0
        for child in node:
            if not isinstance(child.tag, str):
                raise ValueError("selected source contains comment or PI")
            if child.tag not in TAG_MAP:
                raise ValueError(f"unsupported selected source tag {child.tag!r}")
            source_ordinal += 1
            visit(
                child,
                feature_id,
                str(tei_attrs["xml:id"]),
                title_offset + source_ordinal,
            )

    for ordinal, book in enumerate(selected, start=1):
        before = len(rows)
        visit(book, None, "anf01-irenaeus-selected-books", ordinal)
        rows[before]["book_id"] = str(book.get("id"))
    return rows


def _normalize_tei_attributes(node: etree._Element) -> dict[str, str]:
    return {
        "xml:id"
        if key == f"{{{XML_NS}}}id"
        else "xml:lang"
        if key == f"{{{XML_NS}}}lang"
        else key: value
        for key, value in node.attrib.items()
    }


def _verify_tei_node(
    source: etree._Element, target: etree._Element, number: list[int]
) -> None:
    number[0] += 1
    if target.tag != f"{{{TEI_NS}}}{_target_tag(source)}":
        raise ValueError("LIB-026 TEI element-kind drift")
    if _normalize_tei_attributes(target) != _expected_attributes(source, number[0]):
        raise ValueError("LIB-026 TEI attribute drift")
    source_title = source.get("title") if str(source.tag).startswith("div") else None
    children = [child for child in target if isinstance(child.tag, str)]
    offset = 0
    if source_title is not None:
        if (
            not children
            or children[0].tag != f"{{{TEI_NS}}}head"
            or children[0].text != source_title
            or children[0].tail not in {None, ""}
            or children[0].attrib
        ):
            raise ValueError("LIB-026 projected division-title drift")
        offset = 1
    if (target.text or "") != (source.text or "") or (target.tail or "") != (
        source.tail or ""
    ):
        raise ValueError("LIB-026 TEI direct or tail text drift")
    source_children = [child for child in source if isinstance(child.tag, str)]
    if len(children) - offset != len(source_children):
        raise ValueError("LIB-026 TEI omission duplication or invention")
    for source_child, target_child in zip(
        source_children, children[offset:], strict=True
    ):
        _verify_tei_node(source_child, target_child, number)


def _verify_tei(selected: list[etree._Element], content: bytes) -> None:
    try:
        tree = etree.parse(
            io.BytesIO(content),
            etree.XMLParser(
                resolve_entities=False,
                no_network=True,
                remove_comments=False,
                huge_tree=True,
            ),
        )
    except etree.XMLSyntaxError as exc:
        raise ValueError("LIB-026 TEI is not well-formed") from exc
    if not content.startswith(b"<?xml version='1.0' encoding='UTF-8'?>\n"):
        raise ValueError("LIB-026 TEI XML declaration drift")
    root = tree.getroot()
    if root.getprevious() is not None or root.getnext() is not None:
        raise ValueError("LIB-026 TEI root-sibling invention")
    for node in root.iter():
        if not isinstance(node.tag, str):
            raise ValueError("LIB-026 TEI comment or PI invention")
        if etree.QName(node).namespace != TEI_NS:
            raise ValueError("LIB-026 TEI namespace drift")
        for attr in node.attrib:
            if etree.QName(attr).namespace not in {None, XML_NS}:
                raise ValueError("LIB-026 TEI attribute namespace drift")
    if (
        root.tag != f"{{{TEI_NS}}}TEI"
        or _normalize_tei_attributes(root) != {"xml:id": "anf01-irenaeus-lib026"}
        or (root.text or "") != ""
        or (root.tail or "") != ""
    ):
        raise ValueError("LIB-026 TEI root drift")
    children = [child for child in root if isinstance(child.tag, str)]
    if [child.tag for child in children] != [
        f"{{{TEI_NS}}}teiHeader",
        f"{{{TEI_NS}}}text",
    ]:
        raise ValueError("LIB-026 TEI root topology drift")
    expected_header = (
        '<teiHeader xmlns="http://www.tei-c.org/ns/1.0"><fileDesc><titleStmt>'
        '<title>Against Heresies</title><author>Irenaeus of Lyons</author>'
        '<respStmt><resp>editors and translators (local config claim)</resp><name>Alexander Roberts and James Donaldson</name></respStmt>'
        '<respStmt><resp>American editor (local config claim)</resp><name>A. Cleveland Coxe</name></respStmt>'
        '</titleStmt><publicationStmt><publisher>Open Christian Data</publisher>'
        '<availability status="restricted"><p>The existing source config labels the work public domain and records that CCEL confirmed parsing is permitted. This candidate is nonaccepted; human rights review and publication authorization remain absent.</p></availability>'
        '</publicationStmt><sourceDesc><bibl><ptr target="https://www.ccel.org/ccel/schaff/anf01.xml"/>'
        '<idno type="sha256">8012ea0e35b497d2fbd783f9d4fd7b3a27d98c6dc66fd427b50d7312e6dd45af</idno>'
        '<note type="print-source">Ante-Nicene Fathers, Volume I (1885), retained CCEL ThML witness; no print collation performed</note>'
        '</bibl></sourceDesc></fileDesc></teiHeader>'
    )
    if etree.tostring(children[0], encoding="unicode") != expected_header:
        raise ValueError("LIB-026 complete TEI header drift")
    text = children[1]
    text_children = [child for child in text if isinstance(child.tag, str)]
    if (
        _normalize_tei_attributes(text)
        or (text.text or "") != ""
        or (text.tail or "") != ""
        or [child.tag for child in text_children] != [f"{{{TEI_NS}}}body"]
    ):
        raise ValueError("LIB-026 TEI text topology drift")
    body = text_children[0]
    if (
        _normalize_tei_attributes(body)
        != {"xml:id": "anf01-irenaeus-selected-books"}
        or (body.text or "") != ""
        or (body.tail or "") != ""
    ):
        raise ValueError("LIB-026 TEI body drift")
    target_books = [child for child in body if isinstance(child.tag, str)]
    if len(target_books) != 5:
        raise ValueError("LIB-026 selected book count drift")
    number = [0]
    for source_book, target_book in zip(selected, target_books, strict=True):
        _verify_tei_node(source_book, target_book, number)
    if number[0] != 9_159:
        raise ValueError("LIB-026 TEI element census drift")
    try:
        compiled_schema().assertValid(tree)
    except etree.DocumentInvalid as exc:
        raise ValueError("LIB-026 candidate fails direct TEI P5 XSD validation") from exc


def _expected_accountability(
    div1: list[etree._Element],
    irenaeus: etree._Element,
    selected: list[etree._Element],
    rows: list[dict[str, object]],
) -> dict[str, object]:
    div2 = [
        child
        for child in irenaeus
        if isinstance(child.tag, str) and child.tag == "div2"
    ]
    selected_book_census = []
    for book in selected:
        book_rows = [
            row
            for row in rows
            if str(row["source_selector"]).startswith(_selector(book))
        ]
        selected_book_census.append(
            {
                "div2_id": book.get("id"),
                "title": book.get("title"),
                "feature_count": len(book_rows),
                "attribute_count": sum(len(row["attributes"]) for row in book_rows),
                "direct_text_bytes": sum(int(row["direct_text_bytes"]) for row in book_rows),
                "tail_text_bytes": sum(int(row["tail_text_bytes"]) for row in book_rows),
                "source_subtree_sha256": _sha(
                    etree.tostring(book, encoding="UTF-8", with_tail=False)
                ),
            }
        )
    counts = Counter(str(row["source_tag"]) for row in rows)
    return {
        "contract": "ocd-anf01-irenaeus-source-accountability-v1",
        "schema": "irenaeus-against-heresies.source-accountability.schema.json",
        "profile_id": "anf01-div1-ix-five-against-heresies-books-v1",
        "source_scope": "ANF1 ThML.body div1 ix; selected div2 ix.ii, ix.iii, ix.iv, ix.vi, ix.vii",
        "source_member": {
            "path": SOURCE_PATH,
            "bytes": 4_511_814,
            "sha256": SOURCE_SHA256,
            "disposition": "sole retained source member",
        },
        "div1_accounting": [
            {
                "ordinal": ordinal,
                "div1_id": item.get("id"),
                "title": item.get("title", ""),
                "disposition": (
                    "irenaeus-parent-scope"
                    if item is irenaeus
                    else "sibling-anf-work-excluded"
                ),
            }
            for ordinal, item in enumerate(div1, start=1)
        ],
        "irenaeus_child_accounting": [
            {
                "ordinal": ordinal,
                "tag": child.tag,
                "xml_id": child.get("id"),
                "title": child.get("title"),
                "disposition": (
                    "selected-book-represented"
                    if child.tag == "div2" and child.get("id") in SELECTED
                    else "outside-against-heresies-book-scope"
                ),
            }
            for ordinal, child in enumerate(irenaeus, start=1)
            if isinstance(child.tag, str)
        ],
        "selected_book_ids": list(SELECTED),
        "division_accounting": [
            {
                "ordinal": ordinal,
                "div2_id": str(item.get("id")),
                "title": item.get("title", ""),
                "disposition": (
                    "selected-book-represented"
                    if item.get("id") in SELECTED
                    else "outside-against-heresies-book-scope"
                ),
            }
            for ordinal, item in enumerate(div2, start=1)
        ],
        "selected_book_census": selected_book_census,
        "feature_count": len(rows),
        "attribute_count": sum(len(row["attributes"]) for row in rows),
        "feature_counts": dict(sorted(counts.items())),
        "selected_direct_text_bytes": sum(int(row["direct_text_bytes"]) for row in rows),
        "selected_tail_text_bytes": sum(int(row["tail_text_bytes"]) for row in rows),
        "omitted_feature_count": 0,
        "duplicate_feature_count": 0,
        "unresolved_feature_count": 0,
        "crosswalk": rows,
    }


def _verify_evidence(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
    div1: list[etree._Element],
    irenaeus: etree._Element,
    selected: list[etree._Element],
    rows: list[dict[str, object]],
) -> None:
    accountability = _strict_json(
        candidate.member_bytes("source-accountability.json"), "source accountability"
    )
    schema = _strict_json(
        source_manifest.authority_path("source-accountability-schema").read_bytes(),
        "source accountability schema",
    )
    errors = sorted(Draft202012Validator(schema).iter_errors(accountability), key=str)
    if errors:
        raise ValueError(f"LIB-026 source-accountability schema failure: {errors[0].message}")
    if accountability != _expected_accountability(div1, irenaeus, selected, rows):
        raise ValueError("LIB-026 source-accountability semantic drift")

    expected_provenance = {
        "contract": "ocd-anf01-irenaeus-provenance-v1",
        "status": "nonaccepted",
        "source_id": "ccel-anf01-irenaeus-against-heresies",
        "work_id": "irenaeus-against-heresies",
        "title": "Against Heresies",
        "author": "Irenaeus of Lyons",
        "source": {
            "path": SOURCE_PATH,
            "bytes": 4_511_814,
            "sha256": SOURCE_SHA256,
            "parent_scope": "div1 ix",
            "selected_books": list(SELECTED),
        },
        "local_config_metadata": {
            "contributors": [
                "Alexander Roberts and James Donaldson (editors and translators, 1885)",
                "A. Cleveland Coxe (American editor)",
            ],
            "source_edition": "Ante-Nicene Fathers, Vol. 1. Alexander Roberts and James Donaldson (eds.); A. Cleveland Coxe (American ed.). Buffalo: Christian Literature Publishing Co., 1885.",
            "license_claim": "public-domain",
            "source_format": "ThML XML",
        },
        "print_collation": "not-performed",
        "accepted_ir": "not_accepted",
        "human_review": "required",
        "publication": "not_ready",
        "canonical_data_written": False,
        "canonical_ir_written": False,
    }
    if _strict_json(candidate.member_bytes("provenance.json"), "provenance") != expected_provenance:
        raise ValueError("LIB-026 metadata or provenance drift")
    expected_unresolved = [
        {
            "id": "anf01-irenaeus-print-collation-not-performed",
            "scope": "edition witness",
            "status": "unresolved",
            "question": "Does the retained CCEL witness differ substantively from the identified 1885 print edition?",
            "evidence": "The candidate is bound only to the retained ANF1 XML; no print collation was performed.",
        },
        {
            "id": "anf01-irenaeus-rights-human-acceptance-and-publication",
            "scope": "Against Heresies",
            "status": "unresolved",
            "question": "Will a maintainer accept the candidate and separately authorize publication after rights review?",
            "evidence": "Technical verification is not human textual acceptance, a rights decision, or publication authorization.",
        },
    ]
    if candidate.member_bytes("unresolved.jsonl") != b"".join(
        _canonical(item) for item in expected_unresolved
    ):
        raise ValueError("LIB-026 unresolved evidence drift")
    expected_readme = """# Irenaeus, Against Heresies — retained source reconstruction

This nonaccepted TEI candidate is reconstructed deterministically from the retained `raw/ccel/anf/anf01.xml` witness. The authoritative local-config scope is ANF1 `div1` ix and exactly the five Against Heresies book divisions `ix.ii`, `ix.iii`, `ix.iv`, `ix.vi`, and `ix.vii`.

The introductory note (`ix.i`), elucidation (`ix.v`), fragments (`ix.viii`), non-`div2` Irenaeus siblings, and all sibling ANF works (`div1` i–viii) are explicitly excluded and accounted. No excluded text is silently folded into the candidate.

The existing source config identifies Alexander Roberts and James Donaldson as editors and translators and A. Cleveland Coxe as American editor, identifies the 1885 ANF Volume I edition, labels the work public domain, and records that CCEL confirmed parsing is permitted. These are bound metadata claims, not a new human rights determination.

The candidate remains `accepted_ir:not_accepted`, `human_review:required`, and `publication:not_ready`. No canonical data or IR is written.
""".encode("utf-8")
    if candidate.member_bytes("README.source.md") != expected_readme:
        raise ValueError("LIB-026 README evidence drift")
    config = _strict_json(
        source_manifest.authority_path("existing-source-config").read_bytes(),
        "existing source config",
    )
    expected_config = {
        "resource_id": "irenaeus-against-heresies",
        "title": "Against Heresies",
        "author": "Irenaeus of Lyons",
        "source_hash": "sha256:" + SOURCE_SHA256,
        "source_format": "ThML XML",
        "license": "public-domain",
        "notes": "CCEL confirmed OK to parse. Crawl-delay 10s per robots.txt. Extracted from ANF1 div1 ix, book divs ix.ii, ix.iii, ix.iv, ix.vi, and ix.vii.",
    }
    if any(config.get(key) != value for key, value in expected_config.items()):
        raise ValueError("LIB-026 existing source metadata drift")


def _first_party_module_path(root: Path, module: str) -> Path | None:
    base = root.joinpath(*module.split("."))
    module_path = base.with_suffix(".py")
    if module_path.is_file():
        return module_path.resolve()
    package_path = base / "__init__.py"
    if package_path.is_file():
        return package_path.resolve()
    return None


def _resolved_import_name(
    module: str, module_path: Path, imported: str | None, level: int
) -> str:
    if level == 0:
        return imported or ""
    package = module if module_path.name == "__init__.py" else module.rpartition(".")[0]
    parts = package.split(".") if package else []
    if level - 1 > len(parts):
        return ""
    base = parts[: len(parts) - (level - 1)]
    if imported:
        base.extend(imported.split("."))
    return ".".join(base)


def _closure_paths(root: Path, policy: Mapping[str, object]) -> tuple[Path, ...]:
    forbidden = tuple(policy.get("forbidden_oracle_imports", []))
    pending = ["build.tei.irenaeus_against_heresies_oracle"]
    modules: dict[str, Path] = {}
    while pending:
        module = pending.pop()
        if module in modules:
            continue
        path = _first_party_module_path(root, module)
        if path is None:
            continue
        modules[module] = path
        parts = module.split(".")
        package_parts = parts if path.name == "__init__.py" else parts[:-1]
        for index in range(1, len(package_parts) + 1):
            package = ".".join(package_parts[:index])
            if package not in modules:
                pending.append(package)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = _resolved_import_name(module, path, node.module, node.level)
                if base:
                    names.append(base)
                    names.extend(
                        f"{base}.{alias.name}"
                        for alias in node.names
                        if alias.name != "*"
                    )
            elif isinstance(node, ast.Call) and (
                (
                    isinstance(node.func, ast.Name)
                    and node.func.id in {"__import__", "eval", "exec", "import_module"}
                )
                or (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "import_module"
                )
            ):
                raise ValueError("oracle closure contains dynamic import or execution")
            for name in names:
                if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden):
                    raise ValueError(f"oracle closure contains forbidden import {name}")
                if _first_party_module_path(root, name) is not None:
                    pending.append(name)
    return tuple(sorted(set(modules.values()), key=lambda item: item.as_posix()))


def _closure_digest(root: Path, policy: Mapping[str, object]) -> str:
    records = [
        {"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())}
        for path in _closure_paths(root, policy)
    ]
    return _sha(_canonical(records))


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> Mapping[str, object]:
    source_manifest.verify()
    verify_integrity = getattr(candidate, "verify_integrity", None)
    if verify_integrity is not None:
        verify_integrity()
    if set(candidate.member_names) != MEMBERS or candidate.manifest.get("status") != "nonaccepted":
        raise ValueError("LIB-026 candidate member set or status drift")
    if candidate.manifest.get("source_id") != "ccel-anf01-irenaeus-against-heresies":
        raise ValueError("LIB-026 candidate source boundary drift")
    root = getattr(source_manifest, "repository_root", Path(__file__).resolve().parents[2])
    if hasattr(source_manifest, "path") and "converter" in source_manifest.record:
        expected_manifest = {
            "path": source_manifest.path.relative_to(root).as_posix(),
            "sha256": source_manifest.sha256,
        }
        if (
            candidate.manifest.get("source_manifest") != expected_manifest
            or candidate.manifest.get("converter") != source_manifest.record["converter"]
            or candidate.manifest.get("package_schema")
            != source_manifest.record["package_schema"]
        ):
            raise ValueError("LIB-026 candidate authority binding drift")

    source = source_manifest.authority_path("retained-thml").read_bytes()
    if len(source) != 4_511_814 or _sha(source) != SOURCE_SHA256:
        raise ValueError("LIB-026 retained source identity drift")
    source_tree = _source_tree(source)
    div1, irenaeus, selected = _scope(source_tree)
    rows = _expected_rows(selected)
    counts = Counter(str(row["source_tag"]) for row in rows)
    if (
        len(rows) != 9_159
        or dict(counts) != EXPECTED_COUNTS
        or sum(len(row["attributes"]) for row in rows) != 28_874
        or sum(int(row["direct_text_bytes"]) for row in rows) != 370_356
        or sum(int(row["tail_text_bytes"]) for row in rows) != 1_018_033
    ):
        raise ValueError("LIB-026 independent source census drift")
    _verify_tei(selected, candidate.member_bytes("content.tei.xml"))
    _verify_evidence(source_manifest, candidate, div1, irenaeus, selected, rows)

    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _strict_json(profile_bytes, "reconstruction profile")
    policy = _strict_json(policy_bytes, "validation policy")
    if (
        profile.get("profile_id") != "anf01-div1-ix-five-against-heresies-books-v1"
        or profile.get("selected_book_ids") != list(SELECTED)
        or profile.get("feature_count") != 9_159
        or profile.get("attribute_count") != 28_874
        or profile.get("selected_direct_text_bytes") != 370_356
        or profile.get("selected_tail_text_bytes") != 1_018_033
        or policy.get("candidate_status") != "nonaccepted"
        or policy.get("publication_state") != "not_ready"
        or policy.get("required_selected_book_ids") != list(SELECTED)
    ):
        raise ValueError("LIB-026 profile or policy drift")
    implementation = Path(__file__).resolve()
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(implementation.read_bytes()),
        "import_closure_sha256": _closure_digest(root, policy),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": _sha(
            source_manifest.authority_path("candidate-package-schema").read_bytes()
        ),
        "source_sha256": SOURCE_SHA256,
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
