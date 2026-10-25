"""Faithfully reconstruct the twenty LIB-045 NPNF204 works as one TEI candidate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.tei.writer import XML_ID, XML_LANG, stamp_header, tei_el


CONVERTER_ID = "ocd-npnf204-assigned-works-to-tei"
CONVERTER_VERSION = "2"
SOURCE_SHA256 = "bd625a0fa4f5ddd4b2fa13fcee753de8832ea4b316625e0e06454beb81cfa652"
SOURCE_PATH = "raw/ccel/npnf2/npnf204.xml"
ASSIGNED = (
    ("vi", "athanasius-against-the-heathen"),
    ("vii", "athanasius-on-the-incarnation"),
    ("viii", "athanasius-deposition-of-arius"),
    ("ix", "eusebius-letter-on-nicene-creed"),
    ("x", "athanasius-statement-of-faith"),
    ("xi", "athanasius-on-luke-10-22"),
    ("xii", "athanasius-encyclical-letter"),
    ("xiii", "athanasius-defence-against-the-arians"),
    ("xiv", "athanasius-defence-of-the-nicene-definition"),
    ("xv", "athanasius-defence-of-dionysius"),
    ("xvi", "athanasius-life-of-antony"),
    ("xvii", "athanasius-circular-to-bishops-of-egypt-and-libya"),
    ("xviii", "athanasius-apology-to-the-emperor"),
    ("xix", "athanasius-defence-of-his-flight"),
    ("xx", "athanasius-arian-history"),
    ("xxi", "athanasius-against-the-arians"),
    ("xxii", "athanasius-on-ariminum-and-seleucia"),
    ("xxiii", "athanasius-synodal-letter-to-antioch"),
    ("xxiv", "athanasius-synodal-letter-to-africa"),
    ("xxv", "athanasius-letters-and-chronicles"),
)
OUTSIDE_SCOPE = ("i", "ii", "iii", "iv", "v", "xxvi")
TAG_MAP = {
    "div1": "div",
    "div2": "div",
    "div3": "div",
    "div4": "div",
    "p": "p",
    "i": "hi",
    "note": "note",
    "span": "seg",
    "scripRef": "ref",
    "td": "cell",
    "tr": "row",
    "table": "table",
    "pb": "pb",
    "br": "lb",
    "sup": "hi",
}
EXPECTED_COUNTS = {
    "br": 25,
    "div1": 20,
    "div2": 44,
    "div3": 215,
    "div4": 142,
    "i": 6101,
    "note": 4707,
    "p": 8291,
    "pb": 581,
    "scripRef": 2676,
    "span": 2921,
    "sup": 15,
    "table": 6,
    "td": 966,
    "tr": 180,
}
EXPECTED_ATTRIBUTES = 57398
EXPECTED_TABLES = {"tables": 6, "rows": 180, "cells": 966}


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
    return re.sub(r"[^A-Za-z0-9_.-]", "-", value)


def _source_divisions(tree: etree._ElementTree) -> list[etree._Element]:
    body = tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError("retained NPNF204 source has no ThML.body")
    divisions = [
        node for node in body if isinstance(node.tag, str) and node.tag == "div1"
    ]
    expected = [*OUTSIDE_SCOPE[:5], *(scope for scope, _ in ASSIGNED), "xxvi"]
    if [node.get("id") for node in divisions] != expected:
        raise ValueError("retained NPNF204 div1 order or identity drifted")
    return divisions


def _source_text_by_id(tree: etree._ElementTree, source_id: str) -> str:
    nodes = tree.xpath(f"//*[@id='{source_id}']")
    if len(nodes) != 1:
        raise ValueError(f"retained NPNF204 source evidence {source_id!r} drifted")
    return "".join(nodes[0].itertext())


def _retained_credit_evidence(tree: etree._ElementTree) -> dict[str, str]:
    source_ids = (
        "i-p8",
        "i-p10",
        "i-p11",
        "i-p14",
        "ii-p3",
        "ii-p4",
        "ii-p5",
        "iii-p4",
        "iii-p6",
        "iv-p4",
        "iv-p11",
        "xvi.ii.i-p50",
        "xxii.i-p13",
        "xxiii.i-p9",
        "xxv.iii.i-p20",
    )
    evidence = {
        source_id: _source_text_by_id(tree, source_id) for source_id in source_ids
    }
    exact = {
        "i-p8": "TRANSLATED INTO ENGLISH WITH\nPROLEGOMENA AND EXPLANATORY NOTES.",
        "i-p10": "UNDER THE EDITORIAL SUPERVISION OF",
        "i-p11": "PHILIP SCHAFF, D.D., LL.D.,",
        "i-p14": "HENRY WACE, D.D.,",
        "iii-p4": "Edited, with Prolegomena,\nIndices, and Tables,",
        "iii-p6": "ARchibald Robertson",
    }
    if any(evidence[key] != value for key, value in exact.items()):
        raise ValueError("retained NPNF204 title-page evidence drifted")
    required = {
        "ii-p3": ("Mr. Robertson, the special editor",),
        "ii-p4": ("translation and notes of Cardinal Newman",),
        "ii-p5": ("Rev. J. H. Lupton", "reading the translations throughout"),
        "iv-p4": ("historical and anti-Arian works", "Cardinal) Newman"),
        "iv-p11": ("translation of the Life of Antony", "Miss Payne Smith"),
        "xvi.ii.i-p50": ("Rev. H. Ellershaw",),
        "xxii.i-p13": ("translation of this tract by Newman", "more closely revised"),
        "xxiii.i-p9": ("made independently", "carefully collated"),
        "xxv.iii.i-p20": ("revised by Miss Payne Smith",),
    }
    for source_id, phrases in required.items():
        if any(phrase not in evidence[source_id] for phrase in phrases):
            raise ValueError(f"retained NPNF204 credit evidence {source_id} drifted")
    return evidence


def _selector(node: etree._Element) -> str:
    parts: list[str] = []
    current: etree._Element | None = node
    while current is not None and current.tag != "ThML.body":
        if not isinstance(current.tag, str):
            break
        parent = current.getparent()
        if parent is None:
            break
        siblings = [
            child
            for child in parent
            if isinstance(child.tag, str) and child.tag == current.tag
        ]
        parts.append(f"{current.tag}[{siblings.index(current) + 1}]")
        current = parent
    return "ThML.body/" + "/".join(reversed(parts))


def _tei_attrs(
    source: etree._Element, feature_number: int
) -> tuple[dict[str, str], list[dict[str, str]]]:
    source_id = source.get("id")
    tei_id = "npnf204-" + (
        _safe_id(source_id) if source_id else f"feature-{feature_number:05d}"
    )
    attrs: dict[str, str] = {"xml:id": tei_id}
    dispositions: list[dict[str, str]] = []
    tag = str(source.tag)
    for name, value in source.attrib.items():
        destination = "source-accountability"
        method = "preserved-exactly"
        if name == "id":
            destination = "@xml:id"
            method = "deterministic-prefix"
        elif name == "n" and tag in {"div3", "div4", "note", "pb"}:
            attrs["n"] = value
            destination = "@n"
        elif name == "type" and tag in {"div3", "div4"}:
            attrs["type"] = value
            destination = "@type"
        elif name == "class":
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
            attrs["xml:lang"] = {"EL": "grc"}.get(value, value.lower())
            destination = "@xml:lang"
            method = "declared-language-code-map"
        elif name == "colspan" and tag == "td":
            attrs["cols"] = value
            destination = "@cols"
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
    elif tag == "sup":
        attrs["rend"] = "superscript"
    elif tag == "scripRef":
        attrs["type"] = "scripture"
    return attrs, dispositions


def _target_tag(source: etree._Element) -> str:
    if source.tag == "span" and source.get("lang"):
        return "foreign"
    return TAG_MAP[str(source.tag)]


def _append_source_node(
    source: etree._Element,
    tei_parent: etree._Element,
    rows: list[dict[str, object]],
    parent_feature_id: str | None,
) -> None:
    number = len(rows) + 1
    feature_id = f"npnf204-feature-{number:05d}"
    attrs, dispositions = _tei_attrs(source, number)
    target = tei_el(_target_tag(source), attrs)
    source_title = source.get("title") if str(source.tag).startswith("div") else None
    if source_title is not None:
        target.append(tei_el("head", text=source_title))
    target.text = source.text or ""
    target.tail = source.tail or ""
    child_ordinal = 1 + sum(1 for child in tei_parent if isinstance(child.tag, str))
    tei_parent.append(target)
    row: dict[str, object] = {
        "feature_id": feature_id,
        "source_selector": _selector(source),
        "source_tag": source.tag,
        "source_xml_id": source.get("id"),
        "attributes": dict(source.attrib),
        "direct_text": source.text or "",
        "tail_text": source.tail or "",
        "direct_text_sha256": _sha((source.text or "").encode("utf-8")),
        "tail_text_sha256": _sha((source.tail or "").encode("utf-8")),
        "tei_tag": _target_tag(source),
        "tei_xml_id": target.get(XML_ID),
        "tei_parent_id": tei_parent.get(XML_ID),
        "tei_child_ordinal": child_ordinal,
        "tei_attributes": {
            (
                "xml:id" if key == XML_ID else "xml:lang" if key == XML_LANG else key
            ): value
            for key, value in target.attrib.items()
        },
        "attribute_dispositions": dispositions,
        "disposition": "represented",
        "tei_selector": f"#{target.get(XML_ID)}",
        "parent_feature_id": parent_feature_id,
        "source_title_head": source_title,
    }
    rows.append(row)
    for child in source:
        if not isinstance(child.tag, str):
            raise ValueError(
                "assigned NPNF204 scope unexpectedly contains a comment or PI"
            )
        if child.tag not in TAG_MAP:
            raise ValueError(f"unsupported retained source element {child.tag!r}")
        _append_source_node(child, target, rows, feature_id)


def _work_credit(scope: str) -> dict[str, object]:
    if scope == "xvi":
        return {
            "status": "retained-explicit",
            "credited_to": "H. Ellershaw",
            "role": "translator",
            "source_xml_ids": ["iv-p11", "xvi.ii.i-p50"],
        }
    if scope == "xxii":
        return {
            "status": "retained-explicit",
            "credited_to": "John Henry Newman",
            "role": "translator; translation more closely revised for this edition",
            "source_xml_ids": ["ii-p4", "iv-p4", "xxii.i-p13"],
        }
    if scope in {"xxiii", "xxiv"}:
        return {
            "status": "retained-explicit-anonymous",
            "credited_to": None,
            "role": "translation independently made and collated with Bright",
            "source_xml_ids": ["xxiii.i-p9"],
        }
    if scope == "xxv":
        return {
            "status": "retained-component-level",
            "credited_to": "Miss Payne Smith",
            "role": "reviser of the Oxford translation of the bulk of the Festal Letters",
            "source_xml_ids": ["iv-p11", "xxv.iii.i-p20"],
        }
    return {
        "status": "unresolved",
        "credited_to": None,
        "role": None,
        "source_xml_ids": [],
    }


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    source = source_manifest.authority_path("retained-thml")
    source_bytes = source.read_bytes()
    if _sha(source_bytes) != SOURCE_SHA256:
        raise ValueError("retained NPNF204 authority digest mismatch")
    tree = _parse(source)
    divisions = _source_divisions(tree)
    selected = divisions[5:25]
    credit_evidence = _retained_credit_evidence(tree)

    root = tei_el("TEI", {"xml:id": "npnf204-lib045"})
    root.append(
        stamp_header(
            title="NPNF2-04. Athanasius: Select Works and Letters — assigned works vi–xxv",
            author="Athanasius of Alexandria and Eusebius of Caesarea",
            contributors=[
                {"name": "Philip Schaff", "role": "editorial supervisor"},
                {"name": "Henry Wace", "role": "editorial supervisor"},
                {
                    "name": "Archibald Robertson",
                    "role": "special editor; prolegomena, indices, and tables",
                },
                {"name": "J. H. Lupton", "role": "translation reader"},
                {"name": "H. Ellershaw", "role": "translator of Life of Antony"},
                {
                    "name": "John Henry Newman",
                    "role": "translator whose earlier translations were revised where retained evidence specifies",
                },
                {
                    "name": "Miss Payne Smith",
                    "role": "reviser of the Oxford translation of the bulk of the Festal Letters",
                },
            ],
            source_url="https://www.ccel.org/ccel/schaff/npnf204.xml",
            source_sha256=SOURCE_SHA256,
            print_source="NPNF Second Series, Volume IV: Athanasius: Select Works and Letters (retained title pages; no print collation)",
            rights_statement="The local source configs label the underlying texts public domain. CCEL permits parsing its ThML; do not sell CCEL files or derivatives of CCEL formatting. Attribution is included in README.source.md. Human acceptance and publication remain absent.",
        )
    )
    text = tei_el("text")
    body = tei_el("body", {"xml:id": "npnf204-assigned-body"})
    text.append(body)
    root.append(text)
    rows: list[dict[str, object]] = []
    for source_div, (scope, work_id) in zip(selected, ASSIGNED, strict=True):
        if source_div.get("id") != scope:
            raise ValueError("assigned NPNF204 scope order drifted")
        before = len(rows)
        _append_source_node(source_div, body, rows, None)
        rows[before]["work_id"] = work_id

    counts: dict[str, int] = {}
    attribute_count = 0
    for row in rows:
        source_tag = str(row["source_tag"])
        counts[source_tag] = counts.get(source_tag, 0) + 1
        attribute_count += len(row["attributes"])
    if (
        len(rows) != 26890
        or counts != EXPECTED_COUNTS
        or attribute_count != EXPECTED_ATTRIBUTES
    ):
        raise ValueError(
            f"assigned NPNF204 source inventory drifted: {len(rows)} {attribute_count} {counts}"
        )

    mapping = dict(ASSIGNED)
    division_accounting = [
        {
            "ordinal": ordinal,
            "div1_id": str(div.get("id")),
            "title": div.get("title", ""),
            "disposition": (
                "assigned-work-represented"
                if div.get("id") in mapping
                else "outside-assigned-work-scope"
            ),
            "work_id": mapping.get(str(div.get("id"))),
        }
        for ordinal, div in enumerate(divisions, start=1)
    ]
    accountability = {
        "contract": "ocd-npnf204-source-accountability-v1",
        "schema": "athanasius-table.source-accountability.schema.json",
        "profile_id": "npnf204-assigned-div1-vi-through-xxv-v1",
        "source_scope": "retained ThML.body div1 vi through xxv",
        "source_member": {
            "path": SOURCE_PATH,
            "bytes": len(source_bytes),
            "sha256": SOURCE_SHA256,
            "disposition": "included as the sole retained member",
        },
        "document_accounting": {
            "xml_declaration": '<?xml version="1.0" encoding="UTF-8"?>',
            "doctype": '<!DOCTYPE ThML PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">',
            "pre_root_comment": " Copyright Christian Classics Ethereal Library ",
            "pre_root_comment_disposition": "retained witness evidence outside assigned work scope",
            "assigned_comment_count": 0,
            "assigned_processing_instruction_count": 0,
        },
        "assigned_work_count": 20,
        "feature_count": len(rows),
        "attribute_count": attribute_count,
        "feature_counts": counts,
        "omitted_feature_count": 0,
        "duplicate_feature_count": 0,
        "unresolved_feature_count": 0,
        "table_census": EXPECTED_TABLES,
        "preserved_table_route": {
            "div1_id": "vii",
            "feature_count": sum(
                1
                for row in rows
                if str(row["source_selector"]).startswith("ThML.body/div1[7]")
            ),
            "table_id": "vii.i-p19.1",
            "tables": 1,
            "rows": 55,
            "cells": 165,
        },
        "division_accounting": division_accounting,
        "crosswalk": rows,
    }
    provenance = {
        "contract": "ocd-npnf204-provenance-v1",
        "status": "nonaccepted",
        "source_id": source_manifest.record["source_id"],
        "source": {
            "path": SOURCE_PATH,
            "sha256": SOURCE_SHA256,
            "scope": "div1 vi through xxv",
        },
        "works": [
            {
                "ordinal": ordinal,
                "div1_id": scope,
                "work_id": work_id,
                "source_title": selected[ordinal - 1].get("title", ""),
                "author": (
                    "Eusebius of Caesarea"
                    if scope == "ix"
                    else "Athanasius of Alexandria"
                ),
                "translation_credit": _work_credit(scope),
                "accepted_ir": "not_accepted",
                "human_review": "required",
                "publication": "not_ready",
            }
            for ordinal, (scope, work_id) in enumerate(ASSIGNED, start=1)
        ],
        "edition": {
            "title": "Athanasius: Select Works and Letters",
            "series": "A Select Library of the Nicene and Post-Nicene Fathers of the Christian Church, Second Series, Volume IV",
            "editorial_supervision": ["Philip Schaff", "Henry Wace"],
            "special_editor": "Archibald Robertson",
            "special_editor_roles": ["editor", "prolegomena", "indices", "tables"],
            "source_identifier": "https://www.ccel.org/ccel/schaff/npnf204.xml",
            "print_collation": "not-performed",
        },
        "credit_evidence": credit_evidence,
        "rights": {
            "local_config_claim": "public-domain",
            "ccel_permission": "parsing permitted; do not sell CCEL files or derivatives of CCEL formatting",
            "attribution": "sourced via CCEL.org",
            "human_acceptance": "absent",
            "publication_state": "not_ready",
        },
        "canonical_data_written": False,
        "canonical_ir_written": False,
    }
    unresolved = [
        {
            "id": "npnf204-work-specific-translation-allocation",
            "scope": "assigned works except exact retained allocations",
            "status": "unresolved",
            "question": "Which translator or reviser applies to each assigned work or component not explicitly allocated by retained evidence?",
            "evidence": "The retained preface describes mixed new and revised translations but only safely names exact allocations for Life of Antony, de Synodis, the anonymous Antioch/Africa group, and Festal Letter components.",
        },
        {
            "id": "npnf204-print-collation-not-performed",
            "scope": "edition",
            "status": "unresolved",
            "question": "Does the retained CCEL witness differ substantively from the print edition identified by its retained title pages?",
            "evidence": "The candidate is bound to retained CCEL XML; no print collation was performed.",
        },
        {
            "id": "npnf204-rights-human-acceptance-and-publication",
            "scope": "all-20-assigned-works",
            "status": "unresolved",
            "question": "Will a maintainer accept these candidates and separately authorize publication after rights review?",
            "evidence": "Technical verification is not human textual acceptance, a rights decision, or publication authorization.",
        },
    ]
    readme = """# NPNF2-04 assigned-work reconstruction source

