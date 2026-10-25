"""Source-bound partial TEI reconstruction for the retained BCP 1928 HTML."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from lxml import etree

from build.parsers import bcp1928
from ocd_kernel.reconstruction.contract import SourceManifest


CONVERTER_ID = "ocd-bcp-1928-retained-html-to-tei"
CONVERTER_VERSION = "1"
_TEI = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _q(name: str) -> str:
    return f"{{{_TEI}}}{name}"


def _profile(source_manifest: SourceManifest) -> Mapping[str, object]:
    profile = json.loads(
        source_manifest.authority_path("reconstruction-profile").read_bytes()
    )
    if (
        profile.get("contract") != "ocd-bcp-1928-reconstruction-profile-v1"
        or profile.get("profile_id") != "bcp-1928-collects-retained-html-partial-v1"
    ):
        raise ValueError("BCP 1928 reconstruction profile identity mismatch")
    return profile


def _source_members(
    source_manifest: SourceManifest, profile: Mapping[str, object]
) -> tuple[dict[str, object], ...]:
    members = tuple(source_manifest.record.get("source_members", ()))
    expected_names = tuple(str(value) for value in bcp1928.SOURCE_PAGES)
    if len(members) != len(expected_names):
        raise ValueError("BCP 1928 source manifest member count drifted")
    if tuple(str(item.get("logical_name")) for item in members) != expected_names:
        raise ValueError("BCP 1928 source member order drifted")

    primary = tuple(
        item
        for item in source_manifest.record["authorities"]
        if item.get("role") == "primary-source"
    )
    primary_by_path = {str(item["path"]): item for item in primary}
    if len(primary_by_path) != len(members):
        raise ValueError("BCP 1928 primary-source authority count drifted")

    observed: list[dict[str, object]] = []
    bundle_hash = hashlib.sha256()
    total_bytes = 0
    for order, member in enumerate(members):
        path = str(member["path"])
        logical_name = str(member["logical_name"])
        if path != f"raw/bcp-1928/{logical_name}":
            raise ValueError("BCP 1928 source member path is not canonical")
        authority = primary_by_path.get(path)
        if authority is None or authority.get("name") != logical_name:
            raise ValueError("BCP 1928 source member lacks matching primary authority")
        content = (source_manifest.repository_root / path).read_bytes()
        identity = {
            "name": logical_name,
            "path": path,
            "bytes": len(content),
            "sha256": _sha(content),
            "order": order,
        }
        if (
            identity["bytes"] != member.get("bytes")
            or identity["sha256"] != member.get("sha256")
            or identity["bytes"] != authority.get("bytes")
            or identity["sha256"] != authority.get("sha256")
        ):
            raise ValueError(f"BCP 1928 source member drifted: {path}")
        observed.append(identity)
        total_bytes += len(content)
        bundle_hash.update(content)

    expected_bundle = profile["source_bundle"]
    if {
        "members": len(observed),
        "bytes": total_bytes,
        "sha256": bundle_hash.hexdigest(),
    } != expected_bundle:
        raise ValueError("BCP 1928 source bundle does not match its profile")
    declared_bundle = source_manifest.record.get("source_bundle")
    if declared_bundle != expected_bundle:
        raise ValueError("BCP 1928 source manifest bundle does not match its profile")
    return tuple(observed)


def _extract_records(
    source_manifest: SourceManifest, members: tuple[dict[str, object], ...]
) -> tuple[tuple[dict[str, object], ...], tuple[str, ...]]:
    records: list[dict[str, object]] = []
    pages_without_collect: list[str] = []
    for member in members:
        logical_name = str(member["name"])
        content = (source_manifest.repository_root / str(member["path"])).read_bytes()
        page_records, errors = bcp1928.extract_collects_from_html(content, logical_name)
        if errors:
            raise ValueError(f"BCP 1928 source parser rejected {logical_name}")
        if not page_records:
            pages_without_collect.append(logical_name)
        for record in page_records:
            enriched = dict(record)
            enriched["source_path"] = str(member["path"])
            enriched["source_page_order"] = int(member["order"])
            records.append(enriched)
    expected = {"Trinity23.html", "Trinity24.html"}
    if set(pages_without_collect) != expected:
        raise ValueError("BCP 1928 pages without collect marker drifted")
    if len(records) != 100:
        raise ValueError(f"BCP 1928 retained collect count drifted: {len(records)}")
    if len({str(record["prayer_id"]) for record in records}) != len(records):
        raise ValueError("BCP 1928 retained collect IDs are not unique")
    return tuple(records), tuple(pages_without_collect)


def _tei_header(profile: Mapping[str, object], bundle_sha256: str) -> etree._Element:
    header = etree.Element(_q("teiHeader"))
    file_desc = etree.SubElement(header, _q("fileDesc"))
    title_stmt = etree.SubElement(file_desc, _q("titleStmt"))
    etree.SubElement(title_stmt, _q("title")).text = str(profile["title"])
    publication = etree.SubElement(file_desc, _q("publicationStmt"))
    etree.SubElement(publication, _q("publisher")).text = "Open Christian Data"
    availability = etree.SubElement(publication, _q("availability"), status="restricted")
    etree.SubElement(availability, _q("p")).text = (
        "Nonaccepted source-bound candidate; technical reconstruction does not "
        "establish human acceptance or publication authorization."
    )
    source_desc = etree.SubElement(file_desc, _q("sourceDesc"))
    bibl = etree.SubElement(source_desc, _q("bibl"))
    etree.SubElement(bibl, _q("title")).text = str(profile["title"])
    etree.SubElement(bibl, _q("ref"), target=str(profile["source_url"])).text = (
        "Retained source provider"
    )
    etree.SubElement(bibl, _q("idno"), type="SHA-256").text = bundle_sha256
    encoding = etree.SubElement(header, _q("encodingDesc"))
    project = etree.SubElement(encoding, _q("projectDesc"))
    etree.SubElement(project, _q("p")).text = (
        "The two Trinity manual claims are not represented because their exact "
        "alternate witness bytes remain unretained."
    )
    revision = etree.SubElement(header, _q("revisionDesc"))
    etree.SubElement(revision, _q("change"), status="candidate").text = (
        "Deterministic partial reconstruction from 100 retained HTML members."
    )
    return header


def _build_tei(
    profile: Mapping[str, object],
    members: tuple[dict[str, object], ...],
    records: tuple[dict[str, object], ...],
) -> bytes:
    root = etree.Element(_q("TEI"), nsmap={None: _TEI})
    root.append(_tei_header(profile, str(profile["source_bundle"]["sha256"])))
    body = etree.SubElement(etree.SubElement(root, _q("text")), _q("body"))
    collection = etree.SubElement(body, _q("div"), type="collection")
    collection.set(_XML_ID, "bcp-1928-collects")
    by_page: dict[str, list[dict[str, object]]] = {}
    for record in records:
        by_page.setdefault(str(record["source_path"]), []).append(record)

    for member in members:
        path = str(member["path"])
        page_id = "page-" + re.sub(r"[^a-zA-Z0-9]+", "-", str(member["name"])).strip("-").lower()
        page = etree.SubElement(collection, _q("div"), type="source-page", n=str(member["name"]))
        page.set(_XML_ID, page_id)
        etree.SubElement(page, _q("note"), type="source-page").text = (
            f"Retained source page: {path}"
        )
        page_records = by_page.get(path, [])
        if not page_records:
            etree.SubElement(page, _q("note"), type="source-page-without-collect").text = (
                "No collect is present in the retained HTML; the alternate witness "
                "claim remains unresolved."
            )
        for record in page_records:
            prayer_id = str(record["prayer_id"])
            collect = etree.SubElement(page, _q("div"), type="collect", n=prayer_id)
            collect.set(_XML_ID, f"collect-{prayer_id}")
            etree.SubElement(collect, _q("head")).text = str(record["title"])
            paragraph = etree.SubElement(collect, _q("p"))
            paragraph.set(_XML_ID, f"text-{prayer_id}")
            paragraph.text = str(record["content_blocks"][0])
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)


def _accountability(
    source_manifest: SourceManifest,
    profile: Mapping[str, object],
    members: tuple[dict[str, object], ...],
    records: tuple[dict[str, object], ...],
    pages_without_collect: tuple[str, ...],
    tei_bytes: bytes,
) -> dict[str, object]:
    source_records = [
        {
            "id": str(record["prayer_id"]),
            "source_path": str(record["source_path"]),
            "source_page_order": int(record["source_page_order"]),
            "title": str(record["title"]),
            "text": str(record["content_blocks"][0]),
            "text_sha256": _sha(str(record["content_blocks"][0]).encode("utf-8")),
            "word_count": int(record["word_count"]),
            "tei_id": f"collect-{record['prayer_id']}",
            "disposition": "represented",
        }
        for record in records
    ]
    manual_claims = []
    for claim_id, claim in sorted(bcp1928.MANUAL_COLLECTS.items()):
        manual_claims.append(
            {
                "id": claim_id,
                "source_page": f"{claim_id.title()}.html",
                "alternate_witness": "archive.org/details/1928bookofcommon0000prot",
                "scan_pages": [222 if claim_id == "trinity23" else 223],
                "claim_text_sha256": _sha(str(claim["text"]).encode("utf-8")),
                "status": "unbound-alternate-witness",
            }
        )
    return {
        "contract": "ocd-bcp-1928-source-accountability-v1",
        "schema": "sources/prayers/bcp-1928-collects/bcp-1928-collects.source-accountability.schema.json",
        "profile_id": str(profile["profile_id"]),
        "work_id": "bcp-1928-collects",
        "source_id": str(source_manifest.record["source_id"]),
        "source_bundle": dict(profile["source_bundle"]),
        "source_members": list(members),
        "record_count": len(source_records),
        "records": source_records,
        "pages_without_collect": list(pages_without_collect),
        "manual_claims": manual_claims,
        "tei": {"bytes": len(tei_bytes), "sha256": _sha(tei_bytes)},
        "omitted_record_count": 2,
        "duplicated_record_count": 0,
    }


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    profile = _profile(source_manifest)
    members = _source_members(source_manifest, profile)
    records, pages_without_collect = _extract_records(source_manifest, members)
    tei_bytes = _build_tei(profile, members, records)
    accountability = _accountability(
        source_manifest, profile, members, records, pages_without_collect, tei_bytes
    )
    authorities = {
        str(item["name"]): {
            key: item[key]
            for key in ("path", "bytes", "sha256", "role")
            if key in item
        }
        for item in source_manifest.record["authorities"]
    }
    provenance = {
        "contract": "ocd-bcp-1928-candidate-provenance-v1",
        "status": "nonaccepted",
        "source_manifest_sha256": source_manifest.sha256,
        "source_bundle": dict(profile["source_bundle"]),
        "authorities": authorities,
        "scope": "100 retained HTML members; 100 page-derived collects; two manual claims unresolved",
        "rights": {"status": "human-review-required", "publication_authorized": False},
    }
    unresolved = [
        {
            "id": claim_id,
            "kind": "alternate-witness",
            "status": "unbound",
            "source_page": f"{claim_id.title()}.html",
            "witness": "archive.org/details/1928bookofcommon0000prot",
            "scan_page": 222 if claim_id == "trinity23" else 223,
            "reason": "manual text exists in the legacy producer but no exact retained witness bytes are bound",
        }
        for claim_id in ("trinity23", "trinity24")
    ]
    unresolved.extend(
        {"id": gate, "kind": "review-gate", "status": "open"}
        for gate in (
            "candidate-human-acceptance",
            "rights-clearance",
            "cvw-visual-review",
            "durable-admission",
            "publication-authorization",
        )
    )
    readme = (
        "# BCP 1928 Collects retained-source candidate\n\n"
        "This nonaccepted candidate reconstructs the 100 retained HTML pages and "
        "their 100 page-derived collect records. Trinity 23 and Trinity 24 are "
        "left unresolved: the legacy producer records an Internet Archive scan "
        "claim, but those exact witness bytes are not retained and therefore are "
        "not represented in the TEI. Technical validation does not establish "
        "human acceptance, rights clearance, or publication authorization.\n"
    ).encode("utf-8")
    return {
        "content.tei.xml": tei_bytes,
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()

