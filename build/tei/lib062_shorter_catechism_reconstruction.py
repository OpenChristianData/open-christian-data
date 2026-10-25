"""Ticket-local candidate envelope for the retained shorter catechism JSON."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from build.tei import lib062_json_catechisms_reconstruction as family
from ocd_kernel.reconstruction.contract import SourceManifest


WORK_ID = "shorter-catechism-explained"
SOURCE_ID = "creeds-json-lib062-shorter-catechism-explained-retained-json"
CONVERTER_ID = "ocd-creeds-json-lib062-shorter-catechism-explained-to-tei"
CONVERTER_VERSION = "1"


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _primary(source_manifest: SourceManifest) -> Mapping[str, object]:
    authorities = source_manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("shorter catechism source authorities are invalid")
    primary = [item for item in authorities if item.get("role") == "primary-source"]
    if len(primary) != 1:
        raise ValueError("shorter catechism route requires exactly one primary source")
    return primary[0]


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    if source_manifest.record.get("source_id") != SOURCE_ID:
        raise ValueError("shorter catechism source identity drift")
    if source_manifest.record.get("work_id") != WORK_ID:
        raise ValueError("shorter catechism work identity drift")

    root = source_manifest.repository_root
    profile = json.loads(
        source_manifest.authority_path(
            "reconstruction-profile"
        ).read_bytes()
    )
    primary = _primary(source_manifest)
    expected_source = profile["source"]
    if (
        primary.get("path") != expected_source["path"]
        or primary.get("bytes") != expected_source["raw_bytes"]
        or primary.get("sha256") != expected_source["raw_sha256"]
    ):
        raise ValueError("shorter catechism primary source does not match profile")

    _, _, census_indexes = family._retained_member_census(root)
    packet, source, source_bytes = family._source_and_packet(
        root, WORK_ID, census_indexes
    )
    if not family._json_equal(
        packet["profile"], profile["profile"]
    ) or not family._json_equal(packet["structural_policy"], profile["structural_policy"]):
        raise ValueError("shorter catechism packet/profile binding drift")
    if _sha(source_bytes) != expected_source["raw_sha256"]:
        raise ValueError("shorter catechism source bytes drift")

    family._assert_model(packet, source, WORK_ID)
    tei_bytes, accounting = family._build_tei(WORK_ID, packet, source)
    schema = family._schema(root)
    from lxml import etree

    if not schema.validate(etree.ElementTree(etree.fromstring(tei_bytes))):
        raise ValueError(f"shorter catechism TEI P5 failure: {schema.error_log.last_error}")

    source_member = {
        "name": str(primary["name"]),
        "path": str(primary["path"]),
        "bytes": int(primary["bytes"]),
        "sha256": str(primary["sha256"]),
        "normalized_utf8_bytes": int(expected_source["normalized_utf8_bytes"]),
        "normalized_utf8_sha256": str(expected_source["normalized_utf8_sha256"]),
    }
    accountability = {
        "contract": "ocd-lib062-shorter-catechism-explained-source-accountability-v1",
        "source_id": SOURCE_ID,
        "work_id": WORK_ID,
        "source_member": source_member,
        "packet": {
            "path": "sources/shorter-catechism-explained/LIB-062.packet.json",
            "bytes": len(source_manifest.authority_path("source-packet").read_bytes()),
            "sha256": _sha(source_manifest.authority_path("source-packet").read_bytes()),
        },
        "profile": profile["profile"],
        "structural_policy": profile["structural_policy"],
        "top_level_keys": accounting["top_level_keys"],
        "recursive_key_counts": accounting["recursive_key_counts"],
        "data_record_count": accounting["data_record_count"],
        "represented_leaf_count": accounting["represented_leaf_count"],
        "omitted_leaf_count": accounting["omitted_leaf_count"],
        "duplicate_leaf_count": accounting["duplicate_leaf_count"],
        "crosswalk": accounting["crosswalk"],
        "tei": {"bytes": len(tei_bytes), "sha256": _sha(tei_bytes)},
        "route": "build/tei/lib062_json_catechisms_reconstruction.py",
        "ocr": "not-used",
    }
    provenance = {
        "contract": "ocd-provenance-v1",
        "source_id": SOURCE_ID,
        "work_id": WORK_ID,
        "source_manifest_sha256": source_manifest.sha256,
        "source": source_member,
        "source_url": str(source["Metadata"]["SourceUrl"]),
        "source_edition": "Creeds.json retained JSON member; source metadata Year 1765",
        "source_format": "JSON",
        "source_attribution": str(source["Metadata"]["SourceAttribution"]),
        "ocr": "not-used",
        "producer_envelope": "build/tei/lib062_shorter_catechism_reconstruction.py",
        "shared_route": "build/tei/lib062_json_catechisms_reconstruction.py",
    }
    unresolved = [
        {"gate": gate, "status": "open"}
        for gate in (
            "cvw-visual-review",
            "metadata-adoption",
            "human-acceptance",
            "rights-clearance",
            "ir-durable-admission",
            "publication",
        )
    ]
    readme = (
        "# The Assembly's Shorter Catechism Explained\n\n"
        "This non-OCR candidate is reconstructed from the retained JSON member "
        "`raw/Creeds.json/creeds/shorter_catechism_explained.json`. The 107 parent "
        "records and 3,831 nested subquestions remain in source order, including "
        "explicit empty arrays. The retained source is authoritative; no OCR-derived "
        "text is used. Technical validation does not establish human acceptance, "
        "rights clearance, or publication authorization.\n"
    ).encode("utf-8")
    return {
        "content.tei.xml": tei_bytes,
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
