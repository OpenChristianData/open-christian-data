"""Producer-independent retained-source oracle for LIB-048."""

from __future__ import annotations

import ast
import hashlib
import io
import json
from pathlib import Path
import platform
import re
import sys
from typing import Any, Mapping

import jsonschema
from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-npnf2-lib048-source-to-tei-oracle"
ORACLE_VERSION = "2"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
MEMBERS = {
    "README.source.md",
    "content.tei.xml",
    "manifest.json",
    "provenance.json",
    "source-accountability.json",
    "unresolved.jsonl",
}
SOURCES = (
    (
        "npnf206",
        "retained-npnf206",
        "raw/ccel/npnf2/npnf206.xml",
        4_444_300,
        "6bf37affb240f5a775995ab2353c00569b34990130c98649a358f30f37f41f8d",
    ),
    (
        "npnf209",
        "retained-npnf209",
        "raw/ccel/npnf2/npnf209.xml",
        3_088_610,
        "b07e2fac0851444a42d2bbd11d39eb7384c518f6fd79e64b7f7bdc404e8a3cc7",
    ),
    (
        "npnf212",
        "retained-npnf212",
        "raw/ccel/npnf2/npnf212.xml",
        3_461_929,
        "f701b4ce5196bc5890e50adabce4900cd07b803f3221115a7cce526ae0a95570",
    ),
    (
        "npnf213",
        "retained-npnf213",
        "raw/ccel/npnf2/npnf213.xml",
        2_246_124,
        "323ecfb6470854de378fdf47375b2e15b108e72559bbe3167da9c37500bbf2ae",
    ),
)
ASSIGNED = (
    ("npnf206", "v", "jerome-letters"),
    ("npnf206", "vi.i", "jerome-life-of-paulus"),
    ("npnf206", "vi.ii", "jerome-life-of-hilarion"),
    ("npnf206", "vi.iii", "jerome-life-of-malchus"),
    ("npnf206", "vi.iv", "jerome-dialogue-against-luciferians"),
    ("npnf206", "vi.v", "jerome-perpetual-virginity-of-mary"),
    ("npnf206", "vi.vi", "jerome-against-jovinianus"),
    ("npnf206", "vi.vii", "jerome-against-vigilantius"),
    ("npnf206", "vi.viii", "jerome-to-pammachius-against-john-of-jerusalem"),
    ("npnf206", "vi.ix", "jerome-against-pelagians"),
    ("npnf209", "ii", "hilary-of-poitiers-select-works"),
    ("npnf209", "iii", "john-of-damascus-orthodox-faith"),
    ("npnf212", "ii", "leo-the-great-letters-and-sermons"),
    ("npnf212", "iii", "gregory-the-great-pastoral-rule-and-epistles"),
    ("npnf213", "ii", "gregory-the-great-selected-epistles"),
)
EXPECTED_CENSUS = {
    "elements": 53_294,
    "attributes": 115_741,
    "text_nodes": 39_394,
    "tail_nodes": 39_005,
    "characters": 7_718_481,
    "non_ascii_characters": 48_481,
    "notes": 10_138,
    "page_breaks": 1_542,
    "scripture_refs": 7_082,
}
IMAGE_ASSET = {
    "asset_id": "lib048-asset-npnf212-iii.iii-p86.1",
    "authority_name": "gregory-pedigree-image",
    "work_id": "gregory-the-great-pastoral-rule-and-epistles",
    "source_root_id": "iii",
    "source_member": "npnf212",
    "source_xml_id": "iii.iii-p86.1",
    "source_page": "https://ccel.org/ccel/schaff/npnf212/npnf212.iii.iii.html",
    "source_path": "raw/ccel/npnf2/npnf212/files/fig1.png",
    "source_url": "https://ccel.org/ccel/schaff/npnf212/files/fig1.png",
    "media_type": "image/png",
    "alt": "Pedigree of Kings of Gaul",
    "bytes": 44_462,
    "sha256": "a06e1fa626deadbfa78c1390ccd63408b7eea2a720c5b4542eda9e999cc616b5",
    "acquisition_receipt_path": "plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-10-structural-audit/14-gregory-asset-acquisition.json",
    "acquisition_receipt_sha256": "4df83db9cf9c3e3f06066a36e62f75e3b110be89c7bef6a47fe6576723941adc",
    "acquired_at": "2026-09-10T11:25:44.179665+00:00",
    "historical_snapshot_bytes": "unknown",
}
CREDIT_IDS = {
    "npnf206": ("ii-p2", "ii-p4", "ii-p7", "ii-p10", "iii-p4", "iii-p7"),
    "npnf209": (
        "ii.i-p3",
        "ii.i-p5",
        "ii.i-p7",
        "ii.i-p12",
        "iii.i-p3",
        "iii.i-p5",
        "iii.ii-p4",
    ),
    "npnf212": ("ii.i-p6", "ii.i-p8", "iii.i-p8", "iii.i-p10"),
    "npnf213": ("ii.i-p6", "ii.i-p8"),
}
CREDIT_NAMES = {
    "npnf206": ["W. H. Fremantle", "G. Lewis", "W. G. Martley"],
    "npnf209": [
        "E. W. Watson",
        "L. Pullan",
        "W. Sanday",
        "S. D. F. Salmond",
        "James L. Salmond",
    ],
    "npnf212": ["Charles Lett Feltoe", "James Barmby"],
    "npnf213": ["James Barmby"],
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {label}") from exc
    if not isinstance(value, dict) or _canonical(value) != content:
        raise ValueError(f"{label} is not a canonical JSON object")
    return value


def _authority_json(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {label}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object")
    return value


def _source_tree(content: bytes) -> etree._ElementTree:
    return etree.parse(
        io.BytesIO(content),
        etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            remove_comments=False,
            remove_pis=False,
            huge_tree=True,
        ),
    )


def _tei_tree(content: bytes) -> etree._ElementTree:
    try:
        return etree.ElementTree(
            etree.fromstring(
                content,
                etree.XMLParser(
                    resolve_entities=False,
                    no_network=True,
                    remove_comments=False,
                    remove_pis=False,
                    huge_tree=True,
                ),
            )
        )
    except etree.XMLSyntaxError as exc:
        raise ValueError("candidate TEI is not well formed") from exc


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
    before = []
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
    after = []
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


def _selector(node: etree._Element) -> str:
    parts = []
    current: etree._Element | None = node
    while current is not None and current.tag != "ThML.body":
        parent = current.getparent()
        if parent is None or not isinstance(current.tag, str):
            break
        peers = [child for child in parent if child.tag == current.tag]
        parts.append(f"{current.tag}[{peers.index(current) + 1}]")
        current = parent
    return "ThML.body/" + "/".join(reversed(parts))


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "-", value) or "source"


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


