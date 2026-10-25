"""Byte-preserving PTA TEI source route for exact single-title candidates."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lxml import etree
from ocd_kernel.reconstruction import SourceManifest

TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _parse(data: bytes) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, recover=False, huge_tree=False)
    return etree.fromstring(data, parser=parser)


def _features(data: bytes) -> dict[str, object]:
    root = _parse(data)
    ns = {"tei": TEI}
    if etree.QName(root).namespace != TEI or etree.QName(root).localname != "TEI":
        raise ValueError("retained PTA source must have a TEI P5 root")
    titles = root.xpath("./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", namespaces=ns)
    if len(titles) != 1:
        raise ValueError(f"source must declare exactly one top-level title, got {len(titles)}")
    body = root.find(f"{{{TEI}}}text/{{{TEI}}}body")
    if body is None:
        raise ValueError("retained PTA TEI is missing text/body")
    carriers = []
    for position, node in enumerate(body, 1):
        carriers.append({
            "position": position,
            "tag": etree.QName(node).localname if isinstance(node.tag, str) else "comment",
            "type": node.get("type"), "n": node.get("n"), "xml_id": node.get(XML_ID),
            "text_sha256": _sha("".join(node.itertext()).encode("utf-8")),
        })
    return {
        "root_name": "TEI", "root_namespace": TEI, "root_xml_id": root.get(XML_ID),
        "tei_root_count": len(root.xpath("//tei:TEI", namespaces=ns)),
        "tei_element_count": len(root.xpath("//*")),
        "title": " ".join("".join(titles[0].itertext()).split()),
        "title_count": len(titles), "language": root.get("{http://www.w3.org/XML/1998/namespace}lang"),
        "body_direct_child_count": len(body),
        "body_text_sha256": _sha("".join(body.itertext()).encode("utf-8")),
        "whole_document_text_sha256": _sha("".join(root.itertext()).encode("utf-8")),
        "body_carriers": carriers,
    }


def _convert(source: SourceManifest) -> dict[str, bytes]:
    profile_bytes = source.authority_path("complete-source-feature-profile").read_bytes()
    profile = json.loads(profile_bytes)
    source_path = source.authority_path("primary-source")
    source_bytes = source_path.read_bytes()
    source_sha = _sha(source_bytes)
    if source_sha != profile["source_sha256"] or len(source_bytes) != profile["source_bytes"]:
        raise ValueError("retained PTA TEI no longer matches the hash-bound route profile")
    receipt = json.loads(source.authority_path("acquisition-receipt").read_bytes())
    if receipt["retained_file"]["sha256"] != source_sha or receipt["retained_file"]["bytes"] != len(source_bytes):
        raise ValueError("PTA acquisition receipt does not bind exact retained bytes")
    feature = _features(source_bytes)
    if feature["title"] != profile["source_title"] or feature["tei_root_count"] != 1:
        raise ValueError("PTA source title or one-root boundary differs from route profile")
    if feature != profile["source_feature_inventory"]:
        raise ValueError("current PTA source feature inventory differs from the hash-bound profile")
    accounting = {
        "contract": "ocd-pta-exact-tei-source-accounting-v1",
        "manifest_row": profile["manifest_row"], "work_id": source.record["work_id"],
        "source_id": source.record["source_id"], "scope_id": profile["scope_id"],
        "canonical_title": profile["canonical_title"], "source_title": profile["source_title"],
        "cts_urn": profile["cts_urn"], "pinned_commit": profile["pinned_commit"],
        "source_path": profile["source_path"], "source_sha256": source_sha,
        "source_bytes": len(source_bytes), "candidate_tei_sha256": source_sha,
        "candidate_tei_bytes": len(source_bytes), "copy_mode": "exact-byte-preserving-retained-TEI",
        "source_scope": profile["source_scope"], "coverage_limits": profile["coverage_limits"],
        "file_level_license": profile["file_level_license"],
        "one_top_level_title_per_tei": True, "whole_source_member_represented_once": True,
        "feature_inventory": feature,
    }
    policy = json.loads(source.authority_path("independent-validation-policy").read_bytes())
    unresolved = b"".join(_canonical(item) for item in policy["unresolved"])
    return {
        "content.tei.xml": source_bytes,
        "source-accountability.json": _canonical(accounting),
        "unresolved.jsonl": unresolved,
        "README.source.md": source.authority_path("source-attribution").read_bytes(),
        "provenance.json": _canonical(policy["provenance"]),
    }


_convert.converter_id = "ocd-pta-retained-tei-byte-preserving-converter"
_convert.converter_version = "2"
