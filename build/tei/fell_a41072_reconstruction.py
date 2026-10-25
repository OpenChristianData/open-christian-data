"""Package the complete retained A41072 TEI witness without changing its bytes."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest


CONVERTER_ID = "ocd-tcp-a41072-exact-tei-p5"
CONVERTER_VERSION = "1"
SOURCE_SHA256 = "6050d2fee9b03d63ec4cf52d137ea025a2404e09ff736f550d6b8d97d4316379"


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def _census(content: bytes) -> tuple[dict[str, int], dict[str, int]]:
    root = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True))
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
    source = source_manifest.authority_path("retained-tei-p5").read_bytes()
    profile = json.loads(source_manifest.authority_path("reconstruction-profile").read_bytes())
    policy = json.loads(source_manifest.authority_path("validation-policy").read_bytes())
    source_sha = sha256(source).hexdigest()
    if len(source) != profile["source_bytes"] or source_sha != SOURCE_SHA256 or source_sha != profile["source_sha256"]:
        raise ValueError("retained A41072 source binding drifted")
    counts, census = _census(source)
    if counts != profile["element_counts"] or census != profile["source_census"]:
        raise ValueError("retained A41072 source census drifted")
    if policy["source_id"] != source_manifest.record["source_id"]:
        raise ValueError("A41072 policy source binding drifted")
    accountability = policy["accountability"] | {
        "source_id": source_manifest.record["source_id"],
        "source_content_bytes": len(source),
        "source_content_sha256": source_sha,
        "candidate_content_bytes": len(source),
        "candidate_content_sha256": source_sha,
        "element_counts": counts,
        "source_census": census,
    }
    return {
        "README.source.md": source_manifest.authority_path("source-local-attribution-readme").read_bytes(),
        "content.tei.xml": source,
        "provenance.json": _canonical(policy["provenance"]),
        "source-accountability.json": _canonical(accountability),
        "unresolved.jsonl": b"".join(_canonical(row) for row in policy["unresolved"]),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
