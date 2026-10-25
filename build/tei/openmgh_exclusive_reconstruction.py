"""Source-native child-work extraction from retained openMGH TEI volumes.

Only profiles with an exclusive, verified ``div type="work"`` are supported.
The containing volume and downloaded ZIP remain acquisition context.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest


TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML}}}id"
PROFILE = "reconstruction-profile"
CONVERTER_ID = "ocd-openmgh-exclusive-div-to-tei"
CONVERTER_VERSION = "1"


def _tag(name: str) -> str:
    return f"{{{TEI}}}{name}"


def _json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _profile(manifest: SourceManifest) -> dict[str, object]:
    result = json.loads(manifest.authority_path(PROFILE).read_text(encoding="utf-8"))
    if result.get("contract") != "ocd-openmgh-exclusive-profile-v1":
        raise ValueError("openMGH profile contract is invalid")
    return result


def _source_div(
    manifest: SourceManifest, profile: Mapping[str, object]
) -> tuple[etree._Element, etree._Element, etree._Element]:
    raw = manifest.authority_path("extracted-xml").read_bytes()
    if _digest(raw) != profile.get("source_sha256"):
        raise ValueError("extracted XML hash drifted")
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True
    )
    root = etree.fromstring(raw, parser=parser)
    if root.tag != _tag("TEI") or root.getroottree().docinfo.doctype:
        raise ValueError("source is not an entity-free TEI document")
    body = root.find(f"{_tag('text')}/{_tag('body')}")
    if body is None:
        raise ValueError("source TEI body is missing")
    volumes = [
        node
        for node in body
        if node.tag == _tag("div") and node.get("type") == "volume"
    ]
    if len(volumes) != 1:
        raise ValueError("exclusive route requires one volume div")
    volume = volumes[0]
    works = [
        node
        for node in volume
        if node.tag == _tag("div") and node.get("type") == "work"
    ]
    if len(works) != profile.get("volume_work_count"):
        raise ValueError("volume work count drifted")
    ordinal = profile.get("work_div_ordinal")
    if not isinstance(ordinal, int) or not 1 <= ordinal <= len(works):
        raise ValueError("work div ordinal is invalid")
    selected = works[ordinal - 1]
    if selected.get("n") != profile.get("work_div_n"):
        raise ValueError("selected work title drifted")
    for name in ("start_xml_id", "end_xml_id"):
        xml_id = profile.get(name)
        matches = root.xpath(
            "//*[@xml:id=$value]", namespaces={"xml": XML}, value=xml_id
        )
        if len(matches) != 1 or selected not in matches[0].iterancestors():
            raise ValueError(f"{name} is not unique inside the selected work")
    if (works[ordinal - 2].get("n") if ordinal > 1 else None) != profile.get(
        "preceding_work_n"
    ):
        raise ValueError("preceding work boundary drifted")
    if (works[ordinal].get("n") if ordinal < len(works) else None) != profile.get(
        "following_work_n"
    ):
        raise ValueError("following work boundary drifted")
    return root, volume, selected


def _candidate_xml(
    root: etree._Element, selected: etree._Element, profile: Mapping[str, object]
) -> bytes:
    output = etree.Element(_tag("TEI"), nsmap={None: TEI})
    output.set(XML_ID, f"ocd-{profile['work_id']}-electronic-v1")
    header = etree.SubElement(output, _tag("teiHeader"))
    file_desc = etree.SubElement(header, _tag("fileDesc"))
    title_stmt = etree.SubElement(file_desc, _tag("titleStmt"))
    etree.SubElement(title_stmt, _tag("title")).text = str(profile["work_title"])
    source_header = root.find(_tag("teiHeader"))
    if source_header is None:
        raise ValueError("source TEI header is missing")
    source_publication = source_header.find(
        f"{_tag('fileDesc')}/{_tag('publicationStmt')}"
    )
    source_bibl = source_header.find(
        f"{_tag('fileDesc')}/{_tag('sourceDesc')}/{_tag('biblFull')}"
    )
    if source_publication is None or source_bibl is None:
        raise ValueError(
            "source publication, rights, or volume bibliography is missing"
        )
    file_desc.append(deepcopy(source_publication))
    source_desc = etree.SubElement(file_desc, _tag("sourceDesc"))
    source_desc.append(deepcopy(source_bibl))
    text = etree.SubElement(output, _tag("text"))
    body = etree.SubElement(text, _tag("body"))
    body.append(deepcopy(selected))
    return etree.tostring(output, encoding="UTF-8", xml_declaration=True)


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    profile = _profile(source_manifest)
    root, volume, selected = _source_div(source_manifest, profile)
    source = source_manifest.authority_path("extracted-xml").read_bytes()
    counts = Counter(
        etree.QName(node).localname
        for node in selected.iter()
        if isinstance(node.tag, str)
    )
    work_id = str(profile["work_id"])
    edition_id = str(profile["edition_id"])
    acquisition_id = str(profile["acquisition_id"])
    accounting = {
        "contract": "ocd-openmgh-exclusive-accounting-v1",
        "work_id": work_id,
        "edition_id": edition_id,
        "acquisition_id": acquisition_id,
        "source_path": profile["source_path"],
        "source_sha256": _digest(source),
        "work_div_n": selected.get("n"),
        "work_div_ordinal": profile["work_div_ordinal"],
        "volume_work_count": profile["volume_work_count"],
        "start_xml_id": profile["start_xml_id"],
        "end_xml_id": profile["end_xml_id"],
        "preceding_work_n": profile["preceding_work_n"],
        "following_work_n": profile["following_work_n"],
        "element_counts": dict(sorted(counts.items())),
        "source_div_c14n_sha256": _digest(
            etree.tostring(selected, method="c14n", with_comments=True)
        ),
        "source_header_disposition": "Original electronic publication statement, license, and printed-volume bibliography copied into the child TEI header; other volume metadata stays with the source.",
        "outside_work_disposition": "Other work divs and volume shell are retained in the acquired XML and excluded from this child candidate.",
        "zip_disposition": "Original ZIP is a retained acquisition package, not a text source.",
    }
    provenance = {
        "contract": "ocd-openmgh-exclusive-provenance-v1",
        "status": "nonaccepted",
        "work_id": work_id,
        "edition_id": edition_id,
        "acquisition_id": acquisition_id,
        "source_path": profile["source_path"],
        "source_sha256": _digest(source),
        "canonical_ir_written": False,
        "publication": "not-ready",
    }
    unresolved = [
        {
            "status": "unresolved",
            "item": "Human visual review of the child work and its exact source boundary has not occurred.",
        },
        {
            "status": "unresolved",
            "item": "Print-edition identity and public rights/attribution deliverable require separate review.",
        },
    ]
    readme = (
        f"# {profile['work_title']} — openMGH child-work candidate\n\n"
        f"Retained text source: `{profile['source_path']}` (SHA-256 `{_digest(source)}`).\n"
        f"Work div: `{selected.get('n')}`, ordinal {profile['work_div_ordinal']} of {profile['volume_work_count']}.\n"
        f"Acquisition: `{acquisition_id}`. The downloaded ZIP is a package only.\n\n"
        "The source electronic license and print-volume bibliography are carried in the TEI header. "
        "Monumenta Germaniae Historica (MGH) and the Bavarian State Library ask derivative distributors to name them; "
        "publication attribution and rights review remain separate.\n"
    ).encode("utf-8")
    return {
        "content.tei.xml": _candidate_xml(root, selected, profile),
        "source-accountability.json": _json(accounting),
        "provenance.json": _json(provenance),
        "unresolved.jsonl": b"".join(_json(item) for item in unresolved),
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION


__all__ = ("_convert",)
