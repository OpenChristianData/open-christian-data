"""Package the complete retained TCP N00001 TEI without changing its bytes."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest


CONVERTER_ID = "ocd-tcp-n00001-exact-tei-p5"
CONVERTER_VERSION = "1"
SOURCE_ID = "tcp-N00001"
SOURCE_SHA256 = "3016f74bcce71ffa67f7b87e55db64ffcd54a28ad29899251582d2e784a6df7e"


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _census(content: bytes) -> tuple[dict[str, int], dict[str, int]]:
    root = etree.fromstring(
        content,
        etree.XMLParser(
            resolve_entities=False,
            load_dtd=False,
            no_network=True,
            remove_comments=False,
            huge_tree=True,
        ),
    )
    elements = list(root.iter())
    counts = dict(sorted(Counter(etree.QName(item).localname for item in elements).items()))
    census = {
        "elements": len(elements),
        "attributes": sum(len(item.attrib) for item in elements),
        "text_nodes": sum(item.text is not None for item in elements),
        "tail_nodes": sum(item.tail is not None for item in elements),
        "characters": sum(len((item.text or "") + (item.tail or "")) for item in elements),
    }
    return counts, census


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    if source_manifest.record.get("source_id") != SOURCE_ID:
        raise ValueError("N00001 source identity differs")
    source = source_manifest.authority_path("retained-tei-p5").read_bytes()
    profile = json.loads(
        source_manifest.authority_path("reconstruction-profile").read_text(encoding="utf-8")
    )
    policy = json.loads(
        source_manifest.authority_path("validation-policy").read_text(encoding="utf-8")
    )
    receipt = json.loads(
        source_manifest.authority_path("acquisition-receipt").read_text(encoding="utf-8")
    )
    source_sha = sha256(source).hexdigest()
    member = receipt.get("member", {})
    if (
        len(source) != profile.get("source_bytes")
        or source_sha != SOURCE_SHA256
        or source_sha != profile.get("source_sha256")
        or member.get("path") != profile.get("source_path")
        or member.get("bytes") != len(source)
        or member.get("sha256") != source_sha
    ):
        raise ValueError("retained N00001 source or acquisition binding drifted")
    counts, census = _census(source)
    if counts != profile.get("element_counts") or census != profile.get("source_census"):
        raise ValueError("retained N00001 source census drifted")
    if policy.get("source_id") != SOURCE_ID:
        raise ValueError("N00001 validation policy source binding drifted")
    accountability = policy["accountability"] | {
        "source_id": SOURCE_ID,
        "source_content_bytes": len(source),
        "source_content_sha256": source_sha,
        "candidate_content_bytes": len(source),
        "candidate_content_sha256": source_sha,
        "element_counts": counts,
        "source_census": census,
        "source_features": profile["source_features"],
        "acquisition_receipt_sha256": sha256(
            source_manifest.authority_path("acquisition-receipt").read_bytes()
        ).hexdigest(),
        "member_inventory_sha256": sha256(
            source_manifest.authority_path("member-inventory").read_bytes()
        ).hexdigest(),
    }
    return {
        "README.source.md": source_manifest.authority_path("source-credit").read_bytes(),
        "content.tei.xml": source,
        "provenance.json": _canonical(policy["provenance"]),
        "source-accountability.json": _canonical(accountability),
        "unresolved.jsonl": b"".join(_canonical(item) for item in policy["unresolved"]),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
