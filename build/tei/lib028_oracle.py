"""Producer-independent retained-source oracle for LIB-028 church histories."""

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


ORACLE_ID = "ocd-lib028-ccel-church-histories-source-to-tei-oracle"
ORACLE_VERSION = "1"
EXPECTED_SOURCE_ID = "ccel-schaff-npnf2-lib028-three-retained-xml-members"
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
        "npnf201",
        "retained-npnf201",
        "raw/ccel/schaff/npnf201.xml",
        5_624_937,
        "da92679dcdd452c10dab212ee4168be1d37f89f758dae8301821a96d49a261c9",
    ),
    (
        "npnf202",
        "retained-npnf202",
        "raw/ccel/schaff/npnf202.xml",
        3_292_641,
        "0139e8dcea6d40c3b1a5e046f3d45bdf6d1b30c503461d7f29f60309b4f2015c",
    ),
    (
        "npnf203",
        "retained-npnf203",
        "raw/ccel/schaff/npnf203.xml",
        4_264_937,
        "f2683481bded09cf90369589dd40330e231c83e6dbd4cb1aec730c9b90f9ec3a",
    ),
)
ASSIGNED = (
    ("npnf201", "iii", "eusebius-ecclesiastical-history"),
    ("npnf201", "iv", "eusebius-life-of-constantine"),
    ("npnf202", "ii", "socrates-ecclesiastical-history"),
    ("npnf202", "iii", "sozomen-ecclesiastical-history"),
    ("npnf203", "iv", "theodoret-ecclesiastical-history"),
)
EXPECTED_CENSUS = {
    "elements": 53_258,
    "attributes": 101_789,
    "text_nodes": 39_120,
    "tail_nodes": 41_598,
    "characters": 7_730_052,
    "non_ascii_characters": 72_586,
    "notes": 7_548,
    "page_breaks": 1_368,
    "scripture_refs": 2_083,
}
WORK_AUTHORITIES = (
    {
        "key": "npnf201",
        "root_id": "iii",
        "root_selector": "ThML.body/div1[3]",
        "work_id": "eusebius-ecclesiastical-history",
        "title": "Church History of Eusebius",
        "contributor": "Arthur Cushman McGiffert (translator, 1890)",
        "config_name": "eusebius-history-config",
        "config_path": "sources/structured-text/eusebius-ecclesiastical-history/config.json",
        "config_bytes": 1220,
        "config_sha256": "65b702d85938bd888de4de440583dd540d71837a332d46d2e258a34225ee3796",
        "binding_name": "eusebius-history-binding",
        "binding_path": "sources/structured-text/eusebius-ecclesiastical-history/lib028.work-binding.json",
        "binding_bytes": 426,
        "binding_sha256": "f6957c7c15f0a1b186beb1c905082c186e52a30141165b390d842a64680ee90a",
    },
    {
        "key": "npnf201",
        "root_id": "iv",
        "root_selector": "ThML.body/div1[4]",
        "work_id": "eusebius-life-of-constantine",
        "title": "The Life of Constantine with Orations",
        "contributor": "Ernest Cushing Richardson (translator, 1890)",
        "config_name": "eusebius-constantine-config",
        "config_path": "sources/structured-text/eusebius-life-of-constantine/config.json",
        "config_bytes": 1226,
        "config_sha256": "327468d9e2284d7f97dbc9e36f3dd37118ad293087fba2bed2b008f11138144f",
        "binding_name": "eusebius-constantine-binding",
        "binding_path": "sources/structured-text/eusebius-life-of-constantine/lib028.work-binding.json",
        "binding_bytes": 422,
        "binding_sha256": "66c35bbfff9c40707608224f5a0a7032079f653eaac92a0baef9c7e6be937965",
    },
    {
        "key": "npnf202",
        "root_id": "ii",
        "root_selector": "ThML.body/div1[2]",
        "work_id": "socrates-ecclesiastical-history",
        "title": "The Ecclesiastical History of Socrates Scholasticus",
        "contributor": "Arthur Cleveland Zenos (translator, 1890)",
        "config_name": "socrates-config",
        "config_path": "sources/structured-text/socrates-ecclesiastical-history/config.json",
        "config_bytes": 1244,
        "config_sha256": "db0418e8018bff95b9983f5eb40b1815324a813b40fd5a6f124500ff5f541191",
        "binding_name": "socrates-binding",
        "binding_path": "sources/structured-text/socrates-ecclesiastical-history/lib028.work-binding.json",
        "binding_bytes": 425,
        "binding_sha256": "0cb2a946047b0d1b10048b91b1ba4a7207bdc7d44d36f54234375977ccd9823a",
    },
    {
        "key": "npnf202",
        "root_id": "iii",
        "root_selector": "ThML.body/div1[3]",
        "work_id": "sozomen-ecclesiastical-history",
        "title": "The Ecclesiastical History of Sozomen",
        "contributor": "Chester D. Hartranft (translator, 1890)",
        "config_name": "sozomen-config",
        "config_path": "sources/structured-text/sozomen-ecclesiastical-history/config.json",
        "config_bytes": 1212,
        "config_sha256": "9a64b08882c54f2e717186067e4a17dea150d128aa18aa9fc7fc8a981e4d53be",
        "binding_name": "sozomen-binding",
        "binding_path": "sources/structured-text/sozomen-ecclesiastical-history/lib028.work-binding.json",
        "binding_bytes": 425,
        "binding_sha256": "26f505563231f2d55b36341c6be349eba2885d6791bf8e938e6c2493daa23879",
    },
    {
        "key": "npnf203",
        "root_id": "iv",
        "root_selector": "ThML.body/div1[3]",
        "work_id": "theodoret-ecclesiastical-history",
        "title": "The Ecclesiastical History, Dialogues, and Letters of Theodoret",
        "contributor": "Blomfield Jackson (translator, 1892)",
        "config_name": "theodoret-config",
        "config_path": "sources/structured-text/theodoret-ecclesiastical-history/config.json",
        "config_bytes": 1252,
        "config_sha256": "7198b82aa8e0d25dd00b6c807ef5f334ba163c8d102f3e3274e26062459d60cb",
        "binding_name": "theodoret-binding",
        "binding_path": "sources/structured-text/theodoret-ecclesiastical-history/lib028.work-binding.json",
        "binding_bytes": 426,
        "binding_sha256": "2261f920da9727a55a08bd06962d720e140466e681d50251440f272738fcc5c6",
    },
)
TEXT_AUTHORITIES = {
    "source-local-attribution-readme": (
        "sources/structured-text/eusebius-ecclesiastical-history/README.md",
        "source-attribution-readme",
        832,
        "f2717005d976477085f9c719422ba378998259baff59225128da8a18f6dbe7b0",
        ("five exact `div1` roots", "Publication remains `not_ready`."),
    ),
    "source-attribution": (
        "sources/structured-text/eusebius-ecclesiastical-history/lib028-source-attribution.md",
        "source-attribution-evidence",
        432,
        "22b833624245d13f61439efc13d44c3789ef3836d5a60eda28d10cd46ca8c2cc",
        ("Christian Classics Ethereal Library", "Philip Schaff"),
    ),
    "source-local-provenance": (
        "sources/structured-text/eusebius-ecclesiastical-history/lib028-provenance.md",
        "source-provenance-evidence",
        470,
        "826c1d37817f24e676260161a9da3afaa6feee31963b3f27ccda7f9aefc00138",
        ("exactly the three CCEL Schaff XML members", "publication is\n`not_ready`"),
    ),
    "ccel-permission": (
        "docs/sources/ccel-permission.md",
        "source-permission-evidence",
        1629,
        "e71d588f2309d0cb03f84310fe8149bbfa26309a4f1ef7a2df2b8645b14d93d1",
        ("CCEL", "permission"),
    ),
}
EXPECTED_UNRESOLVED = (
    {
        "id": "lib028-work-specific-credit-confirmation",
        "scope": "all-five-assigned-works",
        "status": "unresolved",
        "evidence": "Retained heads and five local metadata configs are hash-bound; contributor claims remain subject to human confirmation.",
    },
    {
        "id": "lib028-print-collation",
        "scope": "three-retained-electronic-witnesses",
        "status": "unresolved",
        "evidence": "The candidate is bound to retained CCEL XML; cited print editions were not collated.",
    },
    {
        "id": "lib028-rights-human-acceptance-publication",
        "scope": "all-five-assigned-works",
        "status": "unresolved",
        "evidence": "Retained headers state Public Domain; technical verification is not human acceptance or publication authorization.",
    },
)


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


