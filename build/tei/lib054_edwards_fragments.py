"""Bind the two LIB-054 Edwards work candidates to their enclosing CCEL volumes."""

from __future__ import annotations

import hashlib
import json
from typing import Mapping

from lxml import etree

from build.tei.lib054_work_local import _convert as convert_fragment
from ocd_kernel.reconstruction.contract import SourceManifest

TEI_NS = "http://www.tei-c.org/ns/1.0"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _source_tree(data: bytes) -> etree._Element:
    return etree.fromstring(data, etree.XMLParser(
        resolve_entities=False, load_dtd=False, no_network=True,
        remove_comments=False, huge_tree=True,
    ))


def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    manifest.verify()
    volume_bindings = [item for item in manifest.record["authorities"] if item["role"] == "enclosing-volume"]
    primary_bindings = [item for item in manifest.record["authorities"] if item["role"] == "primary-source"]
    if len(volume_bindings) != 1 or len(primary_bindings) != 1:
        raise ValueError("one Edwards fragment and one enclosing volume required")
    volume_binding, fragment_binding = volume_bindings[0], primary_bindings[0]
    volume_bytes = manifest.authority_path(str(volume_binding["name"])).read_bytes()
    fragment_bytes = manifest.authority_path(str(fragment_binding["name"])).read_bytes()
    volume, fragment = _source_tree(volume_bytes), _source_tree(fragment_bytes)
    volume_body, fragment_body = volume.find("ThML.body"), fragment.find("ThML.body")
    volume_head = volume.find("ThML.head")
    if (volume.tag != "ThML" or fragment.tag != "ThML" or volume_body is None
            or volume_head is None or fragment_body is None or fragment.find("ThML.head") is not None
            or len(fragment_body) != 1 or fragment_body[0].tag != "div1"):
        raise ValueError("Edwards extraction envelope changed")
    child = fragment_body[0]
    serialized = etree.tostring(child, encoding="UTF-8", with_tail=False)
    matches = [(i, node) for i, node in enumerate(volume_body)
               if node.tag == "div1" and etree.tostring(node, encoding="UTF-8", with_tail=False) == serialized]
    if len(matches) != 1 or len(volume_body) < 3 or volume_body[-1].get("title") != "Indexes":
        raise ValueError("Edwards fragment is not one unique complete volume work division")
    ordinal, original = matches[0]
    if ordinal in (0, len(volume_body) - 1) or child.get("id") != original.get("id"):
        raise ValueError("Edwards fragment boundary is shared matter")
    volume_title = volume_head.findtext(".//DC.Title")
    if not volume_title:
        raise ValueError("enclosing CCEL volume has no title")
    index_ids = {node.get("id") for node in original.iter() if node.get("id")}
    index_backlinks = sum(
        node.get("href", "").split("#")[-1] in index_ids
        for node in volume_body[-1].iter()
        if node.tag == "a" and node.get("href") and "#" in node.get("href", "")
    )
    result = dict(convert_fragment(manifest))
    tei = _source_tree(result["content.tei.xml"])
    notes = tei.xpath("./t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl/t:note[@type='extracted-fragment']",
                      namespaces={"t": TEI_NS})
    if len(notes) != 1:
        raise ValueError("fragment provenance note missing")
    notes[0].text = (f"Exact complete div1 {child.get('id')} of {volume_binding['path']} "
                     f"({volume_title}); source child {ordinal + 1} of {len(volume_body)}. "
                     "Volume opening matter and final indexes remain collection-owned siblings.")
    accounting = json.loads(result["source-accountability.json"])
    accounting["enclosing_volume"] = {
        "path": volume_binding["path"], "sha256": _sha(volume_bytes),
        "title": volume_title, "body_child_position": ordinal + 1,
        "body_child_count": len(volume_body), "source_division_id": child.get("id"),
        "source_division_xml_sha256": _sha(serialized),
        "opening_matter_id": volume_body[0].get("id"),
        "index_id": volume_body[-1].get("id"),
        "index_backlinks_to_work": index_backlinks,
    }
    accounting["shared_matter"] = (
        "The enclosing volume's first div1 owns its title/contents/memoir; its final div1 owns "
        "the combined indexes. Both are excluded from this work-local TEI. The work title, preface, "
        "notes, and all nested sections inside the exact extracted div1 remain included."
    )
    provenance = json.loads(result["provenance.json"])
    provenance["extraction_provenance"] = "exact-complete-enclosing-volume-div1"
    provenance["enclosing_volume"] = accounting["enclosing_volume"]
    result["content.tei.xml"] = etree.tostring(tei, encoding="UTF-8", xml_declaration=True, pretty_print=False) + b"\n"
    result["source-accountability.json"] = _json(accounting)
    result["provenance.json"] = _json(provenance)
    result["README.source.md"] += (
        f"\nThe exact work division is child {ordinal + 1} of {len(volume_body)} in "
        f"`{volume_binding['path']}` (SHA-256 `{_sha(volume_bytes)}`). "
        "The enclosing volume's opening matter and combined indexes remain outside this work.\n"
    ).encode("utf-8")
    return result


_convert.converter_id = "ocd-lib054-edwards-volume-fragment-to-tei"
_convert.converter_version = "1"
