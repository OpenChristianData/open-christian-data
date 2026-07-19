"""Contract tests for hash-bound Phase 1B catalog accounting."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from build.tools.count_dataset_records import (
    collect_work_catalog,
    render_catalog_markdown,
    serialize_catalog_identity,
)
from cvw_phase1b.catalog_accounting import (
    CatalogAccountingError,
    assert_phase1b_catalog_exit,
    generate_catalog_accounting,
    serialize_catalog_accounting,
)
from tests.test_cvw_phase1b_inventory import (
    _copy_parser_dependency_closure,
    _descriptor,
    _json_bytes,
    _write,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_REGISTRY = REPO_ROOT / "cvw_phase1b/fixtures/catalog_accounting.json"


def _registry(
    catalog_bytes: bytes,
    identity_bytes: bytes,
    owners: list[dict[str, str]],
) -> dict[str, object]:
    return {
        "identity": "verification-catalog-accounting-v1",
        "catalog": {
            "path": "docs/WORK_CATALOG.md",
            "raw_sha256": hashlib.sha256(catalog_bytes).hexdigest(),
            "identity_path": "cvw_phase1a/fixtures/work_catalog_identity.json",
            "identity_raw_sha256": hashlib.sha256(identity_bytes).hexdigest(),
        },
        "ownership_descriptors": owners,
    }


def _render_catalog(root: Path) -> bytes:
    return render_catalog_markdown(collect_work_catalog(root / "data")).encode("utf-8")


def _render_catalog_identity(root: Path) -> bytes:
    return serialize_catalog_identity(collect_work_catalog(root / "data"))


@pytest.fixture
def accounting_repo(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "catalog-accounting-repository"
    source = {
        "translation": "ASV: American Standard Version (1901)",
        "books": [
            {
                "name": "Genesis",
                "chapters": [
                    {
                        "chapter": 1,
                        "verses": [{"verse": 1, "text": "In the beginning"}],
                    }
                ],
            },
            {
                "name": "Exodus",
                "chapters": [
                    {
                        "chapter": 1,
                        "verses": [{"verse": 1, "text": "Now these are"}],
                    }
                ],
            },
        ],
    }
    source_bytes = _json_bytes(source)
    _write(root / "raw/bible_databases/formats/json/ASV.json", source_bytes)
    _write(
        root / "sources/bible-text/asv/config.json",
        _json_bytes(
            {
                "resource_id": "asv",
                "source_file": "raw/bible_databases/formats/json/ASV.json",
            }
        ),
    )
    for member_id, book in (("genesis", "Genesis"), ("exodus", "Exodus")):
        _write(
            root / f"data/bible-text/asv/{member_id}.json",
            _json_bytes(
                {
                    "meta": {
                        "id": "asv",
                        "title": "American Standard Version",
                        "schema_type": "bible_text",
                        "scope": {"book": book},
                    },
                    "data": [],
                }
            ),
        )
    _write(
        root / "data/structured-text/unowned-work.json",
        _json_bytes(
            {
                "meta": {
                    "id": "unowned-work",
                    "title": "Unowned Work",
                    "author": "Unknown Author",
                    "schema_type": "structured_text",
                },
                "data": {"sections": []},
            }
        ),
    )
    catalog_bytes = _render_catalog(root)
    identity_bytes = _render_catalog_identity(root)
    _write(root / "docs/WORK_CATALOG.md", catalog_bytes)
    _write(root / "cvw_phase1a/fixtures/work_catalog_identity.json", identity_bytes)
    for dependency in (
        "cvw_phase1b/catalog_accounting.py",
        "cvw_phase1b/inventory.py",
        "cvw_phase1b/ownership.py",
        "build/parsers/bible_text_translations.py",
        "build/tools/count_dataset_records.py",
    ):
        _write(root / dependency, (REPO_ROOT / dependency).read_bytes())
    _copy_parser_dependency_closure(root, "build/parsers/bible_text_translations.py")
    _write(
        root / "schemas/v1/verification_inventory.schema.json",
        (REPO_ROOT / "schemas/v1/verification_inventory.schema.json").read_bytes(),
    )
    ownership = root / "cvw_phase1b/fixtures/asv_ownership.json"
    descriptor = _descriptor(hashlib.sha256(source_bytes).hexdigest())
    descriptor["catalog"]["path"] = "docs/WORK_CATALOG.md"
    _write(ownership, _json_bytes(descriptor))
    registry = root / "cvw_phase1b/fixtures/catalog_accounting.json"
    _write(
        registry,
        _json_bytes(
            _registry(
                catalog_bytes,
                identity_bytes,
                [
                    {
                        "category": "Bible Translations",
                        "title": "American Standard Version",
                        "author": "",
                        "path": "cvw_phase1b/fixtures/asv_ownership.json",
                    }
                ],
            )
        ),
    )
    return root, registry


def test_accounting_report_exposes_reconstruction_depth_without_losing_ownership(
    accounting_repo: tuple[Path, Path],
) -> None:
    root, registry = accounting_repo

    report = generate_catalog_accounting(root, registry)

    assert report["catalog_snapshot"]["work_units"] == 2
    assert report["canonical_data"] == {"artifacts_owned": 3, "work_units_owned": 2}
    assert report["counts"] == {
        "total": 2,
        "reconstruction_authenticated": 1,
        "reconstruction_referenced_only": 1,
        "reconstruction_unavailable": 0,
    }
    assert [work["reconstruction_adapter"]["state"] for work in report["works"]] == [
        "authenticated",
        "referenced_only",
    ]
    assert report["phase1b_exit"] == {"reasons": [], "state": "READY"}
    assert_phase1b_catalog_exit(report)


def test_complete_accounting_is_ready_and_deterministic(
    accounting_repo: tuple[Path, Path],
) -> None:
    root, registry = accounting_repo
    (root / "data/structured-text/unowned-work.json").unlink()
    catalog = root / "docs/WORK_CATALOG.md"
    catalog_bytes = _render_catalog(root)
    identity_bytes = _render_catalog_identity(root)
    catalog.write_bytes(catalog_bytes)
    (root / "cvw_phase1a/fixtures/work_catalog_identity.json").write_bytes(identity_bytes)
    payload = json.loads(registry.read_bytes())
    payload["catalog"]["raw_sha256"] = hashlib.sha256(catalog_bytes).hexdigest()
    payload["catalog"]["identity_raw_sha256"] = hashlib.sha256(identity_bytes).hexdigest()
    registry.write_bytes(_json_bytes(payload))

    report = generate_catalog_accounting(root, registry)

    assert report["phase1b_exit"] == {"reasons": [], "state": "READY"}
    assert_phase1b_catalog_exit(report)
    assert serialize_catalog_accounting(report) == serialize_catalog_accounting(
        generate_catalog_accounting(root, registry)
    )


def test_catalog_snapshot_drift_fails_closed(
    accounting_repo: tuple[Path, Path],
) -> None:
    root, registry = accounting_repo
    with (root / "docs/WORK_CATALOG.md").open("ab") as handle:
        handle.write(b"\n")

    with pytest.raises(CatalogAccountingError, match="snapshot hash"):
        generate_catalog_accounting(root, registry)


@pytest.mark.parametrize("defect", ["duplicate-owner", "unknown-row", "noncanonical-render"])
def test_ambiguous_or_unknown_catalog_ownership_fails_closed(
    accounting_repo: tuple[Path, Path], defect: str
) -> None:
    root, registry = accounting_repo
    payload = json.loads(registry.read_bytes())
    owner = payload["ownership_descriptors"][0]
    if defect == "duplicate-owner":
        payload["ownership_descriptors"].append(owner.copy())
        registry.write_bytes(_json_bytes(payload))
    elif defect == "unknown-row":
        owner["title"] = "Not In Catalog"
        registry.write_bytes(_json_bytes(payload))
    else:
        catalog = root / "docs/WORK_CATALOG.md"
        catalog_bytes = catalog.read_bytes().replace(b"Publication date", b"Year")
        catalog.write_bytes(catalog_bytes)
        payload["catalog"]["raw_sha256"] = hashlib.sha256(catalog_bytes).hexdigest()
        registry.write_bytes(_json_bytes(payload))
    with pytest.raises(CatalogAccountingError, match="duplicate|does not match|canonical render"):
        generate_catalog_accounting(root, registry)


def test_unavailable_owner_is_visible_and_blocks_exit(
    accounting_repo: tuple[Path, Path],
) -> None:
    root, registry = accounting_repo
    (root / "raw/bible_databases/formats/json/ASV.json").unlink()

    report = generate_catalog_accounting(root, registry)

    assert report["counts"]["reconstruction_unavailable"] == 1
    owner = report["works"][0]["reconstruction_adapter"]
    assert owner["state"] == "unavailable"
    assert "required raw source is missing" in owner["reason"]
    with pytest.raises(CatalogAccountingError, match="reconstruction_unavailable=1"):
        assert_phase1b_catalog_exit(report)


@pytest.mark.requires_local_artifacts
def test_live_catalog_accounting_binds_current_402_work_snapshot() -> None:
    report = generate_catalog_accounting(REPO_ROOT, LIVE_REGISTRY)

    assert report["catalog_snapshot"]["work_units"] == 402
    assert report["catalog_snapshot"]["raw_sha256"] == hashlib.sha256(
        (REPO_ROOT / "docs/WORK_CATALOG.md").read_bytes()
    ).hexdigest()
    authenticated = report["counts"]["reconstruction_authenticated"]
    assert authenticated in {1, 2}
    assert report["counts"]["reconstruction_unavailable"] == 2 - authenticated
    assert report["counts"]["reconstruction_referenced_only"] == 400
    expected_state = "READY" if authenticated == 2 else "BLOCKED"
    assert report["phase1b_exit"]["state"] == expected_state
