"""Source-first LIB-041 NPNF113 candidate producer.

This module reads only authorities named by the source manifest.  Current JSON
and older candidates never participate in reconstruction.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction import SourceManifest


CONVERTER_ID = "ocd-lib041-npnf113-ten-work-to-tei"
CONVERTER_VERSION = "21"
TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML}}}id"
XML_LANG = f"{{{XML}}}lang"
LANGUAGE_MAP = {"DE": "de", "EL": "grc", "HE": "he"}
TAG_MAP = {
    "div2": "div",
    "div3": "div",
    "i": "hi",
    "note": "note",
    "p": "p",
    "pb": "pb",
    "scripRef": "ref",
    "span": "seg",
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _tei(name: str, attrs: Mapping[str, str] | None = None, text: str | None = None):
    node = etree.Element(f"{{{TEI}}}{name}", nsmap={None: TEI} if name == "TEI" else None)
    for key, value in (attrs or {}).items():
        if key == "xml:id":
            node.set(XML_ID, value)
        elif key == "xml:lang":
            node.set(XML_LANG, value)
        else:
            node.set(key, value)
    node.text = text
    return node


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


def _target_tag(source: etree._Element) -> str:
    if source.tag == "span" and source.get("lang"):
        return "foreign"
    if source.tag == "scripCom":
        parent = source.getparent()
        return "p" if parent is not None and str(parent.tag).startswith("div") else "seg"
    try:
        return TAG_MAP[str(source.tag)]
    except KeyError as exc:
        raise ValueError(f"unsupported retained source element {source.tag!r}") from exc


def _target_attributes(
    source: etree._Element, ordinal: int
) -> tuple[dict[str, str], list[dict[str, str]]]:
    tag = str(source.tag)
    source_id = source.get("id")
    attrs = {
        "xml:id": "npnf113-"
        + (_safe_id(source_id) if source_id else f"feature-{ordinal:05d}")
    }
    dispositions: list[dict[str, str]] = []
    for name, value in source.attrib.items():
        destination = "source-accountability"
        method = "preserved-verbatim-in-accountability"
        if name == "id":
            destination, method = "@xml:id", "deterministic-npnf113-prefix"
        elif name == "title" and tag in {"div2", "div3"}:
            destination, method = "child::head[1]", "preserved-exactly"
        elif name == "n" and tag in {"div2", "div3", "note", "pb"}:
            attrs["n"], destination, method = value, "@n", "preserved-exactly"
        elif name == "type" and tag in {"div2", "div3"}:
            attrs["type"], destination, method = value, "@type", "preserved-exactly"
        elif name == "type" and tag == "scripCom":
            attribute = "rend" if _target_tag(source) == "p" else "type"
            attrs[attribute], destination, method = value, f"@{attribute}", "preserved-exactly"
        elif name == "class":
            attrs["rend"], destination, method = value, "@rend", "preserved-exactly"
        elif name == "place" and tag == "note":
            attrs["place"], destination, method = value, "@place", "preserved-exactly"
        elif name == "href" and tag == "pb":
            attrs["facs"], destination, method = value, "@facs", "preserved-exactly"
        elif name == "passage" and tag == "scripRef":
            attrs["cRef"], destination, method = value, "@cRef", "preserved-exactly"
        elif name == "osisRef" and tag == "scripRef":
            attrs["target"], destination, method = value, "@target", "preserved-exactly"
        elif name == "passage" and tag == "scripCom":
            attrs["n"], destination, method = value, "@n", "preserved-exactly"
        elif name == "lang" and tag == "span":
            if value not in LANGUAGE_MAP:
                raise ValueError(f"unsupported retained language code {value!r}")
            attrs["xml:lang"] = LANGUAGE_MAP[value]
            destination, method = "@xml:lang", "declared-language-code-map"
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
    elif tag == "scripCom":
        attribute = "rend" if _target_tag(source) == "p" else "type"
        attrs.setdefault(attribute, "scripture-commentary")
    return attrs, dispositions


def _normalized_attrs(node: etree._Element) -> dict[str, str]:
    return {
        "xml:id" if key == XML_ID else "xml:lang" if key == XML_LANG else key: value
        for key, value in node.attrib.items()
    }


def _append_source_feature(
    source: etree._Element,
    parent: etree._Element,
    crosswalk: list[dict[str, object]],
    *,
    work_id: str,
    root_id: str,
    parent_feature_id: str | None,
) -> None:
    ordinal = len(crosswalk) + 1
    feature_id = f"lib041-feature-{ordinal:05d}"
    attrs, dispositions = _target_attributes(source, ordinal)
    if parent_feature_id is None:
        attrs["corresp"] = f"#npnf113:{root_id}:{work_id}"
    target = _tei(_target_tag(source), attrs)
    target.text = source.text or ""
    title = source.get("title") if source.tag in {"div2", "div3"} else None
    if title is not None:
        target.append(_tei("head", text=title))
    child_ordinal = 1 + sum(1 for child in parent if isinstance(child.tag, str))
    parent.append(target)
    if parent_feature_id is None:
        target.tail = ""
        tail_disposition = "excluded-selected-root-boundary"
    else:
        target.tail = source.tail or ""
        tail_disposition = "represented"
    crosswalk.append(
        {
            "ordinal": ordinal,
            "feature_id": feature_id,
            "work_id": work_id,
            "root_id": root_id,
            "source_selector": _selector(source),
            "source_tag": source.tag,
            "source_xml_id": source.get("id"),
            "source_attributes": dict(source.attrib),
            "source_text_present": source.text is not None,
            "source_text_sha256": _sha((source.text or "").encode("utf-8")),
            "source_tail_present": source.tail is not None,
            "source_tail_sha256": _sha((source.tail or "").encode("utf-8")),
            "tail_disposition": tail_disposition,
            "tei_tag": etree.QName(target).localname,
            "tei_xml_id": target.get(XML_ID),
            "tei_parent_id": parent.get(XML_ID),
            "tei_child_ordinal": child_ordinal,
            "tei_attributes": _normalized_attrs(target),
            "attribute_dispositions": dispositions,
            "tei_selector": f"#{target.get(XML_ID)}",
            "parent_feature_id": parent_feature_id,
            "source_title_head": title,
            "disposition": "represented",
        }
    )
    for child in source:
        if not isinstance(child.tag, str):
            raise ValueError("assigned source unexpectedly contains a comment or PI")
        _append_source_feature(
            child,
            target,
            crosswalk,
            work_id=work_id,
            root_id=root_id,
            parent_feature_id=feature_id,
        )


def _census(nodes: list[etree._Element]) -> dict[str, object]:
    return {
        "elements": len(nodes),
        "attributes": sum(len(node.attrib) for node in nodes),
        "text_nodes": sum(node.text is not None for node in nodes),
        "tail_nodes": sum(node.tail is not None for node in nodes),
        "characters": sum(len((node.text or "") + (node.tail or "")) for node in nodes),
        "non_ascii_characters": sum(
            sum(ord(char) > 127 for char in (node.text or "") + (node.tail or ""))
            for node in nodes
        ),
        "tag_counts": dict(sorted(Counter(str(node.tag) for node in nodes).items())),
    }


def _comment_record(comment: etree._Comment, ordinal: int) -> dict[str, object]:
    ancestor = next(
        (item.get("id") for item in comment.iterancestors() if item.tag == "div1"),
        None,
    )
    return {
        "ordinal": ordinal,
        "ancestor_div1": ancestor,
        "text": comment.text or "",
        "text_sha256": _sha((comment.text or "").encode("utf-8")),
        "tail": comment.tail or "",
        "tail_sha256": _sha((comment.tail or "").encode("utf-8")),
    }


def _exact_head_claims(tree: etree._ElementTree) -> dict[str, object]:
    root = tree.getroot()
    head = root.find("ThML.head")
    if head is None:
        raise ValueError("retained source has no ThML.head")
    values = {}
    for key, expression in {
        "dc_title": ".//DC.Title[not(@sub)]",
        "dc_author": ".//DC.Creator[@sub='Author'][@scheme='short-form']",
        "dc_editor": ".//DC.Creator[@sub='Editor'][@scheme='short-form']",
        "dc_publisher": ".//DC.Publisher",
        "dc_rights": ".//DC.Rights",
        "dc_language": ".//DC.Language",
        "electronic_status": ".//electronicEdInfo/status",
        "print_published": ".//printSourceInfo/published",
    }.items():
        matches = head.xpath(expression)
        if len(matches) != 1:
            raise ValueError(f"retained header claim {key} is not unique")
        values[key] = "".join(matches[0].itertext())
    values["head_xml_sha256"] = _sha(etree.tostring(head, encoding="UTF-8"))
    return values


def _header(claims: Mapping[str, object], source_hash: str) -> etree._Element:
    header = _tei("teiHeader")
    file_desc = _tei("fileDesc")
    title_stmt = _tei("titleStmt")
    title_stmt.append(_tei("title", text=str(claims["dc_title"])))
    title_stmt.append(_tei("author", text=str(claims["dc_author"])))
    title_stmt.append(_tei("editor", text=str(claims["dc_editor"])))
    file_desc.append(title_stmt)
    publication_stmt = _tei("publicationStmt")
    publication_stmt.append(_tei("publisher", text=str(claims["dc_publisher"])))
    availability = _tei("availability", {"status": "restricted"})
    availability.append(
        _tei(
            "p",
            text=(
                f"Retained DC.Rights: {claims['dc_rights']}. CCEL permits parsing "
                "the retained ThML and asks for attribution; this candidate is "
                "nonaccepted and publication is not ready."
            ),
        )
    )
    publication_stmt.append(availability)
    file_desc.append(publication_stmt)
    source_desc = _tei("sourceDesc")
    bibl = _tei("bibl")
    bibl.append(_tei("title", text=str(claims["dc_title"])))
    bibl.append(_tei("publisher", text=str(claims["print_published"])))
    bibl.append(_tei("idno", {"type": "SHA-256"}, source_hash))
    source_desc.append(bibl)
    file_desc.append(source_desc)
    header.append(file_desc)
    encoding = _tei("encodingDesc")
    project = _tei("projectDesc")
    project.append(
        _tei(
            "p",
            text=(
                "Faithful projection of the ten assigned NPNF113 work roots; "
                "source root tails outside each selected subtree are excluded and accounted."
            ),
        )
    )
    encoding.append(project)
    header.append(encoding)
    return header


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    profile = json.loads(source_manifest.authority_path("reconstruction-profile").read_bytes())
    policy = json.loads(source_manifest.authority_path("validation-policy").read_bytes())
    source_path = source_manifest.authority_path("npnf113-retained-xml")
    source_content = source_path.read_bytes()
    member = profile["source_member"]
    if len(source_content) != member["bytes"] or _sha(source_content) != member["sha256"]:
        raise ValueError("retained NPNF113 authority drifted")
    tree = _parse(source_path)
    if tree.docinfo.doctype != profile["document"]["doctype"]:
        raise ValueError("retained NPNF113 doctype drifted")
    root = tree.getroot()
    body_source = root.find("ThML.body")
    if body_source is None:
        raise ValueError("retained NPNF113 has no ThML.body")
    assigned = [(str(root_id), str(work_id)) for root_id, work_id in profile["assigned"]]
    selected: list[tuple[str, str, etree._Element]] = []
    for root_id, work_id in assigned:
        matches = body_source.xpath(f".//*[@id='{root_id}']")
        if len(matches) != 1 or matches[0].tag != "div2":
            raise ValueError(f"assigned root {root_id} is not one unique div2")
        selected.append((root_id, work_id, matches[0]))
    document_order = [node.get("id") for node in body_source.iter("div2") if node.get("id") in {x[0] for x in assigned}]
    if document_order != [root_id for root_id, _ in assigned]:
        raise ValueError("assigned roots are reordered in retained source")
    selected_nodes = [
        node
        for _, _, selected_root in selected
        for node in selected_root.iter()
        if isinstance(node.tag, str)
    ]
    observed = _census(selected_nodes)
    expected = profile["expected"]
    comparisons = {
        "elements": expected["retained_elements"],
        "attributes": expected["retained_attributes"],
        "text_nodes": expected["retained_text_nodes"],
        "tail_nodes": expected["retained_tail_nodes"],
        "characters": expected["retained_characters_including_root_tails"],
        "non_ascii_characters": expected["non_ascii_characters_including_root_tails"],
        "tag_counts": expected["tag_counts"],
    }
    if observed != comparisons:
        raise ValueError(f"assigned source census drifted: {observed}")
    root_tail_records = [
        {
            "root_id": root_id,
            "tail": node.tail or "",
            "tail_sha256": _sha((node.tail or "").encode("utf-8")),
            "characters": len(node.tail or ""),
            "disposition": "excluded-selected-root-boundary",
        }
        for root_id, _, node in selected
    ]
    if sum(item["characters"] for item in root_tail_records) != expected["excluded_root_tail_characters"]:
        raise ValueError("selected-root boundary tail census drifted")
    pre_comments = tree.xpath("/comment()")
    embedded_comments = [item for item in tree.xpath("//comment()") if item.getparent() is not None]
    if len(pre_comments) != profile["document"]["pre_root_comment_count"] or len(embedded_comments) != profile["document"]["embedded_comment_count"]:
        raise ValueError("retained comment inventory drifted")
    if any(node.xpath(".//comment()") for _, _, node in selected):
        raise ValueError("assigned scope unexpectedly contains comments")
    claims = _exact_head_claims(tree)

    tei_root = _tei("TEI", {"xml:id": "lib041-npnf113-ten-work-candidate"})
    tei_root.append(_header(claims, str(member["sha256"])))
    text = _tei("text")
    body = _tei("body", {"xml:id": "lib041-npnf113-assigned-body"})
    text.append(body)
    tei_root.append(text)
    crosswalk: list[dict[str, object]] = []
    for root_id, work_id, selected_root in selected:
        _append_source_feature(
            selected_root,
            body,
            crosswalk,
            work_id=work_id,
            root_id=root_id,
            parent_feature_id=None,
        )
    if len(crosswalk) != expected["retained_elements"]:
        raise ValueError("producer crosswalk is incomplete")

    top_divisions = [child for child in body_source if isinstance(child.tag, str) and child.tag == "div1"]
    division_accounting: list[dict[str, object]] = []
    selected_ids = {root_id for root_id, _ in assigned}
    apparatus_ids = set(profile["document"]["shared_apparatus_divisions"])
    for top_ordinal, top in enumerate(top_divisions, start=1):
        top_id = str(top.get("id"))
        division_accounting.append(
            {
                "level": "div1",
                "ordinal": top_ordinal,
                "source_xml_id": top_id,
                "title": top.get("title", ""),
                "element_count": len([node for node in top.iter() if isinstance(node.tag, str)]),
                "text_sha256": _sha("".join(top.itertext()).encode("utf-8")),
                "disposition": "parent-container-partially-selected" if top_id in {"iii", "iv", "v"} else "outside-assigned-work-scope",
            }
        )
        for child_ordinal, child in enumerate(
            [item for item in top if isinstance(item.tag, str) and item.tag == "div2"], start=1
        ):
            child_id = str(child.get("id"))
            division_accounting.append(
                {
                    "level": "div2",
                    "parent_div1_id": top_id,
                    "ordinal": child_ordinal,
                    "source_xml_id": child_id,
                    "title": child.get("title", ""),
                    "element_count": len([node for node in child.iter() if isinstance(node.tag, str)]),
                    "text_sha256": _sha("".join(child.itertext()).encode("utf-8")),
                    "disposition": "assigned-work-represented" if child_id in selected_ids else "shared-title-or-preface-accounted-excluded" if child_id in apparatus_ids else "index-or-other-work-outside-ticket",
                }
            )

    complete_nodes = [node for node in root.iter() if isinstance(node.tag, str)]
    head_node = root.find("ThML.head")
    body_nodes = [node for node in body_source.iter() if isinstance(node.tag, str)]
    source_census = {
        "complete_document": _census(complete_nodes),
        "thml_head": _census([node for node in head_node.iter() if isinstance(node.tag, str)]),
        "thml_body": _census(body_nodes),
        "assigned_retained_including_root_tails": observed,
        "projected": {
            **{key: observed[key] for key in ("elements", "attributes", "text_nodes", "tail_nodes", "non_ascii_characters", "tag_counts")},
            "characters": expected["projected_characters"],
            "root_tail_characters_excluded": expected["excluded_root_tail_characters"],
        },
    }
    accountability = {
        "contract": "ocd-lib041-npnf113-source-accountability-v1",
        "profile_id": profile["profile_id"],
        "source_member": {
            **member,
            "disposition": "included retained member with ten exact assigned div2 subtrees",
        },
        "document_accounting": {
            "xml_declaration": '<?xml version="1.0" encoding="UTF-8"?>',
            "doctype": tree.docinfo.doctype,
            "root_tag": root.tag,
            "root_attributes": dict(root.attrib),
            "root_namespace_declarations": dict(root.nsmap),
            "pre_root_comments": [_comment_record(item, ordinal) for ordinal, item in enumerate(pre_comments, start=1)],
            "embedded_comments": [_comment_record(item, ordinal) for ordinal, item in enumerate(embedded_comments, start=1)],
            "assigned_comment_count": 0,
            "assigned_processing_instruction_count": 0,
            "thml_head_xml_sha256": claims["head_xml_sha256"],
            "header_claims": claims,
        },
        "scope_accounting": {
            "selected_root_ids": [root_id for root_id, _ in assigned],
            "selected_work_ids": [work_id for _, work_id in assigned],
            "root_tail_exclusions": root_tail_records,
            "shared_apparatus_divisions": list(profile["document"]["shared_apparatus_divisions"]),
            "shared_apparatus_disposition": "metadata and text identities retained in division_accounting; outside exact assigned work roots",
            "remaining_source_disposition": "front matter, editorial essay, indexes, and unassigned containers are fully counted and outside this ticket's ten work roots",
        },
        "source_census": source_census,
        "assigned_work_count": 10,
        "feature_count": len(crosswalk),
        "attribute_count": observed["attributes"],
        "omitted_feature_count": 0,
        "duplicate_feature_count": 0,
        "unresolved_feature_count": 0,
        "division_accounting": division_accounting,
        "crosswalk": crosswalk,
    }
    accountability_schema = json.loads(
        source_manifest.authority_path("source-accountability-schema").read_bytes()
    )
    errors = sorted(Draft202012Validator(accountability_schema).iter_errors(accountability), key=str)
    if errors:
        raise ValueError(f"source-accountability schema failure: {errors[0].message}")

    apparatus = [
        {
            "source_xml_id": item["source_xml_id"],
            "title": item["title"],
            "text_sha256": item["text_sha256"],
            "disposition": item["disposition"],
        }
        for item in division_accounting
        if item["level"] == "div2" and item["source_xml_id"] in apparatus_ids
    ]
    work_titles = profile["work_titles"]
    works = [
        {
            "ordinal": ordinal,
            "root_id": root_id,
            "work_id": work_id,
            "catalog_title": work_titles[work_id],
            "retained_division_title": selected_root.get("title", ""),
            "candidate_verification": "candidate_verified",
            "human_review": "human_required",
            "accepted_ir": "not_accepted",
            "publication": "not_ready",
        }
        for ordinal, (root_id, work_id, selected_root) in enumerate(selected, start=1)
    ]
    permission = source_manifest.authority_path("ccel-permission-evidence").read_bytes()
    provenance = {
        "contract": "ocd-lib041-npnf113-provenance-v1",
        "status": "nonaccepted",
        "source_id": source_manifest.record["source_id"],
        "source_member": member,
        "retained_header_claims": claims,
        "shared_apparatus": apparatus,
        "works": works,
        "legacy_config_disposition": "route and catalog evidence only; contributor, date, title, rights, and edition claims are not reconstruction authority",
        "rights": {
            "retained_dc_rights": claims["dc_rights"],
            "permission_evidence_path": "docs/sources/ccel-permission.md",
            "permission_evidence_sha256": _sha(permission),
            "attribution": "sourced via CCEL.org",
            "publication": "not_ready",
        },
        "canonical_data_written": False,
    }
    unresolved = [
        {
            "id": "lib041-print-collation-not-performed",
            "scope": "retained NPNF113 electronic witness",
            "status": "unresolved",
            "question": "Does the retained CCEL witness differ substantively from the named print edition?",
            "evidence": "The candidate is byte-bound to retained NPNF113 XML; no print collation was performed.",
        },
        {
            "id": "lib041-human-textual-acceptance",
            "scope": "ten assigned works",
            "status": "unresolved",
            "question": "Will the project maintainer accept the exact candidate?",
            "evidence": "Technical verification is separate; all ten works remain human_required and not_accepted.",
        },
        {
            "id": "lib041-publication-authorization",
            "scope": "candidate package",
            "status": "unresolved",
            "question": "Has publication been authorized?",
            "evidence": "No publication authorization exists; publication remains not_ready.",
        },
    ]
    readme = (
        "# LIB-041 retained-source attribution\n\n"
        f"Source: {claims['dc_title']}\n\n"
        "Retained member: `raw/ccel/npnf1/npnf113.xml`\n\n"
        f"SHA-256: `{member['sha256']}` ({member['bytes']} bytes)\n\n"
        "This package faithfully projects the ten assigned work roots in retained order. "
        "The title/preface apparatus, document header, shell, comments, root-boundary tails, "
        "front matter, and indexes are explicitly accounted in `source-accountability.json`.\n\n"
        "Sourced via CCEL.org. CCEL permits parsing its ThML/XML files and asks for attribution; "
        "do not sell CCEL files or derivatives of CCEL formatting. The retained header states "
        "Public Domain. Human textual acceptance is absent and publication is not ready.\n"
    ).encode("utf-8")
    if policy["candidate_status"] != "nonaccepted" or policy["publication_state"] != "not_ready":
        raise ValueError("validation policy lifecycle drifted")
    return {
        "content.tei.xml": etree.tostring(
            tei_root, encoding="UTF-8", xml_declaration=True, pretty_print=False
        ),
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
