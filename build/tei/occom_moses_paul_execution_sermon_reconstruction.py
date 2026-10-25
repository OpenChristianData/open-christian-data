"""Exact-byte Evans-TCP N09814 candidate packaging."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest


CONVERTER_ID = "ocd-evans-tcp-n09814-exact-tei-p5"
CONVERTER_VERSION = "2"
SOURCE_PATH = (
    "raw/clean-ready-acquisition-to-tei/master-2/15/"
    "occom-moses-paul-execution-sermon/N09814.xml"
)
SOURCE_SHA256 = "56d612750fed73102ec0daa1afbbd9182cfe3660275f957fb535fd86d11a3d1a"
WORK_ID = "occom-moses-paul-execution-sermon"
PAGE_MILESTONES_SHA256 = (
    "e114466b2a7f7ce8088c1b8dbf5591260befb5c56445ac39fd3c3d9cd48ec155"
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _parse(content: bytes) -> etree._Element:
    return etree.fromstring(
        content,
        etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            remove_comments=False,
            huge_tree=True,
        ),
    )


def _census(root: etree._Element) -> tuple[dict[str, int], dict[str, int]]:
    elements = list(root.iter())
    counts = Counter(etree.QName(element).localname for element in elements)
    census = {
        "elements": len(elements),
        "attributes": sum(len(element.attrib) for element in elements),
        "text_nodes": sum(element.text is not None for element in elements),
        "tail_nodes": sum(element.tail is not None for element in elements),
        "characters": sum(
            len((element.text or "") + (element.tail or "")) for element in elements
        ),
    }
    return dict(sorted(counts.items())), census


def _page_milestones(root: etree._Element) -> list[dict[str, object]]:
    pages = [
        item for item in root.iter() if etree.QName(item).localname == "pb"
    ]
    return [
        {"ordinal": ordinal, "n": page.get("n"), "facs": page.get("facs")}
        for ordinal, page in enumerate(pages, start=1)
    ]


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_bytes = source_manifest.authority_path("retained-tei-p5").read_bytes()
    profile = json.loads(
        source_manifest.authority_path("reconstruction-profile").read_bytes()
    )
    policy = json.loads(source_manifest.authority_path("validation-policy").read_bytes())
    source_sha256 = _sha(source_bytes)
    if (
        len(source_bytes) != profile["source_bytes"]
        or source_sha256 != SOURCE_SHA256
        or source_sha256 != profile["source_sha256"]
    ):
        raise ValueError("retained N09814 source binding drifted")
    if (
        policy["source_id"] != source_manifest.record["source_id"]
        or policy.get("work_id") != WORK_ID
        or profile.get("work_id") != WORK_ID
        or source_manifest.record.get("work_id") != WORK_ID
    ):
        raise ValueError("N09814 source/work identity binding drifted")

    root = _parse(source_bytes)
    counts, census = _census(root)
    if counts != profile["element_counts"] or census != profile["source_census"]:
        raise ValueError("retained N09814 source census drifted")
    page_milestones = _page_milestones(root)
    page_milestones_sha256 = _sha(_canonical(page_milestones))
    if (
        len(page_milestones) != 32
        or len({item["facs"] for item in page_milestones}) != 18
        or page_milestones_sha256 != PAGE_MILESTONES_SHA256
    ):
        raise ValueError("retained N09814 page/facsimile milestone order drifted")

    accountability = {
        **policy["accountability"],
        "source_id": source_manifest.record["source_id"],
        "source_content_bytes": len(source_bytes),
        "source_content_sha256": source_sha256,
        "candidate_content_bytes": len(source_bytes),
        "candidate_content_sha256": source_sha256,
        "source_census": census,
        "element_counts": counts,
        "page_milestones": page_milestones,
        "page_milestones_sha256": page_milestones_sha256,
        "unique_facsimile_targets": 18,
    }
    return {
        "README.source.md": source_manifest.authority_path(
            "source-local-attribution-readme"
        ).read_bytes(),
        "content.tei.xml": source_bytes,
        "provenance.json": _canonical(policy["provenance"]),
        "source-accountability.json": _canonical(accountability),
        "unresolved.jsonl": b"".join(
            _canonical(item) for item in policy["unresolved"]
        ),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
