
"""Versioned single-work DocSouth TEI.2 to P5 route with retained figure bindings."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Mapping
from build.tei.docsouth_l761_l762 import _migrate, _read
from ocd_kernel.reconstruction.contract import SourceManifest

CONVERTER_ID = "ocd-docsouth-l763-jamison-tei2-to-p5-retained-images"
CONVERTER_VERSION = "2"
def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
def _retained_image_assets(manifest: SourceManifest, receipt: dict, profile: dict) -> list[dict]:
    rows = receipt.get("image_members")
    seq = profile.get("figure_entity_sequence")
    assets = profile.get("retained_image_assets")
    if not isinstance(rows, list) or not isinstance(seq, list) or not isinstance(assets, list):
        raise ValueError("retained image inventory is absent")
    by_entity = {row.get("entity"): row for row in rows if isinstance(row, dict)}
    asset_by_entity = {row.get("entity"): row for row in assets if isinstance(row, dict)}
    if len(by_entity) != len(rows) or len(asset_by_entity) != len(assets):
        raise ValueError("retained image entity inventory contains duplicates")
    if set(seq) != set(by_entity) or set(seq) != set(asset_by_entity) or len(seq) != len(assets):
        raise ValueError("retained image entities differ from exact source figure inventory")
    result = []
    for entity in seq:
        source = by_entity[entity]
        asset = asset_by_entity[entity]
        name = "retained-image-" + entity
        raw = manifest.authority_path(name).read_bytes()
        expected = {
            "entity": entity,
            "path": source["path"],
            "source_url": source["source_url"],
            "media_type": source["media_type"],
            "http_status": source["http_status"],
            "bytes": source["bytes"],
            "sha256": source["sha256"],
            "figure_c14n_sha256": source["figure_c14n_sha256"],
        }
        if asset != expected:
            raise ValueError(f"profile and acquisition receipt differ for image entity {entity}")
        if len(raw) != expected["bytes"] or _sha(raw) != expected["sha256"]:
            raise ValueError(f"retained image authority differs for {entity}")
        if expected["media_type"] != "image/jpeg" or not raw.startswith(b"\xff\xd8\xff"):
            raise ValueError(f"retained image type/signature differs for {entity}")
        result.append(expected)
    return result

def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    receipt, profile, source, entities = _read(manifest)
    assets = _retained_image_assets(manifest, receipt, profile)
    stylesheet = manifest.authority_path("p4-to-p5-stylesheet").read_bytes()
    output = _migrate(source, stylesheet, entities, receipt["source_url"])
    content = __import__("lxml.etree", fromlist=["etree"]).tostring(
        output, encoding="UTF-8", xml_declaration=True, pretty_print=True
    )
    policy = json.loads(manifest.authority_path("policy").read_bytes())
    account = {
        "contract": "ocd-docsouth-single-work-accountability-v2",
        "source_id": receipt["source_id"],
        "work_id": manifest.record["work_id"],
        "source_sha256": receipt["member"]["sha256"],
        "profile_sha256": _sha(manifest.authority_path("profile").read_bytes()),
        "source_envelope": profile["envelope"],
        "page_markers": profile["page_markers"],
        "image_entities": profile["image_entities"],
        "retained_image_assets": assets,
        "tei_sha256": _sha(content),
        "tei_bytes": len(content),
    }
    return {
        "README.source.md": manifest.authority_path("readme").read_bytes(),
        "content.tei.xml": content,
        "provenance.json": _json(policy["provenance"]),
        "source-accountability.json": _json(account),
        "unresolved.jsonl": b"".join(_json(item) for item in policy["unresolved"]),
    }
_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
