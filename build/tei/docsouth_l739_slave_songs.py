"""Source-bound P4-to-P5 reconstruction for DocSouth L739."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
from typing import Mapping
from lxml import etree
from ocd_kernel.reconstruction.contract import SourceManifest
from build.tei.docsouth_l761_l762 import _migrate

CONVERTER_ID = "ocd-docsouth-l739-slave-songs-tei2-to-p5"
CONVERTER_VERSION = "1"
T = "{http://www.tei-c.org/ns/1.0}"
X = "{http://www.w3.org/XML/1998/namespace}"
def _sha(b: bytes) -> str: return hashlib.sha256(b).hexdigest()
def _json(v: object) -> bytes: return (json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"))+"\n").encode()
def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    raw = manifest.authority_path("official-source-member").read_bytes()
    receipt = json.loads(manifest.authority_path("acquisition-receipt").read_bytes())
    profile = json.loads(manifest.authority_path("profile").read_bytes())
    policy = json.loads(manifest.authority_path("policy").read_bytes())
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    root = etree.fromstring(raw, parser)
    entities = {e.name:e.system_url for e in root.getroottree().docinfo.internalDTD.iterentities() if e.system_url and e.system_url.lower().endswith(".jpg")}
    if _sha(raw) != receipt["member"]["sha256"] or _sha(raw) != profile["source_sha256"] or entities != profile["image_entities"]:
        raise ValueError("L739 source identity or image entity inventory drifted")
    stylesheet = manifest.authority_path("p4-to-p5-stylesheet").read_bytes()
    out = _migrate(root, stylesheet, entities, receipt["source_url"])
    content = etree.tostring(out, encoding="UTF-8", xml_declaration=True, pretty_print=True)
    account = {"contract":"ocd-docsouth-single-work-accountability-v1", "source_id":receipt["source_id"], "work_id":manifest.record["work_id"], "source_sha256":_sha(raw), "source_envelope":profile["envelope"], "page_markers":profile["page_markers"], "image_entities":profile["image_entities"], "figure_entity_sequence":profile["figure_entity_sequence"], "declared_member_inventory":profile["declared_member_inventory"], "tei_sha256":_sha(content), "tei_bytes":len(content)}
    return {"README.source.md":manifest.authority_path("readme").read_bytes(), "content.tei.xml":content, "provenance.json":_json(policy["provenance"]), "source-accountability.json":_json(account), "unresolved.jsonl":b"".join(_json(x) for x in policy["unresolved"])}
_convert.converter_id=CONVERTER_ID; _convert.converter_version=CONVERTER_VERSION
_convert.implementation_path=Path(__file__).resolve()
