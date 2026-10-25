"""Faithfully reconstruct LIB-026 from the retained ANF1 Irenaeus books."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.tei.writer import XML_ID, XML_LANG, stamp_header, tei_el


CONVERTER_ID = "ocd-anf01-irenaeus-against-heresies-to-tei"
CONVERTER_VERSION = "1"
SOURCE_PATH = "raw/ccel/anf/anf01.xml"
SOURCE_SHA256 = "8012ea0e35b497d2fbd783f9d4fd7b3a27d98c6dc66fd427b50d7312e6dd45af"
SELECTED_BOOK_IDS = ("ix.ii", "ix.iii", "ix.iv", "ix.vi", "ix.vii")
ALL_DIV1_IDS = ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix")
ALL_IRENAEUS_DIV2_IDS = (
    "ix.i",
    "ix.ii",
    "ix.iii",
    "ix.iv",
    "ix.v",
    "ix.vi",
    "ix.vii",
    "ix.viii",
)
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
EXPECTED_ATTRIBUTES = 28_874
EXPECTED_DIRECT_TEXT_BYTES = 370_356
EXPECTED_TAIL_TEXT_BYTES = 1_018_033


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _parse(path: Path) -> etree._ElementTree:
    return etree.parse(
        str(path),
        etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            remove_comments=False,
            huge_tree=True,
        ),
    )


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "-", value)


def _source_scope(
    tree: etree._ElementTree,
) -> tuple[list[etree._Element], etree._Element, list[etree._Element]]:
    body = tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError("retained ANF1 source has no ThML.body")
    div1 = [
        child
        for child in body
        if isinstance(child.tag, str) and child.tag == "div1"
    ]
    if tuple(item.get("id") for item in div1) != ALL_DIV1_IDS:
        raise ValueError("retained ANF1 div1 identity or order drifted")
    irenaeus = div1[-1]
    div2 = [
        child
        for child in irenaeus
        if isinstance(child.tag, str) and child.tag == "div2"
    ]
    if tuple(item.get("id") for item in div2) != ALL_IRENAEUS_DIV2_IDS:
        raise ValueError("retained Irenaeus div2 identity or order drifted")
    selected = [item for item in div2 if item.get("id") in SELECTED_BOOK_IDS]
    if tuple(item.get("id") for item in selected) != SELECTED_BOOK_IDS:
        raise ValueError("retained Against Heresies book scope drifted")
    return div1, irenaeus, selected


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


def _tei_attrs(
    source: etree._Element, feature_number: int
) -> tuple[dict[str, str], list[dict[str, str]]]:
    source_id = source.get("id")
    attrs: dict[str, str] = {
        "xml:id": "anf01-"
        + (_safe_id(source_id) if source_id else f"feature-{feature_number:05d}")
    }
    dispositions: list[dict[str, str]] = []
    tag = str(source.tag)
    for name, value in source.attrib.items():
        destination = "source-accountability"
        method = "preserved-exactly"
        if name == "id":
            destination, method = "@xml:id", "deterministic-prefix"
        elif name == "n" and tag in {"div2", "div3", "note", "pb"}:
            attrs["n"] = value
            destination = "@n"
        elif name == "class" and tag in {"p", "span", "hr"}:
            attrs["rend"] = value
            destination = "@rend"
        elif name == "place" and tag == "note":
            attrs["place"] = value
            destination = "@place"
        elif name == "href" and tag == "pb":
            attrs["facs"] = value
            destination = "@facs"
        elif name == "passage" and tag == "scripRef":
            attrs["cRef"] = value
            destination = "@cRef"
        elif name == "osisRef" and tag == "scripRef":
            attrs["target"] = value
            destination = "@target"
        elif name == "lang" and tag == "span":
            attrs["xml:lang"] = "grc" if value == "EL" else value.lower()
            destination, method = "@xml:lang", "declared-language-code-map"
        elif name == "type" and tag == "verse":
            attrs["type"] = value
            destination = "@type"
        elif name == "title" and tag.startswith("div"):
            destination = "child::head[1]"
        dispositions.append(
            {
                "source_attribute": name,
                "source_value": value,
                "destination": destination,
                "method": method,
            }
        )
    if tag == "i":
        attrs["rend"] = "italic"
    elif tag == "scripRef":
        attrs["type"] = "scripture"
    elif tag == "hr":
        attrs["unit"] = "horizontal-rule"
    return attrs, dispositions


def _normalized_attrs(node: etree._Element) -> dict[str, str]:
    return {
        "xml:id" if key == XML_ID else "xml:lang" if key == XML_LANG else key: value
        for key, value in node.attrib.items()
    }


def _append_source_node(
    source: etree._Element,
    tei_parent: etree._Element,
    rows: list[dict[str, object]],
    parent_feature_id: str | None,
) -> None:
    number = len(rows) + 1
    feature_id = f"anf01-irenaeus-feature-{number:05d}"
    attrs, dispositions = _tei_attrs(source, number)
    target = tei_el(_target_tag(source), attrs)
    source_title = source.get("title") if str(source.tag).startswith("div") else None
    if source_title is not None:
        target.append(tei_el("head", text=source_title))
    target.text = source.text or ""
    target.tail = source.tail or ""
    child_ordinal = 1 + sum(1 for child in tei_parent if isinstance(child.tag, str))
    tei_parent.append(target)
    direct = (source.text or "").encode("utf-8")
    tail = (source.tail or "").encode("utf-8")
    row: dict[str, object] = {
        "feature_id": feature_id,
        "source_selector": _selector(source),
        "source_tag": source.tag,
        "source_xml_id": source.get("id"),
        "attributes": dict(source.attrib),
        "direct_text": source.text or "",
        "tail_text": source.tail or "",
        "direct_text_bytes": len(direct),
        "tail_text_bytes": len(tail),
        "direct_text_sha256": _sha(direct),
        "tail_text_sha256": _sha(tail),
        "tei_tag": _target_tag(source),
        "tei_xml_id": target.get(XML_ID),
        "tei_parent_id": tei_parent.get(XML_ID),
        "tei_child_ordinal": child_ordinal,
        "tei_attributes": _normalized_attrs(target),
        "attribute_dispositions": dispositions,
        "disposition": "represented",
        "tei_selector": f"#{target.get(XML_ID)}",
        "parent_feature_id": parent_feature_id,
        "source_title_head": source_title,
    }
    rows.append(row)
    for child in source:
        if not isinstance(child.tag, str):
            raise ValueError("selected ANF1 scope contains a comment or PI")
        if child.tag not in TAG_MAP:
            raise ValueError(f"unsupported retained source element {child.tag!r}")
        _append_source_node(child, target, rows, feature_id)


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    source = source_manifest.authority_path("retained-thml")
    source_bytes = source.read_bytes()
    if len(source_bytes) != 4_511_814 or _sha(source_bytes) != SOURCE_SHA256:
        raise ValueError("retained ANF1 authority identity mismatch")
    tree = _parse(source)
    div1, irenaeus, selected = _source_scope(tree)

    root = tei_el("TEI", {"xml:id": "anf01-irenaeus-lib026"})
    root.append(
        stamp_header(
            title="Against Heresies",
            author="Irenaeus of Lyons",
            contributors=[
                {
                    "name": "Alexander Roberts and James Donaldson",
                    "role": "editors and translators (local config claim)",
                },
                {"name": "A. Cleveland Coxe", "role": "American editor (local config claim)"},
            ],
            source_url="https://www.ccel.org/ccel/schaff/anf01.xml",
            source_sha256=SOURCE_SHA256,
            print_source="Ante-Nicene Fathers, Volume I (1885), retained CCEL ThML witness; no print collation performed",
            rights_statement="The existing source config labels the work public domain and records that CCEL confirmed parsing is permitted. This candidate is nonaccepted; human rights review and publication authorization remain absent.",
        )
    )
    text = tei_el("text")
    body = tei_el("body", {"xml:id": "anf01-irenaeus-selected-books"})
    text.append(body)
    root.append(text)

    rows: list[dict[str, object]] = []
    for book in selected:
        before = len(rows)
        _append_source_node(book, body, rows, None)
        rows[before]["book_id"] = str(book.get("id"))

    counts = Counter(str(row["source_tag"]) for row in rows)
    attribute_count = sum(len(row["attributes"]) for row in rows)
    direct_text_bytes = sum(int(row["direct_text_bytes"]) for row in rows)
    tail_text_bytes = sum(int(row["tail_text_bytes"]) for row in rows)
    if (
        len(rows) != 9_159
        or dict(counts) != EXPECTED_COUNTS
        or attribute_count != EXPECTED_ATTRIBUTES
        or direct_text_bytes != EXPECTED_DIRECT_TEXT_BYTES
        or tail_text_bytes != EXPECTED_TAIL_TEXT_BYTES
    ):
        raise ValueError("selected ANF1 feature, attribute, or text-byte census drifted")

    div2 = [
        child
        for child in irenaeus
        if isinstance(child.tag, str) and child.tag == "div2"
    ]
    division_accounting = [
        {
            "ordinal": ordinal,
            "div2_id": str(item.get("id")),
            "title": item.get("title", ""),
            "disposition": (
                "selected-book-represented"
                if item.get("id") in SELECTED_BOOK_IDS
                else "outside-against-heresies-book-scope"
            ),
        }
        for ordinal, item in enumerate(div2, start=1)
    ]
    selected_book_census = []
    for book in selected:
        book_rows = [
            row
            for row in rows
            if str(row["source_selector"]).startswith(
                _selector(book)
            )
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
    accountability = {
        "contract": "ocd-anf01-irenaeus-source-accountability-v1",
        "schema": "irenaeus-against-heresies.source-accountability.schema.json",
        "profile_id": "anf01-div1-ix-five-against-heresies-books-v1",
        "source_scope": "ANF1 ThML.body div1 ix; selected div2 ix.ii, ix.iii, ix.iv, ix.vi, ix.vii",
        "source_member": {
            "path": SOURCE_PATH,
            "bytes": len(source_bytes),
            "sha256": SOURCE_SHA256,
            "disposition": "sole retained source member",
        },
        "div1_accounting": [
            {
                "ordinal": ordinal,
                "div1_id": item.get("id"),
                "title": item.get("title", ""),
                "disposition": (
                    "irenaeus-parent-scope" if item is irenaeus else "sibling-anf-work-excluded"
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
                    if child.tag == "div2" and child.get("id") in SELECTED_BOOK_IDS
                    else "outside-against-heresies-book-scope"
                ),
            }
            for ordinal, child in enumerate(irenaeus, start=1)
            if isinstance(child.tag, str)
        ],
        "selected_book_ids": list(SELECTED_BOOK_IDS),
        "division_accounting": division_accounting,
        "selected_book_census": selected_book_census,
        "feature_count": len(rows),
        "attribute_count": attribute_count,
        "feature_counts": dict(sorted(counts.items())),
        "selected_direct_text_bytes": direct_text_bytes,
        "selected_tail_text_bytes": tail_text_bytes,
        "omitted_feature_count": 0,
        "duplicate_feature_count": 0,
        "unresolved_feature_count": 0,
        "crosswalk": rows,
    }
    provenance = {
        "contract": "ocd-anf01-irenaeus-provenance-v1",
        "status": "nonaccepted",
        "source_id": source_manifest.record["source_id"],
        "work_id": "irenaeus-against-heresies",
        "title": "Against Heresies",
        "author": "Irenaeus of Lyons",
        "source": {
            "path": SOURCE_PATH,
            "bytes": len(source_bytes),
            "sha256": SOURCE_SHA256,
            "parent_scope": "div1 ix",
            "selected_books": list(SELECTED_BOOK_IDS),
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
    unresolved = [
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
    readme = """# Irenaeus, Against Heresies — retained source reconstruction

This nonaccepted TEI candidate is reconstructed deterministically from the retained `raw/ccel/anf/anf01.xml` witness. The authoritative local-config scope is ANF1 `div1` ix and exactly the five Against Heresies book divisions `ix.ii`, `ix.iii`, `ix.iv`, `ix.vi`, and `ix.vii`.

The introductory note (`ix.i`), elucidation (`ix.v`), fragments (`ix.viii`), non-`div2` Irenaeus siblings, and all sibling ANF works (`div1` i–viii) are explicitly excluded and accounted. No excluded text is silently folded into the candidate.

The existing source config identifies Alexander Roberts and James Donaldson as editors and translators and A. Cleveland Coxe as American editor, identifies the 1885 ANF Volume I edition, labels the work public domain, and records that CCEL confirmed parsing is permitted. These are bound metadata claims, not a new human rights determination.

The candidate remains `accepted_ir:not_accepted`, `human_review:required`, and `publication:not_ready`. No canonical data or IR is written.
""".encode("utf-8")
    return {
        "content.tei.xml": etree.tostring(
            root, encoding="UTF-8", xml_declaration=True, pretty_print=False
        ),
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