def _authority_content(
    source_manifest: SourceManifest,
    name: str,
    path: str,
    role: str,
    size: int,
    digest: str,
) -> bytes:
    declarations = [
        authority
        for authority in source_manifest.record["authorities"]
        if authority.get("name") == name
    ]
    if len(declarations) != 1:
        raise ValueError(f"ticket authority declaration {name!r} drifted")
    declaration = declarations[0]
    expected = {
        "name": name,
        "path": path,
        "role": role,
        "bytes": size,
        "sha256": digest,
    }
    if dict(declaration) != expected:
        raise ValueError(f"ticket authority identity {name!r} drifted")
    content = source_manifest.authority_path(name).read_bytes()
    if len(content) != size or _sha(content) != digest:
        raise ValueError(f"ticket authority content {name!r} drifted")
    return content


def _verify_ticket_authorities(source_manifest: SourceManifest) -> dict[str, list[str]]:
    if source_manifest.record.get("source_id") != EXPECTED_SOURCE_ID:
        raise ValueError("LIB-028 expected source identity drift")

    retained_content = _authority_content(
        source_manifest,
        "retained-source-set",
        "sources/structured-text/eusebius-ecclesiastical-history/lib028-retained-source-set.json",
        "retained-member-census",
        959,
        "87b30377053f5156bbe50a9ada6d22189e4a060a60520fc8b3cc0bddbdf29f73",
    )
    retained = _authority_json(retained_content, "retained source set")
    expected_members = [
        {
            "name": f"{key}.xml",
            "bytes": size,
            "sha256": digest,
            "disposition": "include",
            "reason": reason,
        }
        for (key, _authority, _path, size, digest), reason in zip(
            SOURCES,
            (
                "LIB-028 exact roots div1 iii and iv",
                "LIB-028 exact roots div1 ii and iii",
                "LIB-028 exact root div1 iv",
            ),
            strict=True,
        )
    ]
    if retained != {
        "contract": "ocd-lib028-retained-source-set-v1",
        "family": "CCEL Schaff NPNF second series adjacent retained XML members",
        "enumerated_directory": "D:/Library/Open Christian Data/raw/ccel/schaff",
        "enumeration_pattern": "npnf2*.xml",
        "members": expected_members,
        "unaccounted_members": 0,
        "source_fetch_performed": False,
        "durable_raw_repair_performed": False,
    }:
        raise ValueError("retained source set semantic identity drift")

    source_by_key = {
        key: (path, digest) for key, _authority, path, _size, digest in SOURCES
    }
    credits: dict[str, list[str]] = {}
    for work in WORK_AUTHORITIES:
        config_content = _authority_content(
            source_manifest,
            str(work["config_name"]),
            str(work["config_path"]),
            "local-metadata-claim-evidence",
            int(work["config_bytes"]),
            str(work["config_sha256"]),
        )
        config = _authority_json(config_content, f"{work['work_id']} config")
        source_path, source_digest = source_by_key[str(work["key"])]
        expected_url = f"https://www.ccel.org/ccel/schaff/{work['key']}.xml"
        expected_output = f"data/structured-text/{work['work_id']}.json"
        expected_contributors = [
            str(work["contributor"]),
            "Philip Schaff (series editor)",
        ]
        if any(
            (
                config.get("resource_id") != work["work_id"],
                config.get("title") != work["title"],
                config.get("contributors") != expected_contributors,
                config.get("source_hash") != f"sha256:{source_digest}",
                config.get("source_url") != expected_url,
                config.get("source_format") != "ThML XML",
                config.get("license") != "public-domain",
                config.get("output_file") != expected_output,
            )
        ):
            raise ValueError(f"{work['work_id']} metadata authority drift")
        credits[str(work["work_id"])] = [
            str(work["contributor"]).split(" (", maxsplit=1)[0]
        ]

        binding_content = _authority_content(
            source_manifest,
            str(work["binding_name"]),
            str(work["binding_path"]),
            "exact-work-binding",
            int(work["binding_bytes"]),
            str(work["binding_sha256"]),
        )
        binding = _authority_json(binding_content, f"{work['work_id']} binding")
        expected_binding = {
            "contract": "ocd-lib028-work-binding-v1",
            "ticket": "LIB-028",
            "work_id": work["work_id"],
            "source_member": source_path,
            "source_sha256": source_digest,
            "source_root_id": work["root_id"],
            "source_root_selector": work["root_selector"],
            "disposition": "complete-subtree-represented",
            "human_review": "required",
            "accepted_ir": "not_accepted",
            "publication": "not_ready",
        }
        if binding != expected_binding:
            raise ValueError(f"{work['work_id']} work binding semantic drift")

    for name, (path, role, size, digest, required) in TEXT_AUTHORITIES.items():
        content = _authority_content(source_manifest, name, path, role, size, digest)
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{name} is not UTF-8") from exc
        if any(fragment not in text for fragment in required):
            raise ValueError(f"{name} semantic content drift")

    unresolved_content = _authority_content(
        source_manifest,
        "source-local-unresolved",
        "sources/structured-text/eusebius-ecclesiastical-history/lib028-unresolved.jsonl",
        "unresolved-question-evidence",
        673,
        "70b54f839be7cc9ce21b4f94864e694c15db33be43a1cc34afc6ee95c13f3e01",
    )
    try:
        unresolved = tuple(json.loads(line) for line in unresolved_content.splitlines())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("source-local unresolved authority is invalid") from exc
    if unresolved != EXPECTED_UNRESOLVED or unresolved_content != b"".join(
        _canonical(item) for item in EXPECTED_UNRESOLVED
    ):
        raise ValueError("source-local unresolved authority semantic drift")
    return credits


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


