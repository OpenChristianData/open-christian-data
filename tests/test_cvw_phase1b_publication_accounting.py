"""Contract tests for exact publication-row ownership."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cvw_phase1b import generate_catalog_accounting
from cvw_phase1b.publication_accounting import (
    PublicationAccountingError,
    generate_publication_accounting,
)
from tests.test_cvw_phase1b_catalog_accounting import _json_bytes, _write, accounting_repo


REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_CATALOG_REGISTRY = REPO_ROOT / "cvw_phase1b/fixtures/catalog_accounting.json"
LIVE_PUBLICATION_REGISTRY = REPO_ROOT / "cvw_phase1b/fixtures/publication_accounting.json"
LIVE_EXPORT = REPO_ROOT / "exports/huggingface/bible_text.jsonl"


@pytest.fixture
def publication_repo(
    accounting_repo: tuple[Path, Path],
) -> tuple[Path, Path, dict[str, object]]:
    root, catalog_registry = accounting_repo
    _write(
        root / "cvw_phase1b/publication_accounting.py",
        (REPO_ROOT / "cvw_phase1b/publication_accounting.py").read_bytes(),
    )
    _write(
        root / "build/scripts/export_huggingface.py",
        (REPO_ROOT / "build/scripts/export_huggingface.py").read_bytes(),
    )
    rows = b"".join(
        (
            json.dumps(
                {
                "_source_id": "asv",
                "_source_title": "American Standard Version",
                "_author": None,
                "_schema_type": "bible_text",
                "osis": osis,
                "text": text,
                },
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        for osis, text in (("Gen.1.1", "In the beginning"), ("Exod.1.1", "Now these are"))
    )
    export_path = "exports/huggingface/bible_text.jsonl"
    _write(root / export_path, rows)
    registry = root / "cvw_phase1b/fixtures/publication_accounting.json"
    _write(
        registry,
        _json_bytes(
            {
                "identity": "verification-publication-accounting-v1",
                "exports": [
                    {
                        "schema_type": "bible_text",
                        "path": export_path,
                        "expected_rows": 2,
                        "expected_raw_sha256": hashlib.sha256(rows).hexdigest(),
                    }
                ],
            }
        ),
    )
    catalog_report = generate_catalog_accounting(root, catalog_registry)
    return root, registry, catalog_report


def test_publication_accounting_resolves_every_row_to_one_work(
    publication_repo: tuple[Path, Path, dict[str, object]],
) -> None:
    root, registry, catalog_report = publication_repo

    report = generate_publication_accounting(root, registry, catalog_report)

    assert report["counts"] == {
        "export_files": 1,
        "rows_owned": 2,
        "work_units_included": 1,
    }
    assert report["exports"][0]["work_units"] == 1
    assert report["phase1b_publication_exit"] == {"reasons": [], "state": "READY"}


@pytest.mark.parametrize("defect", ["unknown-source", "wrong-schema", "blank-row", "hash"])
def test_publication_ownership_defects_fail_closed(
    publication_repo: tuple[Path, Path, dict[str, object]], defect: str
) -> None:
    root, registry, catalog_report = publication_repo
    export = root / "exports/huggingface/bible_text.jsonl"
    if defect == "blank-row":
        export.write_bytes(export.read_bytes() + b"\n")
    else:
        lines = export.read_text(encoding="utf-8").splitlines()
        first = json.loads(lines[0])
        if defect == "unknown-source":
            first["_source_id"] = "unknown"
        elif defect == "wrong-schema":
            first["_schema_type"] = "commentary"
        else:
            payload = json.loads(registry.read_bytes())
            payload["exports"][0]["expected_raw_sha256"] = "0" * 64
            registry.write_bytes(_json_bytes(payload))
        if defect != "hash":
            lines[0] = json.dumps(first)
            export.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(
        PublicationAccountingError,
        match="resolve|schema does not match|blank row|hash drifted",
    ):
        generate_publication_accounting(root, registry, catalog_report)


@pytest.mark.skipif(not LIVE_EXPORT.is_file(), reason="local publication snapshot is unavailable")
def test_live_publication_accounting_owns_all_805146_rows() -> None:
    catalog_report = generate_catalog_accounting(REPO_ROOT, LIVE_CATALOG_REGISTRY)

    report = generate_publication_accounting(
        REPO_ROOT,
        LIVE_PUBLICATION_REGISTRY,
        catalog_report,
    )

    assert report["counts"] == {
        "export_files": 12,
        "rows_owned": 805146,
        "work_units_included": 402,
    }
