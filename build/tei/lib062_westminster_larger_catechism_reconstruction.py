"""Produce the standard nonaccepted candidate for LIB-062 Westminster Larger."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from ocd_kernel.reconstruction import SourceManifest

import build.tei.lib062_json_catechisms_reconstruction as family


CONVERTER_ID = "ocd-lib062-westminster-larger-catechism-to-tei"
CONVERTER_VERSION = "1"
WORK_ID = "westminster-larger-catechism"


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _unresolved(source_path: str, source_sha: str) -> bytes:
    rows = [
        {
            "category": "metadata",
            "status": "open",
            "claim": "Primary-source edition, translation, and authorship allocation remain human-review questions.",
            "source_path": source_path,
            "source_sha256": source_sha,
        },
        {
            "category": "rights",
            "status": "open",
            "claim": "The retained provider statements are evidence only; rights clearance is not claimed.",
            "source_path": source_path,
            "source_sha256": source_sha,
        },
        {
            "category": "review",
            "status": "open",
            "claim": "Human acceptance, accepted IR, promotion, and publication remain unperformed and unauthorized.",
            "source_path": source_path,
            "source_sha256": source_sha,
        },
    ]
    return b"".join(_canonical(row) for row in rows)


def convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    """Adapt the existing LIB-062 reconstruction to the standard package shape."""

    if source_manifest.record.get("work_id") != WORK_ID:
        raise ValueError("LIB-062 Westminster source manifest work identity drifted")
    root = source_manifest.repository_root
    _, census_bytes, census_indexes = family._retained_member_census(root)
    packet, source, source_bytes = family._source_and_packet(
        root, WORK_ID, census_indexes
    )
    family._assert_model(packet, source, WORK_ID)
    tei_bytes, accounting = family._build_tei(WORK_ID, packet, source)
    source_path = str(packet["authority"]["path"])
    source_sha = family._sha(source_bytes)
    normalized_sha = family._sha(family._normalized_utf8(source_bytes))
    metadata = source["Metadata"]
    assert isinstance(metadata, dict)
    provenance = {
        "contract": "ocd-lib062-westminster-larger-catechism-provenance-v1",
        "work_id": WORK_ID,
        "retained_source": {
            "path": source_path,
            "bytes": len(source_bytes),
            "sha256": source_sha,
            "normalized_utf8_sha256": normalized_sha,
        },
        "retained_metadata": metadata,
        "rights": {
            "evidence_path": "raw/Creeds.json/README.md",
            "provider_statement": "Unlicense claim retained in source packet; worldwide clearance is not claimed",
            "human_review": "required",
        },
        "status": {
            "candidate": "nonaccepted",
            "human_review": "required",
            "accepted_ir": "not_accepted",
            "publication": "not_ready",
        },
        "authority_boundary": (
            "Retained Creeds.json bytes and the LIB-062 packet are authority. "
            "The legacy data JSON is a catalog claim only and was not read by the converter."
        ),
    }
    return {
        "README.source.md": (root / "sources/westminster-larger-catechism/LIB-062.README.md").read_bytes(),
        "content.tei.xml": tei_bytes,
        "provenance.json": _canonical(provenance),
        "source-accountability.json": _canonical(accounting),
        "unresolved.jsonl": _unresolved(source_path, source_sha),
    }


convert.converter_id = CONVERTER_ID
convert.converter_version = CONVERTER_VERSION


__all__ = ("CONVERTER_ID", "CONVERTER_VERSION", "WORK_ID", "convert")