def _normalized_attrs(node: etree._Element) -> dict[str, str]:
    return {
        "xml:id"
        if key == f"{{{XML_NS}}}id"
        else "xml:lang"
        if key == f"{{{XML_NS}}}lang"
        else key: value
        for key, value in node.attrib.items()
    }


def _neutral_reference_inventory(
    policy: Mapping[str, Any],
    selected: list[tuple[str, etree._Element, str]],
) -> dict[tuple[str, str, str], str]:
    try:
        entries = policy["projection"]["reference_classification"][
            "neutral_non_scripture_exceptions"
        ]
    except (KeyError, TypeError) as exc:
        raise ValueError("reference classification policy is incomplete") from exc
    if not isinstance(entries, list) or len(entries) != 31:
        raise ValueError("reference classification policy must declare 31 exceptions")
    roots = {
        (key, root.get("id")): root
        for key, root, _work_id in selected
        if root.get("id")
    }
    inventory: dict[tuple[str, str, str], str] = {}
    required = {"source_member", "source_root_id", "source_xml_id", "passage"}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != required:
            raise ValueError("reference classification exception shape drift")
        if not all(isinstance(entry[name], str) for name in required):
            raise ValueError("reference classification exception value drift")
        if not entry["passage"].startswith("Ep."):
            raise ValueError("reference classification exception binding drift")
        root = roots.get((entry["source_member"], entry["source_root_id"]))
        if root is None:
            raise ValueError("reference classification exception root drift")
        matches = root.xpath(
            ".//scripRef[@id=$source_id]", source_id=entry["source_xml_id"]
        )
        if len(matches) != 1:
            raise ValueError("reference classification exception node drift")
        node = matches[0]
        if (
            node.get("passage") != entry["passage"]
            or node.get("osisRef") is not None
            or set(node.attrib) != {"id", "passage"}
        ):
            raise ValueError(
                "reference classification exception source drift at "
                f"{_selector(node)}"
            )
        key = (
            entry["source_member"],
            entry["source_root_id"],
            entry["source_xml_id"],
        )
        if key in inventory:
            raise ValueError("duplicate reference classification exception")
        inventory[key] = entry["passage"]
    return inventory


