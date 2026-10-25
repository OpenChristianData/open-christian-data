"""Preserve the complete First1KGreek Methodius TEI member unchanged."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from ocd_kernel.reconstruction import SourceManifest


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    source = manifest.authority_path("retained-tei").read_bytes()
    profile = json.loads(manifest.authority_path("profile").read_text(encoding="utf-8"))
    policy = json.loads(manifest.authority_path("policy").read_text(encoding="utf-8"))
    source_sha = hashlib.sha256(source).hexdigest()
    if source_sha != profile["source_sha256"] or len(source) != profile["source_bytes"]:
        raise ValueError("Methodius source bytes drifted")
    accountability = {
        "contract": "ocd-methodius-first1kgreek-source-accountability-v1",
        "source_sha256": source_sha,
        "source_bytes": len(source),
        "candidate_sha256": source_sha,
        "candidate_bytes": len(source),
        "member_inventory": profile["member_inventory"],
        "mapping": "The complete official TEI member is preserved byte for byte; no source transformation or exclusion.",
    }
    return {
        "README.source.md": manifest.authority_path("readme").read_bytes(),
        "content.tei.xml": source,
        "source-accountability.json": _json(accountability),
        "provenance.json": _json(policy["provenance"]),
        "unresolved.jsonl": b"".join(_json(item) for item in policy["unresolved"]),
    }


_convert.converter_id = "ocd-methodius-first1kgreek-byte-conservation"
_convert.converter_version = "1"
_convert.implementation_path = Path(__file__).resolve()
