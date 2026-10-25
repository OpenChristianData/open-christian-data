"""Produce one source-bound LIB062 candidate from six retained catechisms."""

from __future__ import annotations

import json
from typing import Mapping

from ocd_kernel.reconstruction import SourceManifest

import build.tei.lib062_json_catechisms_reconstruction as family


CONVERTER_ID = "ocd-lib062-six-catechisms-to-tei"
CONVERTER_VERSION = "1"
WORK_IDS = frozenset({
    "1695-baptist-catechism", "exposition-of-the-assemblies-catechism",
    "heidelberg-catechism", "keachs-catechism",
    "matthew-henrys-scripture-catechism", "puritan-catechism",
})


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _unresolved(source_path: str, source_sha: str) -> bytes:
    rows = [
        {"category": "metadata", "status": "open",
         "claim": "Primary-source edition, translation, and authorship allocation remain human-review questions.",
         "source_path": source_path, "source_sha256": source_sha},
        {"category": "rights", "status": "open",
         "claim": "The retained provider statements are evidence only; rights clearance is not claimed.",
         "source_path": source_path, "source_sha256": source_sha},
        {"category": "review", "status": "open",
         "claim": "Human acceptance, accepted IR, promotion, and publication remain unperformed and unauthorized.",
         "source_path": source_path, "source_sha256": source_sha},
    ]
    return b"".join(_canonical(row) for row in rows)


def convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    work_id = source_manifest.record.get("work_id")
    if work_id not in WORK_IDS:
        raise ValueError(f"LIB062 six-work converter is outside its exact work set: {work_id}")
    root = source_manifest.repository_root
    _, _, census_indexes = family._retained_member_census(root)
    packet, source, source_bytes = family._source_and_packet(root, work_id, census_indexes)
    family._assert_model(packet, source, work_id)
    tei_bytes, accounting = family._build_tei(work_id, packet, source)
    source_path = str(packet["authority"]["path"])
    source_sha = family._sha(source_bytes)
    provenance = {
        "contract": "ocd-lib062-six-catechisms-provenance-v1",
        "work_id": work_id,
        "retained_source": {
            "path": source_path, "bytes": len(source_bytes), "sha256": source_sha,
            "normalized_utf8_sha256": family._sha(family._normalized_utf8(source_bytes)),
        },
        "retained_metadata": source["Metadata"],
        "rights": {
            "evidence_path": "raw/Creeds.json/README.md",
            "provider_statement": "Unlicense claim retained in source packet; worldwide clearance is not claimed",
            "human_review": "required",
        },
        "status": {"candidate": "nonaccepted", "human_review": "required",
                   "accepted_ir": "not_accepted", "publication": "not_ready"},
        "authority_boundary": (
            "Retained Creeds.json bytes and the LIB-062 packet are authority. "
            "Legacy data JSON is a catalog claim only and was not read by the converter."
        ),
    }
    return {
        "README.source.md": (root / "sources" / work_id / "LIB-062.README.md").read_bytes(),
        "content.tei.xml": tei_bytes,
        "provenance.json": _canonical(provenance),
        "source-accountability.json": _canonical(accounting),
        "unresolved.jsonl": _unresolved(source_path, source_sha),
    }


convert.converter_id = CONVERTER_ID
convert.converter_version = CONVERTER_VERSION