def _projection(
    policy: Mapping[str, Any],
    source: etree._Element,
    key: str,
    ordinal: int,
    work_id: str | None,
    source_root_id: str,
    reference_exceptions: Mapping[tuple[str, str, str], str],
) -> tuple[str, dict[str, str], str | None]:
    rules = policy["projection"]
    tag = str(source.tag)
    target_tag = (
        rules["language_span_tag"]
        if tag == "span" and source.get("lang")
        else rules["tag_map"].get(tag)
    )
    if not isinstance(target_tag, str):
        raise ValueError(f"source element {tag!r} lacks declared projection")
    exception_key = (key, source_root_id, source.get("id") or "")
    neutral_passage = reference_exceptions.get(exception_key)
    neutral_reference = neutral_passage is not None
    if neutral_reference and (
        source.get("passage") != neutral_passage
        or source.get("osisRef") is not None
        or set(source.attrib) != {"id", "passage"}
    ):
        raise ValueError(
            "reference classification exception source drift at "
            f"{_selector(source)}"
        )
    attrs = {
        "xml:id": rules["xml_id_template"].format(
            source_key=key, ordinal=ordinal, source_id=_safe(source.get("id") or tag)
        )
    }
    for name, value in source.attrib.items():
        rule = rules["attribute_rules"].get(name)
        if not rule or tag not in rule.get("source_tags", []):
            continue
        if rule.get("except_work_root") and work_id:
            continue
        destination = rule.get("tei_attribute")
        if not destination:
            continue
        if rule.get("value_map"):
            value = rule["value_map"].get(value, value.lower())
        if rule.get("append_prefix"):
            value = (attrs.get(destination, "") + rule["append_prefix"] + value).strip()
        if not (
            neutral_reference
            and tag == "scripRef"
            and name in {"passage", "osisRef"}
        ):
            attrs[destination] = value
    if work_id:
        attrs.update({"type": "work", "subtype": work_id})
    else:
        derived = rules["derived_attributes"]
        if tag.startswith("div") and "type" not in attrs:
            attrs["type"] = derived["division_type_template"].format(source_tag=tag)
        for rule in derived["by_source_tag"]:
            if tag == rule["source_tag"] and not (
                neutral_reference and tag == "scripRef"
            ):
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
    return target_tag, attrs, wrapper


def _selected(
    trees: Mapping[str, etree._ElementTree],
) -> list[tuple[str, etree._Element, str]]:
    result = []
    for key, source_id, work_id in ASSIGNED:
        matches = trees[key].xpath("//*[@id=$source_id]", source_id=source_id)
        if len(matches) != 1:
            raise ValueError(
                f"source root omission, duplication, or wrong binding: {key} {source_id}"
            )
        result.append((key, matches[0], work_id))
    return result


