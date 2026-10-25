"""Source-bound candidate producer for the retained 1559 BCP HTML expression."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
from typing import Mapping

from build.tei.bcp_source import load_bcp_edition
from build.tei.bcp_to_tei import convert_bcp_to_tei
from build.tei.census import census_bcp_liturgy
from ocd_kernel.reconstruction.contract import SourceManifest
from ocd_kernel.lib.storage_topology import resolve_repo_path


CONVERTER_ID = "ocd-bcp-1559-retained-html-to-tei"
CONVERTER_VERSION = "1"


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json_bytes(value: object) -> bytes:
    return _canonical(value)


def _primary_authorities(source_manifest: SourceManifest) -> list[Mapping[str, object]]:
    authorities = source_manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("BCP 1559 source authorities are invalid")
    return [item for item in authorities if item.get("role") == "primary-source"]


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    repository_root = source_manifest.repository_root
    raw_root = resolve_repo_path(repository_root, "raw").resolve(strict=True)
    profile = json.loads(source_manifest.authority_path("bcp1559-profile").read_bytes())
    bundle = profile["source_bundle"]
    source_bundle = source_manifest.record.get("source_bundle")
    if source_bundle != bundle:
        raise ValueError("BCP 1559 source bundle does not match its profile")

    edition = load_bcp_edition("bcp-1559", raw_root)
    expected_paths = {f"raw/{path.relative_to(raw_root).as_posix()}" for path in edition.files}
    primary = _primary_authorities(source_manifest)
    observed_paths = {str(item["path"]) for item in primary}
    for authority in primary:
        resolved = source_manifest.authority_path(str(authority["name"])).resolve(strict=True)
        resolved.relative_to(raw_root)
    if observed_paths != expected_paths or len(primary) != 16:
        raise ValueError("BCP 1559 source manifest does not bind the route envelope")

    with tempfile.TemporaryDirectory(prefix="ocd-bcp1559-route-") as temporary:
        tei_path = Path(temporary) / "content.tei.xml"
        convert_bcp_to_tei("bcp-1559", tei_path, raw_root=raw_root)
        tei_bytes = tei_path.read_bytes()

    census = census_bcp_liturgy("bcp-1559", raw_root)
    features = dict(census["features"])
    features["paragraphs"] = {
        "count": sum(event.feature == "paragraphs" for event in edition.events),
        "ids": [event.xml_id for event in edition.events if event.feature == "paragraphs"],
    }
    expected_features = profile["expected_features"]
    if any(features[name]["count"] != expected_features[name] for name in expected_features):
        raise ValueError("BCP 1559 source feature census does not match its profile")

    source_members = [
        {
            "name": str(item["name"]),
            "path": str(item["path"]),
            "bytes": int(item["bytes"]),
            "sha256": str(item["sha256"]),
        }
        for item in sorted(primary, key=lambda value: str(value["path"]))
    ]
    accountability = {
        "contract": "ocd-bcp-1559-source-accountability-v1",
        "source_id": str(source_manifest.record["source_id"]),
        "source_members": source_members,
        "features": features,
        "tei": {"bytes": len(tei_bytes), "sha256": _sha(tei_bytes)},
        "route": "build/tei/bcp_to_tei.py",
        "ocr": "not-used",
    }
    provenance = {
        "contract": "ocd-provenance-v1",
        "source_id": str(source_manifest.record["source_id"]),
        "source_url": "http://justus.anglican.org/resources/bcp/1559/",
        "source_edition": "Transcription by Rev. Richard J. Mammana Jr. at justus.anglican.org",
        "source_format": "HTML",
        "license": "public-domain",
        "source_manifest_sha256": source_manifest.sha256,
        "ocr": "not-used",
    }
    unresolved = [
        {"gate": gate, "status": "open"}
        for gate in (
            "canonical-source-manifest-admission",
            "producer-independent-mutation-rejection",
            "cvw-visual-review",
            "metadata-adoption",
            "human-acceptance",
            "rights-clearance",
            "ir-durable-admission",
            "publication",
        )
    ]
    readme = """# BCP 1559 source note

This non-OCR candidate is reconstructed from the retained 16-member HTML
expression under `raw/bcp-full-text/bcp-1559`, transcribed by Rev. Richard J.
Mammana Jr. at justus.anglican.org. The source is public domain. The retained
source remains authoritative; no OCR-derived text was used. Technical
validation does not establish human acceptance, rights clearance, or
publication authorization.
""".encode("utf-8")
    return {
        "content.tei.xml": tei_bytes,
        "source-accountability.json": _json_bytes(accountability),
        "provenance.json": _json_bytes(provenance),
        "unresolved.jsonl": b"".join(_json_bytes(item) for item in unresolved),
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
