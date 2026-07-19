"""Contract tests for complete, fail-closed Phase 1B IR ownership."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cvw_phase1b import generate_catalog_accounting
from cvw_phase1b.ir_accounting import (
    IrAccountingError,
    generate_ir_accounting,
    serialize_ir_accounting,
)
from tests.test_cvw_phase1b_catalog_accounting import _json_bytes, _write, accounting_repo


REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_CATALOG_REGISTRY = REPO_ROOT / "cvw_phase1b/fixtures/catalog_accounting.json"
LIVE_IR_REGISTRY = REPO_ROOT / "cvw_phase1b/fixtures/ir_accounting.json"


def _paths_hash(paths: list[str]) -> str:
    data = (
        json.dumps(paths, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def ir_repo(accounting_repo: tuple[Path, Path]) -> tuple[Path, Path, dict[str, object]]:
    root, catalog_registry = accounting_repo
    _write(root / "cvw_phase1b/ir_accounting.py", (REPO_ROOT / "cvw_phase1b/ir_accounting.py").read_bytes())
    paths = [
        "ir/asv/asv.synthetic.census.json",
        "ir/asv/asv.synthetic.tei.xml",
    ]
    _write(root / paths[0], b'{"identity":"synthetic-census"}\n')
    _write(root / paths[1], b"<TEI/>\n")
    registry = root / "cvw_phase1b/fixtures/ir_accounting.json"
    _write(
        registry,
        _json_bytes(
            {
                "identity": "verification-ir-accounting-v1",
                "ir_root": "ir",
                "renderings": [
                    {
                        "work_id": "asv",
                        "rendering_id": "synthetic",
                        "artifact_name_prefix": "asv.synthetic",
                        "expected_artifact_count": 2,
                        "expected_paths_sha256": _paths_hash(paths),
                    }
                ],
            }
        ),
    )
    catalog_report = generate_catalog_accounting(root, catalog_registry)
    return root, registry, catalog_report


def test_ir_accounting_owns_every_artifact_at_rendering_grain(
    ir_repo: tuple[Path, Path, dict[str, object]],
) -> None:
    root, registry, catalog_report = ir_repo

    report = generate_ir_accounting(root, registry, catalog_report)

    assert report["counts"] == {
        "artifacts_owned": 2,
        "renderings_owned": 1,
        "work_units_with_ir": 1,
    }
    assert report["phase1b_ir_exit"] == {"reasons": [], "state": "READY"}
    assert [item["path"] for item in report["renderings"][0]["artifacts"]] == [
        "ir/asv/asv.synthetic.census.json",
        "ir/asv/asv.synthetic.tei.xml",
    ]
    assert serialize_ir_accounting(report) == serialize_ir_accounting(
        generate_ir_accounting(root, registry, catalog_report)
    )


@pytest.mark.parametrize("defect", ["orphan", "missing", "path-set", "unknown-work"])
def test_ir_ownership_defects_fail_closed(
    ir_repo: tuple[Path, Path, dict[str, object]], defect: str
) -> None:
    root, registry, catalog_report = ir_repo
    if defect == "orphan":
        _write(root / "ir/orphan.bin", b"orphan\n")
    elif defect == "missing":
        (root / "ir/asv/asv.synthetic.tei.xml").unlink()
    else:
        payload = json.loads(registry.read_bytes())
        if defect == "path-set":
            payload["renderings"][0]["expected_paths_sha256"] = "0" * 64
        else:
            payload["renderings"][0]["work_id"] = "not-in-catalog"
        registry.write_bytes(_json_bytes(payload))

    with pytest.raises(IrAccountingError, match="no owner|count drifted|path set drifted|outside"):
        generate_ir_accounting(root, registry, catalog_report)


def test_overlapping_ir_prefixes_fail_closed(
    ir_repo: tuple[Path, Path, dict[str, object]],
) -> None:
    root, registry, catalog_report = ir_repo
    payload = json.loads(registry.read_bytes())
    duplicate = payload["renderings"][0].copy()
    duplicate["rendering_id"] = "overlap"
    duplicate["artifact_name_prefix"] = "asv."
    payload["renderings"].append(duplicate)
    registry.write_bytes(_json_bytes(payload))

    with pytest.raises(IrAccountingError, match="multiple owners"):
        generate_ir_accounting(root, registry, catalog_report)


def test_live_ir_accounting_owns_all_75_artifacts_and_15_renderings() -> None:
    catalog_report = generate_catalog_accounting(REPO_ROOT, LIVE_CATALOG_REGISTRY)

    report = generate_ir_accounting(REPO_ROOT, LIVE_IR_REGISTRY, catalog_report)

    assert report["counts"] == {
        "artifacts_owned": 75,
        "renderings_owned": 15,
        "work_units_with_ir": 14,
    }
