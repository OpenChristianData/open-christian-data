"""Tests for the scans_manifest schema + the committed SH manifest."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

try:
    import jsonschema  # type: ignore
except ImportError:  # pragma: no cover
    jsonschema = None  # type: ignore

REPO_ROOT = Path(__file__).resolve().parents[1]
SH_MANIFEST = REPO_ROOT / "sources" / "schaff-herzog-encyclopedia" / "scans_manifest.json"
SCHEMA = REPO_ROOT / "schemas" / "v1" / "scans_manifest.schema.json"


pytestmark = pytest.mark.skipif(jsonschema is None, reason="jsonschema not installed")


def _manifest_checksum(body: dict) -> str:
    body = dict(body)
    body["manifest_checksum_sha256"] = None
    payload = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_sh_scans_manifest_validates_against_schema() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    body = json.loads(SH_MANIFEST.read_text(encoding="utf-8"))

    jsonschema.validate(body, schema)


def test_sh_scans_manifest_checksum_matches_body() -> None:
    body = json.loads(SH_MANIFEST.read_text(encoding="utf-8"))
    stored = body["manifest_checksum_sha256"]
    assert isinstance(stored, str)
    assert re.fullmatch(r"^[0-9a-f]{64}$", stored)

    expected = _manifest_checksum(body)

    assert stored == expected


def test_sh_scans_manifest_has_at_least_five_scans() -> None:
    body = json.loads(SH_MANIFEST.read_text(encoding="utf-8"))
    assert len(body["scans"]) >= 5


def test_sh_scans_manifest_uses_external_url_image_storage() -> None:
    body = json.loads(SH_MANIFEST.read_text(encoding="utf-8"))
    for scan in body["scans"]:
        assert scan["image_storage"] == "external_url"
        assert scan["provider"] == "Internet Archive"
