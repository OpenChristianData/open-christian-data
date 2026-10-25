"""Entry-local faithful TEI reconstruction for source-to-TEI issue 37c-204."""

from __future__ import annotations

from collections import Counter
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Mapping

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.tei.writer import tei_el


CONVERTER_ID = "ocd-37c204-hodge-systematic-theology-vol-2-to-tei"
CONVERTER_VERSION = "2"
PROFILE_ID = "hodge-systematic-theology-vol-2-ccel-content-roots-v1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"

SOURCE_ID = "ocd-37c204-hodge-systematic-theology-vol-2-ccel-theology2"
SOURCE_KEY = "hodge-vol-2"
SOURCE_PATH = "raw/ccel/hodge/theology2.xml"
SOURCE_BYTES = 2_601_781
SOURCE_SHA256 = "52a43581dcb7b75a6903c89c8e2496b8d754bdbcd6fa751ecaa4f065e933d942"
WORK_ID = "hodge-systematic-theology-vol-2"
ASSIGNED_ROOTS = ((SOURCE_KEY, "iii", WORK_ID), (SOURCE_KEY, "iv", WORK_ID))
ASSIGNED_ROOT_IDS = ("iii", "iv")
TOP_LEVEL_IDS = ("i", "ii", "iii", "iv", "v")
TOP_LEVEL_TITLES = {
    "i": "Title",
    "ii": "Prefatory",
    "iii": "Part II. Anthropology",
    "iv": "Part III. Soteriology.",
    "v": "Indexes",
}
SUPPORTED_TAGS = {
    "div",
    "div1",
    "div2",
    "div3",
    "h1",
    "h2",
    "h3",
    "hr",
    "i",
    "l",
    "note",
    "p",
    "pb",
    "scripRef",
    "span",
    "verse",
}
LANGUAGE_MAP = {"DE": "de", "EL": "grc", "FR": "fr", "HE": "he", "LA": "la"}
SOURCE_ONLY_ATTRIBUTES = {"next", "parsed", "prev", "progress", "title", "version"}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _json_authority(source: SourceManifest, name: str) -> dict[str, Any]:
    value = json.loads(source.authority_path(name).read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"37c-204 {name} authority is not an object")
    return value


def _census(nodes: list[etree._Element]) -> dict[str, Any]:
    elements = [node for node in nodes if isinstance(node.tag, str)]
    strings = [(node.text or "") + (node.tail or "") for node in elements]
    return {
        "attribute_counts": dict(
            sorted(Counter(k for n in elements for k in n.attrib).items())
        ),
        "attributes": sum(len(n.attrib) for n in elements),
        "characters": sum(map(len, strings)),
        "direct_text_bytes": sum(len((n.text or "").encode("utf-8")) for n in elements),
        "elements": len(elements),
        "non_ascii_characters": sum(
            sum(ord(c) > 127 for c in value) for value in strings
        ),
        "notes": sum(n.tag == "note" for n in elements),
        "page_breaks": sum(n.tag == "pb" for n in elements),
        "scripture_refs": sum(n.tag == "scripRef" for n in elements),
        "tag_counts": dict(sorted(Counter(n.tag for n in elements).items())),
        "tail_text_bytes": sum(len((n.tail or "").encode("utf-8")) for n in elements),
        "tail_nodes": sum(bool(n.tail) for n in elements),
        "text_nodes": sum(bool(n.text) for n in elements),
    }


