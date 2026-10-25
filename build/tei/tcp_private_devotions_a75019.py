"""Exact-byte EEBO-TCP A75019 candidate packaging."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest


CONVERTER_ID = "ocd-eebo-tcp-a75019-exact-tei-p5"
CONVERTER_VERSION = "1"
SOURCE_PATH = (
    "raw/tcp/high-range/A75019/A75019.xml"
)
SOURCE_SHA256 = "800bae82b44a6c45ef3d49af85e1e0dd046ace2741055a078acc9be808d69aec"


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


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_bytes = source_manifest.authority_path("retained-tei-p5").read_bytes()
    profile = json.loads(
        source_manifest.authority_path("reconstruction-profile").read_bytes()
    )
    policy = json.loads(source_manifest.authority_path("validation-policy").read_bytes())
    if len(source_bytes) != profile["source_bytes"] or _sha(source_bytes) != SOURCE_SHA256:
        raise ValueError("retained A75019 source binding drifted")
    if source_manifest.record["source_id"] != "tcp-a75019-1660":
        raise ValueError("TCP A75019 source ID drifted")
    root = _parse(source_bytes)
    counts, census = _census(root)
    if counts != profile["element_counts"] or census != profile["source_census"]:
        raise ValueError("retained A75019 source census drifted")

    accountability = {
        **policy["accountability"],
        "source_id": source_manifest.record["source_id"],
        "source_content_bytes": len(source_bytes),
        "source_content_sha256": _sha(source_bytes),
        "candidate_content_bytes": len(source_bytes),
        "candidate_content_sha256": _sha(source_bytes),
        "source_census": census,
        "element_counts": counts,
    }
    return {
        "README.source.md": source_manifest.authority_path(
            "source-local-attribution-readme"
        ).read_bytes(),
        "content.tei.xml": source_bytes,
        "provenance.json": _canonical(policy["provenance"]),
        "source-accountability.json": _canonical(accountability),
        "unresolved.jsonl": b"".join(_canonical(item) for item in policy["unresolved"]),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
