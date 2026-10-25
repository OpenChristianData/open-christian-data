"""Single-work DocSouth TEI.2 to P5 reconstruction for exact L763 Green and L764 Gaines editions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from build.tei.docsouth_l761_l762 import _migrate, _read
from ocd_kernel.reconstruction.contract import SourceManifest

CONVERTER_ID = "ocd-docsouth-green-gaines-exact-v1-to-p5"
CONVERTER_VERSION = "1"

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()

def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    receipt, profile, source, entities = _read(manifest)
    stylesheet = manifest.authority_path("p4-to-p5-stylesheet").read_bytes()
    from build.tei.docsouth_l761_l762 import _migrate
    output = _migrate(source, stylesheet, entities, receipt["source_url"])
    content = __import__("lxml.etree", fromlist=["etree"]).tostring(output, encoding="UTF-8", xml_declaration=True, pretty_print=True)
    policy = json.loads(manifest.authority_path("policy").read_bytes())
    account = {
        "contract": "ocd-docsouth-single-work-accountability-v1",
        "source_id": receipt["source_id"], "work_id": manifest.record["work_id"],
        "source_sha256": receipt["member"]["sha256"], "profile_sha256": _sha(manifest.authority_path("profile").read_bytes()),
        "source_envelope": profile["envelope"], "page_markers": profile["page_markers"],
        "image_entities": profile["image_entities"], "tei_sha256": _sha(content), "tei_bytes": len(content),
    }
    return {"README.source.md": manifest.authority_path("readme").read_bytes(),
            "content.tei.xml": content, "provenance.json": _json(policy["provenance"]),
            "source-accountability.json": _json(account),
            "unresolved.jsonl": b"".join(_json(item) for item in policy["unresolved"])}

_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