def _subtract(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in left.items():
        if key in {"tag_counts", "attribute_counts"}:
            result[key] = {
                name: count - right.get(key, {}).get(name, 0)
                for name, count in value.items()
                if count - right.get(key, {}).get(name, 0)
            }
        else:
            result[key] = value - right.get(key, 0)
    return result


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
    if current is None:
        raise ValueError("source selector escaped ThML.body")
    return "ThML.body/" + "/".join(reversed(parts))


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


def _document_accounting(tree: etree._ElementTree) -> dict[str, Any]:
    root = tree.getroot()

    def adjacent(node: etree._Element | None, direction: str) -> list[dict[str, str]]:
        found: list[dict[str, str]] = []
        while node is not None:
            found.append(
                {
                    "kind": "comment"
                    if node.tag is etree.Comment
                    else "processing-instruction",
                    "text": node.text or "",
                    "tail": node.tail or "",
                }
            )
            node = node.getprevious() if direction == "previous" else node.getnext()
        if direction == "previous":
            found.reverse()
        return found

    return {
        "doctype": tree.docinfo.doctype,
        "encoding": tree.docinfo.encoding,
        "post_root_nodes": adjacent(root.getnext(), "next"),
        "pre_root_nodes": adjacent(root.getprevious(), "previous"),
        "root_attributes": dict(root.attrib),
        "root_namespace_declarations": {
            "" if k is None else k: v for k, v in root.nsmap.items()
        },
        "root_tag": root.tag,
        "standalone": tree.docinfo.standalone,
        "xml_version": tree.docinfo.xml_version,
    }


def _selected(
    tree: etree._ElementTree, source: SourceManifest
) -> list[tuple[etree._Element, str, str]]:
    body = tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError("retained Hodge Vol. 2 source lacks ThML.body")
    top = [node for node in body if isinstance(node.tag, str)]
    if (
        any(node.tag != "div1" for node in top)
        or tuple(node.get("id") for node in top) != TOP_LEVEL_IDS
    ):
        raise ValueError("37c-204 five-root source envelope drift")
    if {node.get("id"): node.get("title", "") for node in top} != TOP_LEVEL_TITLES:
        raise ValueError("37c-204 source root title drift")
    scope = source.record.get("scope")
    expected_scope = {
        "assigned_roots_in_source_order": [list(item) for item in ASSIGNED_ROOTS],
        "excluded_top_level_roots": ["i", "ii", "v"],
        "kind": "complete-source-subtrees",
        "source_member": "retained-hodge-vol-2",
    }
    try:
        observed_scope = {
            "assigned_roots_in_source_order": [
                list(item) for item in scope["assigned_roots_in_source_order"]
            ],
            "excluded_top_level_roots": list(scope["excluded_top_level_roots"]),
            "kind": scope["kind"],
            "source_member": scope["source_member"],
        }
    except (KeyError, TypeError):
        raise ValueError("37c-204 source scope binding is incomplete") from None
    if observed_scope != expected_scope:
        raise ValueError("37c-204 source scope binding drift")
    selected = [
        (node, key, work)
        for node in top
        for key, root_id, work in ASSIGNED_ROOTS
        if node.get("id") == root_id
    ]
    if [(key, node.get("id"), work) for node, key, work in selected] != list(
        ASSIGNED_ROOTS
    ):
        raise ValueError("37c-204 assigned roots missing, duplicated, or out of order")
    return selected


def _target_attributes(
    policy: Mapping[str, Any], source: etree._Element, feature_id: str
) -> tuple[str, dict[str, str], list[dict[str, str]]]:
    projection = policy["projection"]
    tag = str(source.tag)
    explicit_tags = {"hr": "milestone", "verse": "lg", "l": "l"}
    target_tag = str(
        explicit_tags.get(tag)
        or (
            projection["language_span_tag"]
            if tag == "span" and source.get("lang")
            else projection["tag_map"].get(tag, "")
        )
    )
    if not target_tag:
        raise ValueError(f"37c-204 source element lacks a projection: {tag}")
    attrs: dict[str, str] = {"xml:id": feature_id}
    dispositions: list[dict[str, str]] = []
    rend: list[str] = []
    if tag in {"div1", "div2", "div3", "div"}:
        attrs["type"] = str(
            projection["derived_attributes"]["div_type_template"].format(source_tag=tag)
        )
    elif tag == "hr":
        if (
            len(source)
            or (source.text or "").strip()
            or set(source.attrib) != {"style"}
        ):
            raise ValueError("37c-204 unsupported hr source form")
        attrs["unit"] = str(projection["derived_attributes"]["milestone_unit"])
    elif tag == "verse":
        if (
            set(source.attrib) != {"id"}
            or not source.get("id")
            or not len(source)
            or any(child.tag != "l" for child in source)
        ):
            raise ValueError("37c-204 unsupported verse source attributes")
        attrs["type"] = "source-verse"
    elif tag == "l":
        if (
            set(source.attrib) != {"id", "class"}
            or not source.get("id")
            or source.get("class") not in {"t1", "t2"}
        ):
            raise ValueError("37c-204 unsupported verse-line source attributes")
    if tag == "span" and not source.get("lang"):
        attrs["type"] = str(projection["derived_attributes"]["plain_span_type"])
    for derived_tag, token in projection["derived_attributes"][
        "source_tag_rend"
    ].items():
        if tag == derived_tag and token:
            rend.append(str(token))
    rules = policy["attribute_rules"]
    for name, value in source.attrib.items():
        rule = rules.get(name)
        if not isinstance(rule, Mapping) or tag not in rule.get("source_tags", ()):
            raise ValueError(
                f"37c-204 source attribute lacks disposition: {tag}@{name}"
            )
        if name == "id":
            destination, method = (
                "@xml:id-and-source-accountability",
                "deterministic-global-feature-id",
            )
        elif name in SOURCE_ONLY_ATTRIBUTES:
            destination, method = (
                "source-accountability-only",
                "preserved-exactly-in-accountability",
            )
        elif name in {"class", "style", "border"}:
            destination, method = "@rend", f"exact-source-{name}-token-in-rend"
            rend.append(f"{name}={value}")
        else:
            destination, method = (
                str(rule.get("disposition", "source-accountability-only")),
                "declared-attribute-map",
            )
        dispositions.append(
            {
                "destination": destination,
                "method": method,
                "source_attribute": name,
                "source_value": value,
            }
        )
        if name == "lang":
            if value not in LANGUAGE_MAP:
                raise ValueError(f"37c-204 unsupported source language code: {value}")
            attrs["xml:lang"] = LANGUAGE_MAP[value]
        elif name == "n":
            attrs["n"] = value
        elif name == "href":
            attrs["facs"] = value
        elif name == "passage":
            attrs["cRef"] = value
        elif name == "osisRef":
            attrs["target"] = value
        elif name == "rowspan":
            attrs["rows"] = value
        elif name == "colspan":
            attrs["cols"] = value
    if rend:
        attrs["rend"] = "; ".join(rend)
    if tag == "scripRef":
        attrs["type"] = "scripture"
    return target_tag, attrs, dispositions


def _append(
    policy: Mapping[str, Any],
    source: etree._Element,
    parent: etree._Element,
    rows: list[dict[str, Any]],
    state: list[int],
    parent_id: str | None,
    root_id: str,
    work_id: str,
    child_ordinal: int,
) -> None:
    if not isinstance(source.tag, str) or source.tag not in SUPPORTED_TAGS:
        raise ValueError(f"37c-204 unsupported assigned source element: {source.tag!r}")
    state[0] += 1
    feature_id = f"hodge-systematic-theology-vol-2-feature-{state[0]:06d}"
    target_tag, attrs, dispositions = _target_attributes(policy, source, feature_id)
    target = tei_el(target_tag, attrs)
    target.text = source.text
    parent.append(target)
    text = (source.text or "").encode("utf-8")
    tail = (source.tail or "").encode("utf-8")
    rows.append(
        {
            "attribute_dispositions": dispositions,
            "child_ordinal": child_ordinal,
            "direct_text_length": len(text),
            "direct_text_sha256": _sha(text),
            "disposition": "represented",
            "feature_id": feature_id,
            "parent_feature_id": parent_id,
            "source_attributes": dict(source.attrib),
            "source_member": SOURCE_KEY,
            "source_root_id": root_id,
            "source_selector": _selector(source),
            "source_tag": source.tag,
            "source_xml_id": source.get("id"),
            "tail_text_length": len(tail),
            "tail_text_sha256": _sha(tail),
            "tei_attributes": attrs,
            "tei_tag": target_tag,
            "tei_xml_id": feature_id,
            "work_id": work_id,
        }
    )
    for ordinal, child in enumerate(source, 1):
        if not isinstance(child.tag, str):
            raise ValueError("37c-204 assigned source contains non-element markup")
        _append(
            policy, child, target, rows, state, feature_id, root_id, work_id, ordinal
        )
    target.tail = source.tail


def _metadata_entries(nodes: list[etree._Element]) -> list[dict[str, Any]]:
    return [
        {
            "attributes": dict(node.attrib),
            "tag": node.tag,
            "tail": node.tail or "",
            "text": node.text or "",
        }
        for node in nodes
    ]


def _source_metadata(tree: etree._ElementTree) -> dict[str, Any]:
    head = tree.getroot().find("ThML.head")
    if head is None:
        raise ValueError("retained Hodge source lacks ThML.head")
    electronic = head.find("electronicEdInfo")
    if electronic is None:
        raise ValueError("retained Hodge source lacks electronicEdInfo")
    dc = electronic.find("DC")
    print_info = head.find("printSourceInfo")
    return {
        "dc_entries": _metadata_entries(list(dc) if dc is not None else []),
        "electronic_ed_info_entries": _metadata_entries(
            [node for node in electronic if node.tag != "DC"]
        ),
        "head_c14n_sha256": _sha(
            etree.tostring(head, method="c14n", with_comments=True)
        ),
        "print_source_entries": _metadata_entries(
            list(print_info) if print_info is not None else []
        ),
    }


def _header(tree: etree._ElementTree, config: Mapping[str, Any]) -> etree._Element:
    titles = tree.xpath(
        "/ThML/ThML.head/electronicEdInfo/DC/DC.Title[not(@sub)]/text()"
    )
    title = "".join(map(str, titles))
    if title != "Systematic Theology - Volume II":
        raise ValueError("37c-204 retained electronic title drift")
    root = tei_el("TEI", {"xml:id": f"{WORK_ID}-candidate"})
    header = tei_el("teiHeader")
    file_desc = tei_el("fileDesc")
    title_stmt = tei_el("titleStmt")
    title_stmt.append(tei_el("title", {"type": "retained-electronic-title"}, title))
    title_stmt.append(tei_el("author", text="Charles Hodge"))
    resp = tei_el("respStmt")
    resp.append(tei_el("resp", text="electronic source"))
    resp.append(tei_el("name", text="Christian Classics Ethereal Library"))
    title_stmt.append(resp)
    file_desc.append(title_stmt)
    publication = tei_el("publicationStmt")
    publication.append(tei_el("publisher", text="Christian Classics Ethereal Library"))
    availability = tei_el("availability", {"status": "unknown"})
    availability.append(
        tei_el(
            "p",
            text="CCEL permits parsing the ThML source. This permission is not a rights decision; human rights review remains required.",
        )
    )
    publication.append(availability)
    file_desc.append(publication)
    source_desc = tei_el("sourceDesc")
    bibl = tei_el("bibl", {"xml:id": f"source-{WORK_ID}"})
    bibl.append(tei_el("title", {"type": "retained-electronic-title"}, title))
    bibl.append(tei_el("author", text="Charles Hodge"))
    bibl.append(
        tei_el("publisher", text="Wm. B. Eerdmans Publishing Co., Grand Rapids, Mich.")
    )
    bibl.append(tei_el("date", {"when": "1940"}, "1940"))
    bibl.append(
        tei_el(
            "note",
            {"type": "copyright-notice"},
            "The retained title page separately states copyright entered in 1871 by Charles Scribner and Company; this is not treated as the edition date.",
        )
    )
    bibl.append(tei_el("idno", {"type": "CCEL-XML-url"}, str(config["source_url"])))
    bibl.append(tei_el("idno", {"type": "CCEL-path"}, "/ccel/hodge/theology2.html"))
    bibl.append(tei_el("idno", {"type": "sha256"}, SOURCE_SHA256))
    bibl.append(
        tei_el(
            "note",
            {"type": "unverified-local-edition-claim", "source": "work-config"},
            "The work configuration claims New York: Scribner, Armstrong, 1872-1873; the retained source does not establish this local edition claim, and it is not adopted.",
        )
    )
    bibl.append(tei_el("note", {"type": "source-attribution"}, "Sourced via CCEL.org."))
    source_desc.append(bibl)
    file_desc.append(source_desc)
    header.append(file_desc)
    root.append(header)
    return root


def _root_accounting(tree: etree._ElementTree) -> list[dict[str, Any]]:
    body = tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError("retained Hodge source lacks ThML.body")
    result = []
    for ordinal, node in enumerate(body, 1):
        if not isinstance(node.tag, str) or node.tag != "div1":
            raise ValueError("37c-204 source body has unsupported top-level markup")
        source_id = node.get("id")
        assigned = source_id in ASSIGNED_ROOT_IDS
        result.append(
            {
                "census": _census(list(node.iter())),
                "disposition": "assigned-work-root-represented"
                if assigned
                else "source-evidence-outside-work-projection",
                "feature_count": sum(1 for _ in node.iter()),
                "id": source_id,
                "ordinal": ordinal,
                "reason": "complete source-native subtree represented in retained order"
                if assigned
                else "title, prefatory, or index material outside the assigned work projection",
                "selector": _selector(node),
                "tag": node.tag,
                "title": node.get("title", ""),
            }
        )
    return result


def _accountability(
    source: SourceManifest,
    tree: etree._ElementTree,
    selected: list[tuple[etree._Element, str, str]],
    rows: list[dict[str, Any]],
    assigned: dict[str, Any],
) -> dict[str, Any]:
    complete = _census(list(tree.getroot().iter()))
    root_bindings = []
    for order, (node, key, work) in enumerate(selected, 1):
        root_bindings.append(
            {
                "feature_count": sum(1 for _ in node.iter()),
                "root_census": _census(list(node.iter())),
                "source_key": key,
                "source_member": SOURCE_PATH,
                "source_root_id": node.get("id"),
                "source_root_selector": _selector(node),
                "source_root_title": node.get("title", ""),
                "source_order": order,
                "work_id": work,
            }
        )
    primary = next(
        (
            item
            for item in source.record["authorities"]
            if isinstance(item, Mapping) and item.get("name") == "retained-hodge-vol-2"
        ),
        None,
    )
    if (
        primary is None
        or primary.get("bytes") != SOURCE_BYTES
        or primary.get("sha256") != SOURCE_SHA256
    ):
        raise ValueError("37c-204 retained source authority identity drift")
    return {
        "assigned_census": assigned,
        "assigned_root_count": 2,
        "assigned_work_count": 1,
        "attribute_count": assigned["attributes"],
        "complete_source_envelope": {
            "assigned_root_ids_in_source_order": list(ASSIGNED_ROOT_IDS),
            "excluded_root_ids": [
                i for i in TOP_LEVEL_IDS if i not in ASSIGNED_ROOT_IDS
            ],
            "top_level_root_ids_in_source_order": list(TOP_LEVEL_IDS),
            "top_level_root_count": 5,
        },
        "contract": "ocd-37c204-source-accountability-v1",
        "crosswalk": rows,
        "duplicate_feature_count": 0,
        "feature_count": len(rows),
        "member_accounting": [
            {
                "assigned_scope_census": assigned,
                "bytes": primary["bytes"],
                "complete_document_census": complete,
                "document_accounting": _document_accounting(tree),
                "excluded_scope_census": _subtract(complete, assigned),
                "key": SOURCE_KEY,
                "path": SOURCE_PATH,
                "sha256": SOURCE_SHA256,
                "disposition": "retained primary source; assigned content roots represented and all excluded top-level roots explicitly accounted",
            }
        ],
        "omitted_feature_count": 0,
        "profile_id": PROFILE_ID,
        "root_accounting": _root_accounting(tree),
        "root_bindings": root_bindings,
        "schema": "inline-entry-structural-contract-v1",
        "source_member_count": 1,
        "unresolved_feature_count": 0,
        "work_bindings": [
            {
                "root_ids": list(ASSIGNED_ROOT_IDS),
                "source_key": SOURCE_KEY,
                "source_member": SOURCE_PATH,
                "work_id": WORK_ID,
            }
        ],
    }


def _provenance(
    source: SourceManifest, tree: etree._ElementTree, config: Mapping[str, Any]
) -> dict[str, Any]:
    permission = source.authority_path("ccel-permission-evidence").read_bytes()
    witnesses = json.loads(source.authority_path("witness-inventory").read_bytes())
    return {
        "canonical_data_written": False,
        "canonical_ir_written": False,
        "contract": "ocd-37c204-provenance-v1",
        "publication_state": "not_ready",
        "source_id": SOURCE_ID,
        "source_scope": {
            "assigned_roots": [list(item) for item in ASSIGNED_ROOTS],
            "excluded_top_level_roots": [
                i for i in TOP_LEVEL_IDS if i not in ASSIGNED_ROOT_IDS
            ],
            "kind": "complete-source-subtrees",
        },
        "sources": {
            SOURCE_KEY: {
                "bytes": SOURCE_BYTES,
                "config_claims": {
                    "authority": "work-config",
                    "claims": dict(config),
                    "status": "unresolved-not-adopted",
                },
                "metadata": _source_metadata(tree),
                "path": SOURCE_PATH,
                "permission_evidence": {
                    "bytes": len(permission),
                    "path": "docs/sources/ccel-permission.md",
                    "sha256": _sha(permission),
                },
                "sha256": SOURCE_SHA256,
                "witness_inventory": witnesses,
            }
        },
        "works": [
            {
                "accepted_ir": "not_accepted",
                "human_review": "required",
                "publication": "not_ready",
                "root_ids": list(ASSIGNED_ROOT_IDS),
                "source_key": SOURCE_KEY,
                "source_member": SOURCE_PATH,
                "textual_form": "retained English CCEL electronic ThML witness; translation or revision allocation not established",
                "translation_credit": {
                    "credited_to": [],
                    "status": "not-established-in-retained-source",
                    "work_specific_allocation": None,
                },
                "work_id": WORK_ID,
            }
        ],
    }


def _unresolved() -> bytes:
    records = [
        {
            "evidence": "The retained title page names the 1940 Eerdmans imprint and separately gives an 1871 Scribner copyright notice. The work configuration's 1872-1873 original-edition claim is not proven by this source.",
            "id": f"{WORK_ID}-print-edition-claim",
            "scope": "edition and witness identity",
            "status": "unresolved",
        },
        {
            "evidence": "The retained source identifies Charles Hodge and CCEL metadata but does not establish a work-specific translator, reviser, or contributor allocation for the selected roots.",
            "id": f"{WORK_ID}-textual-form-and-contributors",
            "scope": "textual form and contributors",
            "status": "unresolved",
        },
        {
            "evidence": "CCEL permits parsing the ThML. This is not a rights decision, human acceptance, durable IR admission, or publication authorization.",
            "id": f"{WORK_ID}-rights-and-acceptance",
            "scope": "rights, human acceptance, and publication",
            "status": "unresolved",
        },
        {
            "evidence": "CVW visual comparison has not been performed for the exact source/candidate pair. Visual review and downstream admission remain separate gates.",
            "id": f"{WORK_ID}-visual-review-and-admission",
            "scope": "visual review and downstream admission",
            "status": "unresolved",
        },
    ]
    return b"".join(_canonical(record) for record in records)


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    if source_manifest.record.get("source_id") != SOURCE_ID:
        raise ValueError("37c-204 source manifest identity drift")
    config = _json_authority(source_manifest, "work-config")
    if (
        config.get("resource_id") != WORK_ID
        or config.get("title") != "Systematic Theology, Vol. 2"
        or config.get("author") != "Charles Hodge"
        or config.get("source_url") != "https://www.ccel.org/ccel/hodge/theology2.xml"
        or config.get("source_format") != "ThML XML"
        or config.get("source_hash") != f"sha256:{SOURCE_SHA256}"
    ):
        raise ValueError("37c-204 work config source identity or hash drift")
    profile = _json_authority(source_manifest, "reconstruction-profile")
    policy = _json_authority(source_manifest, "validation-policy")
    if profile.get("profile_id") != PROFILE_ID or policy.get("policy_id") != PROFILE_ID:
        raise ValueError("37c-204 profile or policy binding drift")
    primary = source_manifest.authority_path("retained-hodge-vol-2")
    content = primary.read_bytes()
    if len(content) != SOURCE_BYTES or _sha(content) != SOURCE_SHA256:
        raise ValueError("37c-204 retained source bytes or hash drift")
    tree = _source_tree(content)
    selected = _selected(tree, source_manifest)
    assigned_nodes = [node for root, _key, _work in selected for node in root.iter()]
    assigned_census = _census(assigned_nodes)
    if {
        tag: assigned_census["tag_counts"].get(tag, 0) for tag in ("hr", "verse", "l")
    } != {"hr": 2, "verse": 7, "l": 28}:
        raise ValueError("37c-204 source-native rule or verse-line census drift")
    if assigned_census != profile.get("assigned_census"):
        raise ValueError("37c-204 assigned source census drift")
    counts = {
        root.get("id"): sum(1 for _ in root.iter()) for root, _key, _work in selected
    }
    if counts != profile.get("assigned_root_counts"):
        raise ValueError("37c-204 assigned root feature counts drift")
    envelope = profile.get("source_envelope", {})
    if (
        envelope.get("top_level_div1_ids_in_order") != list(TOP_LEVEL_IDS)
        or envelope.get("root_titles") != TOP_LEVEL_TITLES
        or envelope.get("assigned_top_level_div1_ids_in_source_order")
        != list(ASSIGNED_ROOT_IDS)
        or envelope.get("excluded_top_level_div1_ids") != ["i", "ii", "v"]
    ):
        raise ValueError("37c-204 profile source envelope drift")
    root = _header(tree, config)
    text = tei_el("text")
    body = tei_el("body", {"xml:id": f"{WORK_ID}-body"})
    text.append(body)
    root.append(text)
    rows: list[dict[str, Any]] = []
    state = [0]
    for source_root, _key, work_id in selected:
        _append(
            policy,
            source_root,
            body,
            rows,
            state,
            None,
            source_root.get("id") or "",
            work_id,
            TOP_LEVEL_IDS.index(source_root.get("id")) + 1,
        )
    if len(rows) != assigned_census["elements"]:
        raise ValueError("37c-204 produced source feature count drift")
    accountability = _accountability(
        source_manifest, tree, selected, rows, assigned_census
    )
    provenance = _provenance(source_manifest, tree, config)
    readme = source_manifest.authority_path("attribution-readme").read_bytes()
    if b"CCEL.org" not in readme:
        raise ValueError("37c-204 attribution README does not credit CCEL.org")
    return {
        "README.source.md": readme,
        "content.tei.xml": etree.tostring(
            root, encoding="UTF-8", xml_declaration=True, pretty_print=False
        ),
        "provenance.json": _canonical(provenance),
        "source-accountability.json": _canonical(accountability),
        "unresolved.jsonl": _unresolved(),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()

__all__: tuple[str, ...] = ()
