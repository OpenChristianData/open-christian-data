from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.edition_page_key import body_edition_key  # noqa: E402

SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"
EMPTY_EXTRAS_SHA256 = (
    "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
)
ZERO_SHA256 = "sha256:" + "0" * 64
TOKEN_ID = "ot-sha256:" + "1" * 64


def _schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def _accepts(schema: dict, instance: dict) -> None:
    jsonschema.validate(instance=instance, schema=schema)


def _rejects(schema: dict, instance: dict) -> None:
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=instance, schema=schema)


def _valid_manifest() -> dict:
    return {
        "schema_version": "sidecar-manifest-v1",
        "manifest_id": "sm-test",
        "work_id": "schaff-herzog-encyclopedia",
        "edition_id": "1908-1914",
        "volume": 1,
        "rendering_id": "ia-abbyy/schaff/encyclopedia/1908-1914/v1",
        "engine_family": "abbyy",
        "engine_version": "ABBYY FineReader",
        "source_lineage_id": "ia-abbyy-v1",
        "source_files": [
            {
                "path": "data/reference/schaff/encyclopedia/1908-1914/ia-abbyy-v1/vol_01.json",
                "sha256": ZERO_SHA256,
            }
        ],
        "pages": [
            {
                "page_native_id": "1",
                "page_sequence": 1,
                "status": "eligible",
                "sidecar_page_path": "reports/s1-sidecars/ia-abbyy-v1/vol_01/pages/page_0001.json",
                "source_payload_sha256": ZERO_SHA256,
                "canonical_leaf_id": 1,
                "edition_page_key": body_edition_key(1),
            }
        ],
        "manifest_cross_check": {
            "samples_checked": 1,
            "samples_matched": 1,
            "samples_inconclusive": 0,
            "failed_samples": [],
        },
        "bundle_extras_carried": {},
        "bundle_extras_carried_keys": [],
        "bundle_extras_jcs_sha256": EMPTY_EXTRAS_SHA256,
        "created_at": "2026-05-29T00:00:00Z",
    }


def _valid_page() -> dict:
    return {
        "schema_version": "sidecar-page-v1",
        "manifest_id": "sm-test",
        "rendering_id": "ia-abbyy/schaff/encyclopedia/1908-1914/v1",
        "page_native_id": "1",
        "canonical_leaf_id": 1,
        "page_sequence": 1,
        "page_dimensions_native": {"width": None, "height": None, "unit": "unknown"},
        "blocks": [
            {
                "block_id": "block-0001",
                "block_type": "text",
                "lines": [
                    {
                        "observation_token_id": TOKEN_ID,
                        "line_native_id": "line-0001",
                        "source_raw": "Grace and peace",
                        "confidence": None,
                        "bbox_native": None,
                        "words": [
                            {
                                "observation_token_id": "ot-sha256:" + "2" * 64,
                                "word_native_id": "word-0001",
                                "source_raw": "Grace",
                                "confidence": None,
                                "bbox_native": None,
                            }
                        ],
                    }
                ],
                "bbox_native": None,
            }
        ],
        "parsed_keys_index": [
            {
                "key": "text",
                "handling": "extras_carried",
                "source_path": "pages[].text",
            }
        ],
        "page_extras_carried": {},
        "page_extras_carried_keys": [],
        "page_extras_jcs_sha256": EMPTY_EXTRAS_SHA256,
        "source_payload_sha256": ZERO_SHA256,
        "edition_page_key": body_edition_key(1),
    }


def test_sidecar_manifest_schema_accepts_valid_rejects_unknown_engine_family() -> None:
    schema = _schema("sidecar-manifest-v1")
    _accepts(schema, _valid_manifest())

    broken = copy.deepcopy(_valid_manifest())
    broken["engine_family"] = "paddleocr"
    _rejects(schema, broken)


def test_sidecar_page_schema_conformance() -> None:
    schema = _schema("sidecar-page-v1")
    _accepts(schema, _valid_page())

    missing_required = copy.deepcopy(_valid_page())
    del missing_required["source_payload_sha256"]
    _rejects(schema, missing_required)


def test_enum_freshness() -> None:
    result = subprocess.run(
        [sys.executable, "build/tools/check_schema_enums_fresh.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
