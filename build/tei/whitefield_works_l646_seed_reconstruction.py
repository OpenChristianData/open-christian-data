"""Repackage the preserved L646 three-volume TEI seed under current source bindings.

This route does not claim to recreate the historical converter. The preserved
TEI is copied byte-for-byte and checked independently against retained HTML.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, reconstruct

CONVERTER_ID = "ocd-whitefield-l646-preserved-seed-repackager"
SEED_HASH = "a51808a840f0975e7ddba24d1f0bfe4660e0395b0cd3e251fda14ab896dbc9f6"

def _canonical(obj: object) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()

def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    seed = manifest.authority_path("preserved-candidate-tei").read_bytes()
    if hashlib.sha256(seed).hexdigest() != SEED_HASH:
        raise ValueError("preserved candidate TEI seed drifted")
    src = [a for a in manifest.record["authorities"] if a["role"] == "primary-source"]
    accountability = {"contract":"ocd-whitefield-l646-source-accountability-v1", "scope":"PG 68976, 71140, 73012; volumes I-III only", "work_id":"george-whitefield-works", "seed_tei_sha256":SEED_HASH, "sources":[dict(name=a["name"],path=a["path"],bytes=a["bytes"],sha256=a["sha256"]) for a in src]}
    provenance = {"candidate_status":"nonaccepted", "work_id":"george-whitefield-works", "title":"The Works of the Reverend George Whitefield, M.A., volumes I-III", "human_acceptance":"not recorded", "rights":"not cleared", "publication":"not authorized", "conversion_basis":"preserved existing TEI seed; historical producer unavailable; current independent source check required"}
    unresolved = [
        {"id":"editor-attribution","status":"open","question":"Worklist says ed. John Gillies; examined title pages do not establish this attribution."},
        {"id":"human-review","status":"open","question":"Visual/editorial human review remains outstanding."},
        {"id":"rights-clearance","status":"open","question":"No rights clearance or jurisdictional determination is made."},
        {"id":"media-rendering","status":"open","question":"Retained illustration bytes are accounted for; candidate references do not prove viewer rendering."},
    ]
    return {"content.tei.xml":seed,"source-accountability.json":_canonical(accountability),"provenance.json":_canonical(provenance),"unresolved.jsonl":b"".join(_canonical(x) for x in unresolved),"README.source.md":manifest.authority_path("source-readme").read_bytes()}
_convert.converter_id=CONVERTER_ID
_convert.converter_version="1"

def build_candidate(manifest: SourceManifest, output: str | Path) -> CandidatePackage:
    return reconstruct(manifest, output, _convert)