def _projection(
    policy: Mapping[str, Any],
    source: etree._Element,
    key: str,
    ordinal: int,
    work_id: str | None,
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
    selected: list[tuple[str, etree._Element, str]], policy: Mapping[str, Any]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def visit(
        key: str,
        node: etree._Element,
        parent_feature_id: str | None,
        work_id: str | None = None,
    ) -> None:
        if not isinstance(node.tag, str):
            raise ValueError("assigned source contains non-element")
        ordinal = len(rows) + 1
        feature_id = f"lib028-feature-{ordinal:06d}"
        tag, attrs, wrapper = _projection(policy, node, key, ordinal, work_id)
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
            visit(key, child, feature_id)

    for key, root, work_id in selected:
        visit(key, root, None, work_id)
    return rows


def _verify_node(
    source: etree._Element,
    target: etree._Element,
    key: str,
    policy: Mapping[str, Any],
    counter: list[int],
    work_id: str | None = None,
) -> None:
    counter[0] += 1
    tag, attrs, wrapper = _projection(policy, source, key, counter[0], work_id)
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
    for source_child in source:
        if index >= len(children):
            raise ValueError("TEI source child omitted")
        candidate_child = children[index]
        child_ordinal = counter[0] + 1
        _tag, _attrs, child_wrapper = _projection(
            policy, source_child, key, child_ordinal, None
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
        _verify_node(source_child, candidate_child, key, policy, counter)
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


def _expected_evidence(
    source_manifest: SourceManifest,
    trees: Mapping[str, etree._ElementTree],
    selected: list[tuple[str, etree._Element, str]],
    rows: list[dict[str, Any]],
    credits: Mapping[str, list[str]],
) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    members = []
    top_all = {}
    direct_all = {}
    work_bindings = []
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
        "contract": "ocd-lib028-source-accountability-v1",
        "schema": "lib028.source-accountability.schema.json",
        "profile_id": "lib028-five-church-histories-v1",
        "assigned_work_count": 5,
        "source_member_count": 3,
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
        "crosswalk": rows,
    }
    provenance = {
        "contract": "ocd-lib028-provenance-v1",
        "status": "nonaccepted",
        "source_id": source_manifest.record["source_id"],
        "publication_state": "not_ready",
        "sources": {
            key: {
                "path": path,
                "bytes": size,
                "sha256": digest,
                "metadata": _source_metadata(trees[key]),
                "retained_head_c14n_bound": True,
            }
            for key, _authority, path, size, digest in SOURCES
        },
        "works": [
            {
                **binding,
                "translation_credit": {
                    "status": "retained-work-config-claim-bound-for-review",
                    "credited_to": credits[binding["work_id"]],
                    "human_confirmation": "required",
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
    return (
        accountability,
        provenance,
        b"".join(_canonical(item) for item in EXPECTED_UNRESOLVED),
    )


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


def _import_closure_paths(
    root: Path, seeds: tuple[str, ...], forbidden: tuple[str, ...] = ()
) -> tuple[Path, ...]:
    pending = list(seeds)
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


def _closure_paths(root: Path, policy: Mapping[str, Any]) -> tuple[Path, ...]:
    return _import_closure_paths(
        root,
        ("build.tei.lib028_oracle",),
        tuple(policy.get("forbidden_oracle_imports", [])),
    )


def _producer_closure_paths(root: Path) -> tuple[Path, ...]:
    return _import_closure_paths(root, ("build.tei.lib028_reconstruction",))


def _path_records(root: Path, paths: tuple[Path, ...]) -> list[dict[str, object]]:
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "bytes": len(path.read_bytes()),
            "sha256": _sha(path.read_bytes()),
        }
        for path in paths
    ]


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


def _producer_closure_digest(root: Path) -> str:
    return _sha(_canonical(_path_records(root, _producer_closure_paths(root))))


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


def _verify_xsd_closure(
    source_manifest: SourceManifest, profile: Mapping[str, Any]
) -> None:
    closure = _authority_json(
        source_manifest.authority_path("tei-p5-xsd-closure").read_bytes(),
        "TEI P5 XSD closure",
    )
    if closure.get("contract") != "ocd-lib028-tei-xsd-closure-v1":
        raise ValueError("TEI P5 XSD closure contract drift")
    for member in closure.get("members", []):
        path = source_manifest.repository_root / member["path"]
        content = path.read_bytes()
        if len(content) != member["bytes"] or _sha(content) != member["sha256"]:
            raise ValueError("TEI P5 XSD recursive closure drift")
    producer = closure.get("producer_runtime")
    if not isinstance(producer, dict) or producer.get("contract") != (
        "ocd-lib028-producer-runtime-closure-v1"
    ):
        raise ValueError("producer runtime closure contract drift")
    expected_members = _path_records(
        source_manifest.repository_root,
        _producer_closure_paths(source_manifest.repository_root),
    )
    expected_digest = _sha(_canonical(expected_members))
    if (
        producer.get("members") != expected_members
        or producer.get("sha256") != expected_digest
        or profile.get("producer_import_closure_sha256") != expected_digest
    ):
        raise ValueError("producer runtime import closure drift")
    member_paths = {item["path"] for item in expected_members}
    if {
        "build/tei/lib028_reconstruction.py",
        "ocd_kernel/tei/writer.py",
    } - member_paths:
        raise ValueError("producer runtime import closure is incomplete")


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    credits = _verify_ticket_authorities(source_manifest)
    root = source_manifest.repository_root
    if (
        set(candidate.member_names) != MEMBERS
        or candidate.manifest.get("status") != "nonaccepted"
        or candidate.manifest.get("source_id") != EXPECTED_SOURCE_ID
        or candidate.manifest.get("source_id")
        != source_manifest.record.get("source_id")
    ):
        raise ValueError("LIB-028 candidate member or status drift")
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
    nodes = [
        node for _key, source_root, _work_id in selected for node in source_root.iter()
    ]
    if (
        _census(nodes) != EXPECTED_CENSUS
        or profile.get("assigned_census") != EXPECTED_CENSUS
    ):
        raise ValueError("independent source census drift")
    rows = _expected_rows(selected, policy)
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
    if len(works) != 5 or any(not isinstance(node.tag, str) for node in works):
        raise ValueError("TEI work count drift")
    counter = [0]
    for (key, source_root, work_id), target in zip(selected, works, strict=True):
        _verify_node(source_root, target, key, policy, counter, work_id)
    if counter[0] != EXPECTED_CENSUS["elements"]:
        raise ValueError("TEI projection count drift")
    _verify_xsd_closure(source_manifest, profile)
    schema = etree.XMLSchema(
        etree.parse(str(source_manifest.authority_path("tei-p5-xsd")))
    )
    try:
        schema.assertValid(tei)
    except etree.DocumentInvalid as exc:
        raise ValueError("candidate fails TEI P5 XSD") from exc
    expected_accountability, expected_provenance, expected_unresolved = (
        _expected_evidence(source_manifest, trees, selected, rows, credits)
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
    if (
        candidate.member_bytes("unresolved.jsonl") != expected_unresolved
        or candidate.member_bytes("unresolved.jsonl")
        != source_manifest.authority_path("source-local-unresolved").read_bytes()
    ):
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
