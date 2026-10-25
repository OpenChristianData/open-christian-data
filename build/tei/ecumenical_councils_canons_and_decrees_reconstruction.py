"""Entry-local faithful TEI reconstruction for source-to-TEI issue 37c-137."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.tei.writer import tei_el


CONVERTER_ID = "ocd-37c137-ecumenical-councils-to-tei"
CONVERTER_VERSION = "1"
PROFILE_ID = "ecumenical-councils-canons-and-decrees-npnf2-seven-roots-v1"
TEI_NS = "http://www.tei-c.org/ns/1.0"

SOURCES = (
    (
        "npnf214",
        "raw/ccel/npnf2/npnf214.xml",
        3_196_008,
        "4ae3cb29edcb7b8e58bb9246049243c464b6839f88f6730f98b80122770b9bb4",
    ),
)
ASSIGNED = (
    ("npnf214", "vii", "ecumenical-councils-canons-and-decrees"),
    ("npnf214", "ix", "ecumenical-councils-canons-and-decrees"),
    ("npnf214", "x", "ecumenical-councils-canons-and-decrees"),
    ("npnf214", "xi", "ecumenical-councils-canons-and-decrees"),
    ("npnf214", "xii", "ecumenical-councils-canons-and-decrees"),
    ("npnf214", "xiii", "ecumenical-councils-canons-and-decrees"),
    ("npnf214", "xvi", "ecumenical-councils-canons-and-decrees"),
)
TOP_LEVEL_IDS = (
    "i",
    "ii",
    "iii",
    "iv",
    "v",
    "vi",
    "vii",
    "viii",
    "ix",
    "x",
    "xi",
    "xii",
    "xiii",
    "xiv",
    "xv",
    "xvi",
    "xvii",
    "xviii",
)
EXPECTED_CENSUS = {
    "elements": 7_502,
    "attributes": 14_097,
    "text_nodes": 5_803,
    "tail_nodes": 6_027,
    "characters": 1_182_705,
    "non_ascii_characters": 15_505,
    "notes": 257,
    "page_breaks": 312,
    "scripture_refs": 57,
}
TAG_MAP = {
    "div1": "div",
    "div2": "div",
    "div3": "div",
    "div4": "div",
    "p": "p",
    "note": "note",
    "i": "hi",
    "span": "seg",
    "pb": "pb",
    "scripRef": "ref",
    "sup": "hi",
    "hr": "milestone",
    "img": "ref",
    "a": "ref",
}
CREDIT_IDS = ("i-p9", "i-p11", "i-p23", "ii-p14")
CREDIT_NAMES = ("Philip Schaff", "Henry Wace", "Henry R. Percival")


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
            remove_pis=False,
            huge_tree=True,
        ),
    )


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "-", value) or "source"


def _selector(node: etree._Element) -> str:
    parts: list[str] = []
    current: etree._Element | None = node
    while current is not None and current.tag != "ThML.body":
        parent = current.getparent()
        if parent is None or not isinstance(current.tag, str):
            break
        peers = [child for child in parent if child.tag == current.tag]
        parts.append(f"{current.tag}[{peers.index(current) + 1}]")
        current = parent
    return "ThML.body/" + "/".join(reversed(parts))


def _source_text(tree: etree._ElementTree, source_id: str) -> str:
    nodes = tree.xpath("//*[@id=$source_id]", source_id=source_id)
    if len(nodes) != 1:
        raise ValueError(f"retained credit evidence {source_id!r} drifted")
    return "".join(nodes[0].itertext())


def _source_metadata(tree: etree._ElementTree) -> dict[str, Any]:
    head = tree.getroot().find("ThML.head")
    if head is None:
        raise ValueError("retained source lacks ThML.head")
    return {
        "head_c14n_sha256": _sha(
            etree.tostring(head, method="c14n", with_comments=True)
        ),
        "dc_entries": [
            {
                "tag": node.tag,
                "attributes": dict(node.attrib),
                "text": node.text or "",
                "tail": node.tail or "",
            }
            for node in tree.xpath("/ThML/ThML.head/electronicEdInfo/DC/*")
        ],
        "print_source_entries": [
            {
                "tag": node.tag,
                "attributes": dict(node.attrib),
                "text": node.text or "",
                "tail": node.tail or "",
            }
            for node in tree.xpath("/ThML/ThML.head/printSourceInfo/*")
        ],
    }


def _document_accounting(tree: etree._ElementTree) -> dict[str, Any]:
    root = tree.getroot()
    before: list[dict[str, str]] = []
    node = root.getprevious()
    while node is not None:
        before.append(
            {
                "kind": "comment"
                if node.tag is etree.Comment
                else "processing-instruction",
                "text": node.text or "",
                "tail": node.tail or "",
            }
        )
        node = node.getprevious()
    before.reverse()
    after: list[dict[str, str]] = []
    node = root.getnext()
    while node is not None:
        after.append(
            {
                "kind": "comment"
                if node.tag is etree.Comment
                else "processing-instruction",
                "text": node.text or "",
                "tail": node.tail or "",
            }
        )
        node = node.getnext()
    return {
        "xml_version": tree.docinfo.xml_version,
        "encoding": tree.docinfo.encoding,
        "standalone": tree.docinfo.standalone,
        "doctype": tree.docinfo.doctype,
        "root_tag": root.tag,
        "root_attributes": dict(root.attrib),
        "root_namespace_declarations": {
            "" if key is None else key: value for key, value in root.nsmap.items()
        },
        "pre_root_nodes": before,
        "post_root_nodes": after,
    }


def _census(nodes: list[etree._Element]) -> dict[str, int]:
    elements = [node for node in nodes if isinstance(node.tag, str)]
    strings = [(node.text or "") + (node.tail or "") for node in nodes]
    return {
        "elements": len(elements),
        "attributes": sum(len(node.attrib) for node in elements),
        "text_nodes": sum(node.text is not None for node in nodes),
        "tail_nodes": sum(node.tail is not None for node in nodes),
        "characters": sum(len(value) for value in strings),
        "non_ascii_characters": sum(
            sum(ord(char) > 127 for char in value) for value in strings
        ),
        "notes": sum(node.tag == "note" for node in elements),
        "page_breaks": sum(node.tag == "pb" for node in elements),
        "scripture_refs": sum(node.tag == "scripRef" for node in elements),
    }


def _target_attrs(
    policy: Mapping[str, Any],
    source: etree._Element,
    ordinal: int,
    work_id: str | None,
) -> tuple[str, dict[str, str], str | None, list[dict[str, str]]]:
    rules = policy["projection"]
    tag = str(source.tag)
    target_tag = (
        "foreign"
        if tag == "span" and source.get("lang")
        else rules["tag_map"].get(tag)
    )
    if not isinstance(target_tag, str):
        raise ValueError(f"source element {tag!r} lacks declared projection")
    attrs = {
        "xml:id": rules["xml_id_template"].format(
            source_key="npnf214",
            ordinal=ordinal,
            source_id=_safe(source.get("id") or tag),
        )
    }
    dispositions: list[dict[str, str]] = []
    for name, value in source.attrib.items():
        destination = "source-accountability"
        method = "preserved-exactly-in-accountability"
        if name == "id":
            method = "deterministic-member-and-ordinal-prefix"
            destination = "@xml:id-and-source-accountability"
        else:
            rule = rules["attribute_rules"].get(name)
            if (
                isinstance(rule, Mapping)
                and tag in rule.get("source_tags", [])
                and not (rule.get("except_work_root") and work_id)
            ):
                destination = rule.get("disposition", "source-accountability")
                method = rule.get("method", method)
                if name == "href" and tag == "a":
                    destination = "@target"
        dispositions.append(
            {
                "source_attribute": name,
                "source_value": value,
                "destination": destination,
                "method": method,
            }
        )
    for name, value in source.attrib.items():
        if name == "id":
            continue
        rule = rules["attribute_rules"].get(name)
        if (
            not isinstance(rule, Mapping)
            or tag not in rule.get("source_tags", [])
            or (rule.get("except_work_root") and work_id)
        ):
            continue
        destination = rule.get("tei_attribute")
        if not destination:
            continue
        if name == "href" and tag == "a":
            destination = "target"
        if rule.get("value_map"):
            value = rule["value_map"].get(value, value.lower())
        if rule.get("append_prefix"):
            value = (attrs.get(destination, "") + rule["append_prefix"] + value).strip()
        attrs[destination] = value
    if work_id:
        attrs.update({"type": "work", "subtype": work_id})
    else:
        derived = rules["derived_attributes"]
        if tag.startswith("div") and "type" not in attrs:
            attrs["type"] = derived["division_type_template"].format(source_tag=tag)
        for rule in derived["by_source_tag"]:
            if tag == rule["source_tag"]:
                attrs.update(rule["attributes"])
        if tag == "span" and "lang" not in source.attrib:
            attrs.update(derived["plain_span_attributes"])
    wrapper = (
        rules["inline_wrapper_id_template"].format(ordinal=ordinal)
        if target_tag in rules["direct_div_inline_tags"]
        and source.getparent() is not None
        and str(source.getparent().tag).startswith("div")
        else None
    )
    return target_tag, attrs, wrapper, dispositions


def _append(
    policy: Mapping[str, Any],
    source: etree._Element,
    parent: etree._Element,
    rows: list[dict[str, Any]],
    parent_feature_id: str | None,
    source_root_id: str,
    work_id: str | None = None,
) -> None:
    if not isinstance(source.tag, str):
        raise ValueError("assigned source contains a non-element node")
    ordinal = len(rows) + 1
    target_tag, attrs, wrapper_id, dispositions = _target_attrs(
        policy, source, ordinal, work_id
    )
    target = tei_el(target_tag, attrs)
    target.text = source.text or ""
    target.tail = source.tail or ""
    title = source.get("title") if str(source.tag).startswith("div") else None
    if title is not None:
        target.insert(0, tei_el("head", text=title))
    if wrapper_id:
        wrapper = tei_el(
            "ab", {"xml:id": wrapper_id, "type": "source-inline-container"}
        )
        wrapper.append(target)
        parent.append(wrapper)
    else:
        parent.append(target)
    feature_id = f"ecumenical-councils-feature-{ordinal:06d}"
    rows.append(
        {
            "feature_id": feature_id,
            "parent_feature_id": parent_feature_id,
            "source_member": "npnf214",
            "source_selector": _selector(source),
            "source_tag": source.tag,
            "source_xml_id": source.get("id"),
            "source_attributes": dict(source.attrib),
            "direct_text_length": len(source.text or ""),
            "direct_text_sha256": _sha((source.text or "").encode()),
            "tail_text_length": len(source.tail or ""),
            "tail_text_sha256": _sha((source.tail or "").encode()),
            "source_title_head": title,
            "tei_tag": target_tag,
            "tei_xml_id": attrs["xml:id"],
            "tei_attributes": attrs,
            "tei_wrapper_id": wrapper_id,
            "attribute_dispositions": dispositions,
            "disposition": "represented",
            **({"work_id": work_id} if work_id else {}),
        }
    )
    for child in source:
        _append(
            policy,
            child,
            target,
            rows,
            feature_id,
            source_root_id,
        )


def _selected(tree: etree._ElementTree) -> list[tuple[etree._Element, str]]:
    body = tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError("retained source lacks ThML.body")
    result: list[tuple[etree._Element, str]] = []
    for _key, source_id, work_id in ASSIGNED:
        matches = [
            child
            for child in body
            if isinstance(child.tag, str)
            and child.tag == "div1"
            and child.get("id") == source_id
        ]
        if len(matches) != 1:
            raise ValueError(f"exact assigned root drift: npnf214 {source_id}")
        result.append((matches[0], work_id))
    return result


def _header(tree: etree._ElementTree) -> etree._Element:
    root = tei_el(
        "TEI", {"xml:id": "ecumenical-councils-canons-and-decrees-candidate"}
    )
    header = tei_el("teiHeader")
    file_desc = tei_el("fileDesc")
    title_stmt = tei_el("titleStmt")
    title = "".join(
        str(value)
        for value in tree.xpath(
            "/ThML/ThML.head/electronicEdInfo/DC/DC.Title[not(@sub)]/text()"
        )
    )
    title_stmt.append(
        tei_el("title", {"type": "retained-electronic-title", "n": "npnf214"}, title)
    )
    for name in CREDIT_NAMES:
        title_stmt.append(tei_el("editor", text=name))
    file_desc.append(title_stmt)
    publication = tei_el("publicationStmt")
    publication.append(
        tei_el(
            "publisher", text="Grand Rapids, MI: Christian Classics Ethereal Library"
        )
    )
    availability = tei_el("availability")
    availability.append(tei_el("p", text="Public Domain"))
    publication.append(availability)
    file_desc.append(publication)
    source_desc = tei_el("sourceDesc")
    list_bibl = tei_el("listBibl")
    bibl = tei_el("bibl", {"xml:id": "source-npnf214"})
    bibl.append(tei_el("title", text=title))
    for name in CREDIT_NAMES:
        bibl.append(tei_el("editor", text=name))
    published = "".join(
        str(value)
        for value in tree.xpath("/ThML/ThML.head/printSourceInfo/published/text()")
    )
    if published:
        bibl.append(tei_el("publisher", text=published))
    rights = "".join(
        str(value)
        for value in tree.xpath(
            "/ThML/ThML.head/electronicEdInfo/DC/DC.Rights/text()"
        )
    )
    bibl.append(tei_el("note", {"type": "rights"}, rights))
    url = "".join(
        str(value)
        for value in tree.xpath(
            "/ThML/ThML.head/electronicEdInfo/DC/DC.Identifier[@scheme='URL']/text()"
        )
    )
    bibl.append(tei_el("idno", {"type": "CCEL-path"}, url))
    for source_id in CREDIT_IDS:
        bibl.append(
            tei_el(
                "note",
                {
                    "type": "retained-title-page-or-preface-credit",
                    "source": f"#{source_id}",
                },
                _source_text(tree, source_id),
            )
        )
    list_bibl.append(bibl)
    source_desc.append(list_bibl)
    file_desc.append(source_desc)
    header.append(file_desc)
    root.append(header)
    return root


def _division_accounting(
    tree: etree._ElementTree, assigned_ids: set[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    body = tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError("retained source lacks ThML.body")
    top = []
    for ordinal, node in enumerate(
        [child for child in body if isinstance(child.tag, str)], 1
    ):
        assigned = node.get("id") in assigned_ids
        top.append(
            {
                "ordinal": ordinal,
                "tag": node.tag,
                "id": node.get("id"),
                "title": node.get("title", ""),
                "disposition": "assigned-work-root-represented"
                if assigned
                else "source-evidence-outside-work-projection",
                "reason": "complete subtree represented"
                if assigned
                else "title, prefatory, sibling, appendix, and index matter outside exact assigned work roots",
            }
        )
    direct = []
    for ordinal, node in enumerate(
        tree.xpath("/ThML/ThML.body/div1/div2"), 1
    ):
        parent_id = node.getparent().get("id")
        included = parent_id in assigned_ids
        direct.append(
            {
                "ordinal": ordinal,
                "parent_div1_id": parent_id,
                "id": node.get("id"),
                "title": node.get("title", ""),
                "disposition": "assigned-work-subtree-represented"
                if included
                else "outside-assigned-work-scope",
                "reason": "complete subtree represented in retained order"
                if included
                else "not a selected ecumenical-council root or descendant",
            }
        )
    return top, direct


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    scope = source_manifest.record["scope"]
    expected_roots = tuple(
        (key, source_id, work_id) for key, source_id, work_id in ASSIGNED
    )
    if (
        scope["source_member"] != "retained-npnf214"
        or tuple(tuple(item) for item in scope["assigned_roots_in_source_order"])
        != expected_roots
        or tuple(scope["excluded_top_level_roots"]) != tuple(
            item for item in TOP_LEVEL_IDS if item not in {root[1] for root in ASSIGNED}
        )
    ):
        raise ValueError("37c-137 source scope binding drift")
    key, logical_path, expected_bytes, expected_sha = SOURCES[0]
    config = json.loads(source_manifest.authority_path("work-config").read_bytes())
    if not isinstance(config, dict):
        raise ValueError("37c-137 work config is not a JSON object")
    if (
        config.get("source_file") != logical_path
        or config.get("source_hash") != f"sha256:{expected_sha}"
        or [
            (item.get("member"), item.get("id"), item.get("selector"))
            for item in config.get("source_roots", [])
        ]
        != [
            (source_key, source_id, f"ThML.body/div1[{TOP_LEVEL_IDS.index(source_id) + 1}]")
            for source_key, source_id, _work_id in ASSIGNED
        ]
    ):
        raise ValueError("37c-137 work config source binding drift")
    policy = config.get("validation_policy")
    readme = config.get("source_attribution_readme")
    if not isinstance(policy, Mapping) or not isinstance(readme, str):
        raise ValueError("37c-137 entry-local config lacks policy or attribution text")
    path = source_manifest.authority_path("retained-npnf214")
    content = path.read_bytes()
    if len(content) != expected_bytes or _sha(content) != expected_sha:
        raise ValueError("retained npnf214 authority drift")
    tree = _parse(path)
    selected = _selected(tree)
    assigned_nodes = [node for root, _work_id in selected for node in root.iter()]
    assigned_census = _census(assigned_nodes)
    if assigned_census != EXPECTED_CENSUS:
        raise ValueError(f"assigned source census drift: {assigned_census}")
    root = _header(tree)
    text = tei_el("text")
    body = tei_el("body", {"xml:id": "ecumenical-councils-canons-and-decrees-body"})
    text.append(body)
    root.append(text)
    rows: list[dict[str, Any]] = []
    work_bindings = []
    for source_root, work_id in selected:
        before = len(rows)
        _append(policy, source_root, body, rows, None, source_root.get("id") or "", work_id)
        work_bindings.append(
            {
                "work_id": work_id,
                "source_key": key,
                "source_member": logical_path,
                "source_root_id": source_root.get("id"),
                "source_root_selector": _selector(source_root),
                "feature_count": len(rows) - before,
            }
        )
    complete_census = _census(list(tree.getroot().iter()))
    top_accounting, direct_accounting = _division_accounting(
        tree, {source_id for _key, source_id, _work_id in ASSIGNED}
    )
    accountability = {
        "contract": "ocd-37c137-source-accountability-v1",
        "schema": "inline-entry-structural-contract-v1",
        "profile_id": PROFILE_ID,
        "assigned_work_count": len(ASSIGNED),
        "source_member_count": 1,
        "feature_count": len(rows),
        "attribute_count": assigned_census["attributes"],
        "omitted_feature_count": 0,
        "duplicate_feature_count": 0,
        "unresolved_feature_count": 0,
        "assigned_census": assigned_census,
        "member_accounting": [
            {
                "key": key,
                "path": logical_path,
                "bytes": expected_bytes,
                "sha256": expected_sha,
                "disposition": "included retained authority; selected ecumenical roots represented and all other member scope explicitly accounted outside projection",
                "document_accounting": _document_accounting(tree),
                "complete_document_census": complete_census,
                "assigned_scope_census": assigned_census,
                "excluded_scope_census": {
                    name: complete_census[name] - assigned_census[name]
                    for name in complete_census
                },
            }
        ],
        "top_level_division_accounting": {key: top_accounting},
        "direct_div2_accounting": {key: direct_accounting},
        "work_bindings": work_bindings,
        "crosswalk": rows,
    }
    provenance = {
        "contract": "ocd-37c137-provenance-v1",
        "status": "nonaccepted",
        "source_id": source_manifest.record["source_id"],
        "publication_state": "not_ready",
        "sources": {
            key: {
                "path": logical_path,
                "bytes": expected_bytes,
                "sha256": expected_sha,
                "metadata": _source_metadata(tree),
                "retained_title_page_and_preface_credit_evidence": {
                    source_id: _source_text(tree, source_id)
                    for source_id in CREDIT_IDS
                },
                "display_credit_names": list(CREDIT_NAMES),
            }
        },
        "works": [
            {
                **binding,
                "translation_credit": {
                    "status": "retained-source-level-credit",
                    "credited_to": list(CREDIT_NAMES),
                    "work_specific_allocation": None,
                },
                "human_review": "required",
                "accepted_ir": "not_accepted",
                "publication": "not_ready",
            }
            for binding in work_bindings
        ],
        "canonical_data_written": False,
        "canonical_ir_written": False,
    }
    unresolved = [
        {
            "id": "37c-137-work-specific-translation-allocation",
            "scope": "seven-selected-ecumenical-council-roots",
            "status": "unresolved",
            "evidence": "The retained title page credits Henry R. Percival as editor and credits Philip Schaff and Henry Wace as series editors; the preface says that translations were gathered from multiple sources and does not allocate a translator to each selected root.",
        },
        {
            "id": "37c-137-electronic-to-print-collation",
            "scope": "retained-npnf214-electronic-witness",
            "status": "unresolved",
            "evidence": "The retained CCEL ThML records the Edinburgh: T&T Clark source statement and the 1900 volume context, but this bounded review did not independently collate the electronic witness against the printed volume.",
        },
        {
            "id": "37c-137-rights-human-acceptance-publication",
            "scope": "seven-selected-ecumenical-council-roots",
            "status": "unresolved",
            "evidence": "The retained electronic header states Public Domain and CCEL permission evidence permits ThML parsing; technical verification is not human textual acceptance, a separate rights decision, durable IR admission, or publication authorization.",
        },
    ]
    return {
        "README.source.md": readme.encode("utf-8"),
        "content.tei.xml": etree.tostring(
            root, encoding="UTF-8", xml_declaration=True, pretty_print=False
        ),
        "provenance.json": _canonical(provenance),
        "source-accountability.json": _canonical(accountability),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()

__all__: tuple[str, ...] = ()