This nonaccepted TEI candidate is reconstructed deterministically from the retained `raw/ccel/npnf2/npnf204.xml` member. It represents exactly the twenty assigned `div1` scopes vi through xxv. The retained title page, editorial front matter, prolegomena, and index divisions i through v and xxvi are outside assigned work scope and are explicitly accounted as exclusions; their primary metadata and contributor evidence is recorded in the review packet.

The retained title page places the series under the editorial supervision of Philip Schaff and Henry Wace. It identifies Archibald Robertson as editor with prolegomena, indices, and tables. The retained editorial preface credits J. H. Lupton with reading the translations throughout. Work-level credit is not inferred: H. Ellershaw is explicitly credited for the Life of Antony; Newman's de Synodis translation is explicitly said to have been more closely revised; the Antioch/Africa group is described as independently translated and collated with Bright without naming its translator; and Miss Payne Smith revised the Oxford translation of the bulk of the Festal Letters.

The retained electronic edition is sourced via [CCEL.org](https://www.ccel.org/ccel/schaff/npnf204.xml). CCEL permits parsing its ThML; do not sell CCEL files or derivatives of CCEL formatting. Local source configs label the underlying texts public domain. These statements remain evidence rather than a human rights or publication decision.

All twenty works remain `accepted_ir:not_accepted`, `human_review:required`, and `publication:not_ready`. Human textual acceptance and publication authorization are separate and absent.
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