def _expected_rows(
    selected: list[tuple[str, etree._Element, str]],
    policy: Mapping[str, Any],
    reference_exceptions: Mapping[tuple[str, str, str], str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def visit(
        key: str,
        node: etree._Element,
        parent_feature_id: str | None,
        work_id: str | None = None,
        source_root_id: str | None = None,
    ) -> None:
        if not isinstance(node.tag, str):
            raise ValueError("assigned source contains non-element")
        ordinal = len(rows) + 1
        feature_id = f"lib048-feature-{ordinal:06d}"
        if source_root_id is None:
            raise ValueError("reference classification context is required")
        neutral_reference = (
            key,
            source_root_id,
            node.get("id") or "",
        ) in reference_exceptions
        tag, attrs, wrapper = _projection(
            policy,
            node,
            key,
            ordinal,
            work_id,
            source_root_id,
            reference_exceptions,
        )
        dispositions = []
        for name, value in node.attrib.items():
            destination, method = (
                "source-accountability",
                "preserved-exactly-in-accountability",
            )
            rule = policy["projection"]["attribute_rules"].get(name)
            if name == "id":
                destination, method = (
                    "@xml:id-and-source-accountability",
                    "deterministic-member-and-ordinal-prefix",
                )
            elif (
                rule
                and str(node.tag) in rule.get("source_tags", [])
                and not (rule.get("except_work_root") and work_id)
                and not (
                    str(node.tag) == "scripRef"
                    and name in {"passage", "osisRef"}
                    and neutral_reference
                )
            ):
                destination, method = (
                    rule.get("disposition", "source-accountability"),
                    rule.get("method", method),
                )
            dispositions.append(
                {
                    "source_attribute": name,
                    "source_value": value,
                    "destination": destination,
                    "method": method,
                }
            )
        row = {
            "feature_id": feature_id,
            "parent_feature_id": parent_feature_id,
            "source_member": key,
            "source_selector": _selector(node),
            "source_tag": node.tag,
            "source_xml_id": node.get("id"),
            "source_attributes": dict(node.attrib),
            "direct_text_length": len(node.text or ""),
            "direct_text_sha256": _sha((node.text or "").encode()),
            "tail_text_length": len(node.tail or ""),
            "tail_text_sha256": _sha((node.tail or "").encode()),
            "source_title_head": node.get("title")
            if str(node.tag).startswith("div")
            else None,
            "tei_tag": tag,
            "tei_xml_id": attrs["xml:id"],
            "tei_attributes": attrs,
            "tei_wrapper_id": wrapper,
            "attribute_dispositions": dispositions,
            "disposition": "represented",
            **({"work_id": work_id} if work_id else {}),
        }
        rows.append(row)
        for child in node:
            visit(key, child, feature_id, source_root_id=source_root_id)

    for key, root, work_id in selected:
        visit(key, root, None, work_id, root.get("id"))
    return rows


def _verify_node(
    source: etree._Element,
    target: etree._Element,
    key: str,
    policy: Mapping[str, Any],
    counter: list[int],
    work_id: str | None = None,
    source_root_id: str | None = None,
    reference_exceptions: Mapping[tuple[str, str, str], str] | None = None,
) -> None:
    if source_root_id is None or reference_exceptions is None:
        raise ValueError("reference classification context is required")
    counter[0] += 1
    tag, attrs, wrapper = _projection(
        policy,
        source,
        key,
        counter[0],
        work_id,
        source_root_id,
        reference_exceptions,
    )
    if target.tag != f"{{{TEI_NS}}}{tag}" or _normalized_attrs(target) != attrs:
        raise ValueError(f"TEI tag or attribute drift at {_selector(source)}")
    if (target.text or "") != (source.text or "") or (target.tail or "") != (
        source.tail or ""
    ):
        raise ValueError(f"TEI direct text or tail drift at {_selector(source)}")
    children = list(target)
    index = 0
    title = source.get("title") if str(source.tag).startswith("div") else None
    if title is not None:
        if (
            not children
            or children[0].tag != f"{{{TEI_NS}}}head"
            or children[0].text != title
            or children[0].tail
            or children[0].attrib
            or len(children[0])
        ):
            raise ValueError("division head drift")
        index = 1
    if source.tag == "img":
        if (
            len(children) != 2
            or children[0].tag != f"{{{TEI_NS}}}graphic"
            or _normalized_attrs(children[0]) != {"url": source.get("src", "")}
            or children[0].text
            or children[0].tail
            or len(children[0])
            or children[1].tag != f"{{{TEI_NS}}}figDesc"
            or _normalized_attrs(children[1])
            or children[1].text != (source.get("alt") or "")
            or children[1].tail
            or len(children[1])
        ):
            raise ValueError("TEI source image figure drift")
        return
    for source_child in source:
        if index >= len(children):
            raise ValueError("TEI source child omitted")
        candidate_child = children[index]
        child_ordinal = counter[0] + 1
        _tag, _attrs, child_wrapper = _projection(
            policy,
            source_child,
            key,
            child_ordinal,
            None,
            source_root_id,
            reference_exceptions,
        )
        if child_wrapper:
            if (
                candidate_child.tag != f"{{{TEI_NS}}}ab"
                or _normalized_attrs(candidate_child)
                != {"xml:id": child_wrapper, "type": "source-inline-container"}
                or candidate_child.text
                or candidate_child.tail
                or len(candidate_child) != 1
            ):
                raise ValueError("TEI inline wrapper drift")
            candidate_child = candidate_child[0]
        _verify_node(
            source_child,
            candidate_child,
            key,
            policy,
            counter,
            source_root_id=source_root_id,
            reference_exceptions=reference_exceptions,
        )
        index += 1
    if index != len(children):
        raise ValueError("TEI omission, duplication, or invention")


def _division_accounting(
    tree: etree._ElementTree, assigned_ids: set[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    body = tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError("retained source lacks body")
    top = []
    for ordinal, node in enumerate(
        [child for child in body if isinstance(child.tag, str)], 1
    ):
        assigned = node.get("id") in assigned_ids
        descendant = any(
            child.get("id") in assigned_ids for child in node.iterdescendants()
        )
        top.append(
            {
                "ordinal": ordinal,
                "tag": node.tag,
                "id": node.get("id"),
                "title": node.get("title", ""),
                "disposition": "assigned-work-root-represented"
                if assigned
                else "container-with-assigned-descendants"
                if descendant
                else "source-evidence-outside-work-projection",
                "reason": "complete subtree represented"
                if assigned
                else "container shell retained; assigned descendants represented separately"
                if descendant
                else "title/front/prefatory/sibling/index matter outside exact assigned work roots",
            }
        )
    direct = []
    for ordinal, node in enumerate(tree.xpath("//ThML.body/div1/div2"), 1):
        included = node.get("id") in assigned_ids or any(
            ancestor.get("id") in assigned_ids for ancestor in node.iterancestors()
        )
        direct.append(
            {
                "ordinal": ordinal,
                "parent_div1_id": node.getparent().get("id"),
                "id": node.get("id"),
                "title": node.get("title", ""),
                "disposition": "assigned-work-subtree-represented"
                if included
                else "outside-assigned-work-scope",
                "reason": "complete subtree represented in retained order"
                if included
                else "not an assigned root or descendant",
            }
        )
    return top, direct


def _verify_header(
    tei: etree._ElementTree, policy: Mapping[str, Any]
) -> etree._Element:
    root = tei.getroot()
    expected = policy["tei_topology"]
    if (
        root.tag != f"{{{TEI_NS}}}TEI"
        or _normalized_attrs(root) != expected["root_attributes"]
        or root.text
        or root.tail
        or root.getprevious() is not None
        or root.getnext() is not None
    ):
        raise ValueError("TEI root topology drift")
    children = list(root)
    if (
        len(children) != 2
        or any(not isinstance(child.tag, str) for child in children)
        or [etree.QName(child).localname for child in children] != ["teiHeader", "text"]
    ):
        raise ValueError("TEI root child invention or omission")
    header, text = children
    if (
        _sha(etree.tostring(header, method="c14n", with_comments=True))
        != expected["header_c14n_sha256"]
    ):
        raise ValueError("TEI header metadata, rights, credit, or topology drift")
    text_children = list(text)
    if (
        header.tail
        or text.text
        or text.tail
        or _normalized_attrs(text)
        or len(text_children) != 1
        or not isinstance(text_children[0].tag, str)
        or etree.QName(text_children[0]).localname != "body"
    ):
        raise ValueError("TEI text topology drift")
    body = text_children[0]
    if _normalized_attrs(body) != expected["body_attributes"] or body.text or body.tail:
        raise ValueError("TEI body topology drift")
    return body


def _expected_image_binding(
    source_manifest: SourceManifest,
    selected: list[tuple[str, etree._Element, str]],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Independently verify the retained image bytes and source placement."""

    image_nodes = [
        (key, work_id, node)
        for key, root, work_id in selected
        for node in root.iter("img")
    ]
    if len(image_nodes) != 1:
        raise ValueError(f"assigned source image inventory drift: {len(image_nodes)}")
    key, work_id, source = image_nodes[0]
    expected_source_attrs = {
        "id": IMAGE_ASSET["source_xml_id"],
        "src": IMAGE_ASSET["source_url"].removeprefix("https://ccel.org"),
        "alt": IMAGE_ASSET["alt"],
    }
    if (
        key != IMAGE_ASSET["source_member"]
        or work_id != IMAGE_ASSET["work_id"]
        or source.getparent().getparent().getparent().get("id")
        != IMAGE_ASSET["source_root_id"]
        or dict(source.attrib) != expected_source_attrs
    ):
        raise ValueError("Gregory source image identity or metadata drift")
    parent = source.getparent()
    if parent is None or parent.get("id") != "iii.iii-p86":
        raise ValueError("Gregory source image parent placement drift")
    source_selector = _selector(source)
    if source_selector != "ThML.body/div1[3]/div2[3]/p[82]/img[1]":
        raise ValueError("Gregory source image selector drift")

    asset_authority = next(item for item in source_manifest.record["authorities"] if item["name"] == "gregory-pedigree-image")
    if asset_authority.get("path") != IMAGE_ASSET["source_path"] or tuple(asset_authority.get("work_ids", ())) != (IMAGE_ASSET["work_id"],):
        raise ValueError("Gregory source authority path or work scope drifted")
    asset_path = source_manifest.authority_path("gregory-pedigree-image")
    asset_bytes = asset_path.read_bytes()
    if len(asset_bytes) != IMAGE_ASSET["bytes"] or _sha(asset_bytes) != IMAGE_ASSET["sha256"]:
        raise ValueError("Gregory retained image asset bytes drifted")
    if not asset_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Gregory retained image is not a PNG")
    receipt = json.loads(
        source_manifest.authority_path("gregory-pedigree-acquisition").read_bytes()
    )
    expected_receipt = {
        "source_page": IMAGE_ASSET["source_page"],
        "url": IMAGE_ASSET["source_url"],
        "final_url": IMAGE_ASSET["source_url"],
        "content_type": IMAGE_ASSET["media_type"],
        "bytes": IMAGE_ASSET["bytes"],
        "sha256": IMAGE_ASSET["sha256"],
        "retrieved_at": IMAGE_ASSET["acquired_at"],
    }
    if any(receipt.get(name) != value for name, value in expected_receipt.items()):
        raise ValueError("Gregory image acquisition receipt drifted")

    row = next(
        (
            item
            for item in rows
            if item["source_member"] == key
            and item["source_xml_id"] == IMAGE_ASSET["source_xml_id"]
        ),
        None,
    )
    if row is None:
        raise ValueError("Gregory source image crosswalk binding is missing")
    rows_by_feature = {item["feature_id"]: item for item in rows}
    parent_row = rows_by_feature.get(row["parent_feature_id"])
    if parent_row is None:
        raise ValueError("Gregory source image candidate parent binding is missing")
    binding = {
        **IMAGE_ASSET,
        "source_selector": source_selector,
        "source_parent_id": parent.get("id"),
        "tei_xml_id": row["tei_xml_id"],
        "candidate_parent_xml_id": parent_row["tei_xml_id"],
    }
    expected_placement = {
        "tei_xml_id": "lib048-npnf212-043142-iii.iii-p86.1",
        "candidate_parent_xml_id": "lib048-npnf212-043141-iii.iii-p86",
    }
    if any(binding[name] != value for name, value in expected_placement.items()):
        raise ValueError("Gregory candidate image placement drifted")
    return binding


def _expected_evidence(
    source_manifest: SourceManifest,
    trees: Mapping[str, etree._ElementTree],
    selected: list[tuple[str, etree._Element, str]],
    rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    members = []
    top_all = {}
    direct_all = {}
    work_bindings = []
    asset_binding = _expected_image_binding(source_manifest, selected, rows)
    source_paths = {key: path for key, _authority, path, _size, _digest in SOURCES}
    for key, _authority, path, size, digest in SOURCES:
        full = list(trees[key].getroot().iter())
        assigned_nodes = [
            node
            for selected_key, source_root, _work_id in selected
            if selected_key == key
            for node in source_root.iter()
        ]
        complete, assigned = _census(full), _census(assigned_nodes)
        top, direct = _division_accounting(
            trees[key],
            {
                source_id
                for source_key, source_id, _work_id in ASSIGNED
                if source_key == key
            },
        )
        top_all[key], direct_all[key] = top, direct
        members.append(
            {
                "key": key,
                "path": path,
                "bytes": size,
                "sha256": digest,
                "disposition": "included retained authority; assigned roots represented and all remaining member scope explicitly accounted outside work projection",
                "document_accounting": _document_accounting(trees[key]),
                "complete_document_census": complete,
                "assigned_scope_census": assigned,
                "excluded_scope_census": {
                    name: complete[name] - assigned[name] for name in complete
                },
            }
        )
    offset = 0
    for key, source_root, work_id in selected:
        count = sum(1 for _ in source_root.iter())
        work_bindings.append(
            {
                "work_id": work_id,
                "source_key": key,
                "source_member": source_paths[key],
                "source_root_id": source_root.get("id"),
                "source_root_selector": _selector(source_root),
                "feature_count": count,
            }
        )
        offset += count
    accountability = {
        "contract": "ocd-npnf2-lib048-source-accountability-v2",
        "schema": "npnf2-lib048.source-accountability.schema.json",
        "profile_id": "npnf2-lib048-fifteen-work-v2",
        "assigned_work_count": 15,
        "source_member_count": 4,
        "asset_count": 1,
        "feature_count": len(rows),
        "attribute_count": EXPECTED_CENSUS["attributes"],
        "omitted_feature_count": 0,
        "duplicate_feature_count": 0,
        "unresolved_feature_count": 0,
        "assigned_census": EXPECTED_CENSUS,
        "member_accounting": members,
        "top_level_division_accounting": top_all,
        "direct_div2_accounting": direct_all,
        "work_bindings": work_bindings,
        "asset_bindings": [asset_binding],
        "crosswalk": rows,
    }
    provenance = {
        "contract": "ocd-npnf2-lib048-provenance-v2",
        "status": "nonaccepted",
        "source_id": source_manifest.record["source_id"],
        "publication_state": "not_ready",
        "asset_bindings": [asset_binding],
        "source_edition_relationship": {
            "status": "edition-consistent-current-supplemental",
            "retained_source_member": "npnf212",
            "retained_source_sha256": "f701b4ce5196bc5890e50adabce4900cd07b803f3221115a7cce526ae0a95570",
            "retained_source_parent_id": "iii.iii-p86",
            "retained_source_xml_id": "iii.iii-p86.1",
            "retained_source_url": "https://ccel.org/ccel/schaff/npnf212/files/fig1.png",
            "current_asset_sha256": asset_binding["sha256"],
            "historical_snapshot_bytes": "unknown",
            "evidence": "The retained XML source path, image id, alt label, parent locus, and current CCEL image URL agree; the current retrieval is supplemental evidence and does not prove historical snapshot bytes.",
        },
        "sources": {
            key: {
                "path": path,
                "bytes": size,
                "sha256": digest,
                "metadata": _source_metadata(trees[key]),
                "retained_title_page_and_preface_credit_evidence": {
                    source_id: _source_text(trees[key], source_id)
                    for source_id in CREDIT_IDS[key]
                },
                "display_credit_names": CREDIT_NAMES[key],
            }
            for key, _authority, path, size, digest in SOURCES
        },
        "works": [
            {
                **binding,
                "translation_credit": {
                    "status": "retained-source-level-credit",
                    "credited_to": CREDIT_NAMES[binding["source_key"]],
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
            "id": "npnf2-lib048-work-specific-credit-allocation",
            "scope": "all-fifteen-assigned-works",
            "status": "unresolved",
            "evidence": "Retained title pages and prefaces are preserved exactly at source level; no unsupported work-level allocation is inferred.",
        },
        {
            "id": "npnf2-lib048-print-collation",
            "scope": "four-retained-electronic-witnesses",
            "status": "unresolved",
            "evidence": "The candidate is bound to retained CCEL XML; cited print editions were not collated.",
        },
        {
            "id": "npnf2-lib048-rights-human-acceptance-publication",
            "scope": "all-fifteen-assigned-works",
            "status": "unresolved",
            "evidence": "Retained headers state Public Domain; technical verification is not human acceptance or publication authorization.",
        },
    ]
    return accountability, provenance, b"".join(_canonical(item) for item in unresolved)


def _first_party_module_path(root: Path, module: str) -> Path | None:
    direct = root.joinpath(*module.split(".")).with_suffix(".py")
    package = root.joinpath(*module.split("."), "__init__.py")
    if direct.is_file():
        return direct
    if package.is_file():
        return package
    return None


def _resolved_import_name(
    module: str, path: Path, imported: str | None, level: int
) -> str:
    if level == 0:
        return imported or ""
    parts = module.split(".")
    base = parts if path.name == "__init__.py" else parts[:-1]
    base = base[: len(base) - (level - 1)]
    if imported:
        base.extend(imported.split("."))
    return ".".join(base)


def _closure_paths(root: Path, policy: Mapping[str, Any]) -> tuple[Path, ...]:
    forbidden = tuple(policy.get("forbidden_oracle_imports", []))
    pending = ["build.tei.npnf2_lib048_oracle"]
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
        parsed = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(parsed):
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
                if any(
                    name == prefix or name.startswith(prefix + ".")
                    for prefix in forbidden
                ):
                    raise ValueError(f"oracle closure contains forbidden import {name}")
                if _first_party_module_path(root, name) is not None:
                    pending.append(name)
    return tuple(sorted(set(modules.values()), key=lambda item: item.as_posix()))


def _closure_digest(root: Path, policy: Mapping[str, Any]) -> str:
    return _sha(
        _canonical(
            [
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": _sha(path.read_bytes()),
                }
                for path in _closure_paths(root, policy)
            ]
        )
    )


def _member_set_sha(source_manifest: SourceManifest) -> str:
    records = sorted(
        (
            {
                "name": authority["name"],
                "path": authority["path"],
                "bytes": authority["bytes"],
                "sha256": authority["sha256"],
            }
            for authority in source_manifest.record["authorities"]
            if authority["role"] == "primary-source"
        ),
        key=lambda item: (item["path"], item["name"]),
    )
    return _sha(
        _canonical({"contract": "ocd-source-member-set-v1", "members": records})
    )


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    if (
        set(candidate.member_names) != MEMBERS
        or candidate.manifest.get("status") != "nonaccepted"
    ):
        raise ValueError("LIB-048 candidate member or status drift")
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
        raise ValueError("candidate authority binding drift")
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile_bytes = source_manifest.authority_path(
        "reconstruction-profile"
    ).read_bytes()
    policy = _authority_json(policy_bytes, "validation policy")
    profile = _authority_json(profile_bytes, "reconstruction profile")
    trees = {}
    for key, authority, _path, size, digest in SOURCES:
        content = source_manifest.authority_path(authority).read_bytes()
        if len(content) != size or _sha(content) != digest:
            raise ValueError(f"wrong or stale retained source {key}")
        trees[key] = _source_tree(content)
    selected = _selected(trees)
    reference_exceptions = _neutral_reference_inventory(policy, selected)
    nodes = [
        node for _key, source_root, _work_id in selected for node in source_root.iter()
    ]
    if (
        _census(nodes) != EXPECTED_CENSUS
        or profile.get("assigned_census") != EXPECTED_CENSUS
    ):
        raise ValueError("independent source census drift")
    rows = _expected_rows(selected, policy, reference_exceptions)
    if (
        len(rows) != EXPECTED_CENSUS["elements"]
        or sum(len(row["source_attributes"]) for row in rows)
        != EXPECTED_CENSUS["attributes"]
    ):
        raise ValueError("independent source row census drift")
    tei_bytes = candidate.member_bytes("content.tei.xml")
    tei = _tei_tree(tei_bytes)
    body = _verify_header(tei, policy)
    works = list(body)
    if len(works) != 15 or any(not isinstance(node.tag, str) for node in works):
        raise ValueError("TEI work count drift")
    counter = [0]
    for (key, source_root, work_id), target in zip(selected, works, strict=True):
        _verify_node(
            source_root,
            target,
            key,
            policy,
            counter,
            work_id,
            source_root.get("id"),
            reference_exceptions,
        )
    if counter[0] != EXPECTED_CENSUS["elements"]:
        raise ValueError("TEI projection count drift")
    schema = etree.XMLSchema(
        etree.parse(str(source_manifest.authority_path("tei-p5-xsd")))
    )
    try:
        schema.assertValid(tei)
    except etree.DocumentInvalid as exc:
        raise ValueError("candidate fails TEI P5 XSD") from exc
    expected_accountability, expected_provenance, expected_unresolved = (
        _expected_evidence(source_manifest, trees, selected, rows)
    )
    accountability = _strict_json(
        candidate.member_bytes("source-accountability.json"), "source accountability"
    )
    jsonschema.Draft202012Validator(
        json.loads(
            source_manifest.authority_path("source-accountability-schema").read_bytes()
        )
    ).validate(accountability)
    if accountability != expected_accountability:
        raise ValueError(
            "source-accountability omission, duplication, order, mapping, or invention drift"
        )
    if (
        _strict_json(candidate.member_bytes("provenance.json"), "provenance")
        != expected_provenance
    ):
        raise ValueError("source metadata, rights, credit, or state drift")
    if candidate.member_bytes("unresolved.jsonl") != expected_unresolved:
        raise ValueError("unresolved evidence drift")
    if (
        candidate.member_bytes("README.source.md")
        != source_manifest.authority_path(
            "source-local-attribution-readme"
        ).read_bytes()
    ):
        raise ValueError("source attribution README drift")
    result = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).resolve().read_bytes()),
        "import_closure_sha256": _closure_digest(root, policy),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": _sha(
            source_manifest.authority_path("candidate-package-schema").read_bytes()
        ),
        "source_sha256": _member_set_sha(source_manifest),
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
