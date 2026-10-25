"""Producer-independent oracle for source-to-TEI issue 37c-137."""

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

from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.tei.writer import tei_el


ORACLE_ID = "ocd-37c137-ecumenical-councils-source-to-tei-oracle"
ORACLE_VERSION = "1"
PROFILE_ID = "ecumenical-councils-canons-and-decrees-npnf2-seven-roots-v1"
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
        "npnf214",
        "retained-npnf214",
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
CREDIT_IDS = ("i-p9", "i-p11", "i-p23", "ii-p14")
CREDIT_NAMES = ("Philip Schaff", "Henry Wace", "Henry R. Percival")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {label}") from exc
    if not isinstance(value, dict) or _canonical(value) != content:
        raise ValueError(f"{label} is not a canonical JSON object")
    return value


def _authority_json(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"))
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


def _projection(
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
            destination = "@xml:id-and-source-accountability"
            method = "deterministic-member-and-ordinal-prefix"
        else:
            rule = rules["attribute_rules"].get(name)
            if (
                isinstance(rule, Mapping)
                and tag in rule.get("source_tags", [])
                and not (rule.get("except_work_root") and work_id)
            ):
                destination = rule.get("disposition", destination)
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
            raise ValueError(f"source root omission, duplication, or wrong binding: {source_id}")
        result.append((matches[0], work_id))
    return result


def _expected_rows(
    selected: list[tuple[etree._Element, str]], policy: Mapping[str, Any]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def visit(
        node: etree._Element,
        parent_feature_id: str | None,
        source_root_id: str,
        work_id: str | None = None,
    ) -> None:
        if not isinstance(node.tag, str):
            raise ValueError("assigned source contains a non-element node")
        ordinal = len(rows) + 1
        target_tag, attrs, wrapper_id, dispositions = _projection(
            policy, node, ordinal, work_id
        )
        title = node.get("title") if str(node.tag).startswith("div") else None
        feature_id = f"ecumenical-councils-feature-{ordinal:06d}"
        rows.append(
            {
                "feature_id": feature_id,
                "parent_feature_id": parent_feature_id,
                "source_member": "npnf214",
                "source_selector": _selector(node),
                "source_tag": node.tag,
                "source_xml_id": node.get("id"),
                "source_attributes": dict(node.attrib),
                "direct_text_length": len(node.text or ""),
                "direct_text_sha256": _sha((node.text or "").encode()),
                "tail_text_length": len(node.tail or ""),
                "tail_text_sha256": _sha((node.tail or "").encode()),
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
        for child in node:
            visit(child, feature_id, source_root_id)

    for source_root, work_id in selected:
        visit(source_root, None, source_root.get("id") or "", work_id)
    return rows


def _verify_node(
    source: etree._Element,
    target: etree._Element,
    policy: Mapping[str, Any],
    counter: list[int],
    work_id: str | None = None,
) -> None:
    counter[0] += 1
    target_tag, attrs, wrapper_id, _dispositions = _projection(
        policy, source, counter[0], work_id
    )
    if target.tag != f"{{{TEI_NS}}}{target_tag}":
        raise ValueError(f"TEI tag drift at {_selector(source)}")
    if _normalized_attrs(target) != attrs:
        raise ValueError(f"TEI attribute drift at {_selector(source)}")
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
            raise ValueError(f"division head drift at {_selector(source)}")
        index = 1
    for source_child in source:
        if index >= len(children):
            raise ValueError(f"TEI source child omitted at {_selector(source)}")
        candidate_child = children[index]
        child_ordinal = counter[0] + 1
        _tag, _attrs, child_wrapper, _ = _projection(
            policy, source_child, child_ordinal, None
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
                raise ValueError(f"TEI inline wrapper drift at {_selector(source_child)}")
            candidate_child = candidate_child[0]
        _verify_node(source_child, candidate_child, policy, counter)
        index += 1
    if index != len(children):
        raise ValueError(f"TEI omission, duplication, or invention at {_selector(source)}")


def _expected_header(tree: etree._ElementTree) -> etree._Element:
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


def _expected_evidence(
    source_manifest: SourceManifest,
    tree: etree._ElementTree,
    selected: list[tuple[etree._Element, str]],
    rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    key, _authority, logical_path, expected_bytes, expected_sha = SOURCES[0]
    assigned_nodes = [node for source_root, _work_id in selected for node in source_root.iter()]
    assigned_census = _census(assigned_nodes)
    complete_census = _census(list(tree.getroot().iter()))
    top_accounting, direct_accounting = _division_accounting(
        tree, {source_id for _key, source_id, _work_id in ASSIGNED}
    )
    work_bindings = []
    for source_root, work_id in selected:
        work_bindings.append(
            {
                "work_id": work_id,
                "source_key": key,
                "source_member": logical_path,
                "source_root_id": source_root.get("id"),
                "source_root_selector": _selector(source_root),
                "feature_count": sum(1 for _ in source_root.iter()),
            }
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
    pending = ["build.tei.ecumenical_councils_canons_and_decrees_oracle"]
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


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    if (
        set(candidate.member_names) != MEMBERS
        or candidate.manifest.get("status") != "nonaccepted"
    ):
        raise ValueError("37c-137 candidate member or status drift")
    root = source_manifest.repository_root
    expected_manifest = {
        "path": source_manifest.path.relative_to(root).as_posix(),
        "sha256": source_manifest.sha256,
    }
    validator = source_manifest.record["validator"]
    converter = source_manifest.record["converter"]
    if (
        candidate.manifest.get("source_manifest") != expected_manifest
        or candidate.manifest.get("converter") != converter
        or candidate.manifest.get("package_schema")
        != source_manifest.record["package_schema"]
    ):
        raise ValueError("candidate authority binding drift")
    key, authority, logical_path, expected_bytes, expected_sha = SOURCES[0]
    config = _authority_json(
        source_manifest.authority_path("work-config").read_bytes(), "work config"
    )
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
    if not isinstance(policy, dict) or not isinstance(readme, str):
        raise ValueError("37c-137 entry-local config lacks policy or attribution text")
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    authority_policy = _authority_json(policy_bytes, "validation policy")
    if any(
        authority_policy.get(key) != policy.get(key)
        for key in ("forbidden_oracle_imports", "projection", "tei_topology")
    ):
        raise ValueError("37c-137 config and validation-policy drift")
    profile_bytes = source_manifest.authority_path(
        "reconstruction-profile"
    ).read_bytes()
    profile = _authority_json(profile_bytes, "reconstruction profile")
    if (
        profile.get("profile_id") != PROFILE_ID
        or profile.get("assigned_census") != EXPECTED_CENSUS
        or profile.get("source_envelope", {}).get("top_level_div1_ids_in_order")
        != list(TOP_LEVEL_IDS)
    ):
        raise ValueError("37c-137 reconstruction profile drift")
    content = source_manifest.authority_path(authority).read_bytes()
    if len(content) != expected_bytes or _sha(content) != expected_sha:
        raise ValueError("wrong or stale retained npnf214 source")
    tree = _source_tree(content)
    selected = _selected(tree)
    assigned_nodes = [node for source_root, _work_id in selected for node in source_root.iter()]
    if _census(assigned_nodes) != EXPECTED_CENSUS:
        raise ValueError("independent source census drift")
    rows = _expected_rows(selected, policy)
    if (
        len(rows) != EXPECTED_CENSUS["elements"]
        or sum(len(row["source_attributes"]) for row in rows)
        != EXPECTED_CENSUS["attributes"]
    ):
        raise ValueError("independent source row census drift")
    tei = _tei_tree(candidate.member_bytes("content.tei.xml"))
    root_node = tei.getroot()
    if (
        root_node.tag != f"{{{TEI_NS}}}TEI"
        or _normalized_attrs(root_node)
        != {"xml:id": "ecumenical-councils-canons-and-decrees-candidate"}
        or root_node.text
        or root_node.tail
        or root_node.getprevious() is not None
        or root_node.getnext() is not None
    ):
        raise ValueError("TEI root topology drift")
    children = list(root_node)
    if (
        len(children) != 2
        or [etree.QName(child).localname for child in children]
        != ["teiHeader", "text"]
    ):
        raise ValueError("TEI root child invention or omission")
    expected_header = _expected_header(tree).find(f"{{{TEI_NS}}}teiHeader")
    actual_header = children[0]
    if expected_header is None or actual_header is None:
        raise ValueError("TEI header missing")
    expected_header_bytes = etree.tostring(
        expected_header, method="c14n", with_comments=True
    )
    if (
        etree.tostring(actual_header, method="c14n", with_comments=True)
        != expected_header_bytes
        or _sha(expected_header_bytes) != policy["tei_topology"]["header_c14n_sha256"]
    ):
        raise ValueError("TEI header metadata, rights, credit, or topology drift")
    text = children[1]
    if text.text or text.tail or _normalized_attrs(text) or len(text) != 1:
        raise ValueError("TEI text topology drift")
    body = text[0]
    if (
        body.tag != f"{{{TEI_NS}}}body"
        or _normalized_attrs(body)
        != {"xml:id": "ecumenical-councils-canons-and-decrees-body"}
        or body.text
        or body.tail
    ):
        raise ValueError("TEI body topology drift")
    works = list(body)
    if len(works) != len(ASSIGNED):
        raise ValueError("TEI work count drift")
    counter = [0]
    for (source_root, work_id), target in zip(selected, works, strict=True):
        _verify_node(source_root, target, policy, counter, work_id)
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
        _expected_evidence(source_manifest, tree, selected, rows)
    )
    accountability = _strict_json(
        candidate.member_bytes("source-accountability.json"), "source accountability"
    )
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
    if candidate.member_bytes("README.source.md") != readme.encode("utf-8"):
        raise ValueError("source attribution README drift")
    result = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).resolve().read_bytes()),
        "import_closure_sha256": _closure_digest(root, policy),
        "runtime": (
            f"{platform.python_implementation()} {platform.python_version()} "
            f"({Path(sys.executable).resolve(strict=True)})"
        ),
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": _sha(
            source_manifest.authority_path("candidate-package-schema").read_bytes()
        ),
        "source_sha256": expected_sha,
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
