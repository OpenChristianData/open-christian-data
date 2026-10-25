"""Verify a one-work public view of the accepted First Helvetic Confession."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from build.tools.project_first_helvetic_confession import (
    ACCEPTANCE,
    ACCEPTANCE_SHA256,
    MASTER,
    MASTER_SHA256,
    NOTICE_BINDING,
    PUBLIC_NOTICE,
    README,
    README_SHA256,
    ROOT,
    SOURCE,
    SOURCE_NOTE,
    SOURCE_SHA256,
    WORK_ID,
)
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.doctrinal_documents import (
    project_accepted_doctrinal_documents,
    verify_accepted_doctrinal_documents,
)
from ocd_kernel.release.features import configuration_features
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.public_allowlist import _scan, check_public_boundary, render_dataset_card
from ocd_kernel.release.typed_rows import check_rows, compare_rows, encode_rows
from ocd_kernel.tei.install_accepted import _io_path


CATEGORY = "doctrinal_documents"
EDITION_ID = "first-helvetic-confession-creeds-json"
RELEASE_ID = "first-helvetic-confession-offline-rehearsal-20261001-v1"
EVIDENCE = Path("library/works/first-helvetic-confession/publication/offline-release-rehearsal-20261001")
PROJECTION = ACCEPTANCE.parent / "publication/independent-correspondence.json"
EXPECTED_SOURCE_NOTE_SHA256 = "512762a59305edd47890f1736058f3d369b20fe9cf9eeeac0d065f2268f47cb1"
EXPECTED_PUBLIC_NOTICE_SHA256 = "c6aa9bba28a6a1cc88afd5d8bf460204b22737c8c431e130b36ec3c96cf48915"
SOURCE_URL = "https://github.com/NonlinearFruit/Creeds.json"
ROW_COUNT = 19


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(value))


def _authority(root: Path) -> dict[str, str]:
    schema_path = root / "schemas/v2/public-row.schema.json"
    schema = json.loads(schema_path.read_bytes())
    provenance = schema["properties"]["provenance"]
    if ("source_location" in provenance.get("required", [])
            or "source_url" not in provenance.get("properties", {})):
        raise PipelineError("public schema no longer permits the bounded path omission")
    paths = {
        "source_sha256": SOURCE,
        "source_readme_sha256": README,
        "master_sha256": MASTER,
        "acceptance_sha256": ACCEPTANCE,
        "source_note_sha256": SOURCE_NOTE,
        "public_notice_sha256": PUBLIC_NOTICE,
        "notice_binding_sha256": NOTICE_BINDING,
        "projection_correspondence_sha256": PROJECTION,
        "public_row_schema_sha256": Path("schemas/v2/public-row.schema.json"),
    }
    values = {key: _sha(root / path) for key, path in paths.items()}
    expected = {
        "source_sha256": SOURCE_SHA256,
        "source_readme_sha256": README_SHA256,
        "master_sha256": MASTER_SHA256,
        "acceptance_sha256": ACCEPTANCE_SHA256,
        "source_note_sha256": EXPECTED_SOURCE_NOTE_SHA256,
        "public_notice_sha256": EXPECTED_PUBLIC_NOTICE_SHA256,
    }
    if any(values[key] != digest for key, digest in expected.items()):
        raise PipelineError("First Helvetic Confession source, accepted master, or notice changed")
    correspondence = json.loads((root / PROJECTION).read_bytes())
    if (correspondence.get("status") != "pass" or correspondence.get("row_count") != ROW_COUNT
            or correspondence.get("source_sha256") != SOURCE_SHA256
            or correspondence.get("master_sha256") != MASTER_SHA256):
        raise PipelineError("installed projection correspondence differs")
    return values


def _selection(root: Path) -> dict[str, Any]:
    binding = json.loads((root / NOTICE_BINDING).read_bytes())
    if binding.get("work_id") != WORK_ID or binding.get("edition_id") != EDITION_ID:
        raise PipelineError("First Helvetic Confession notice binding identity differs")
    return {
        "schema_version": "2.0",
        "release_id": RELEASE_ID,
        "items": [{
            "item_id": WORK_ID,
            "category": CATEGORY,
            "acceptance_path": ACCEPTANCE.as_posix(),
            "public_notices": binding["public_notices"],
        }],
    }


def _project_and_verify(root: Path) -> dict[str, Any]:
    projection = project_accepted_doctrinal_documents(
        _io_path(root), acceptance_path=_io_path(root / ACCEPTANCE)
    )
    errors = verify_accepted_doctrinal_documents(
        _io_path(root), acceptance_path=_io_path(root / ACCEPTANCE),
        rows=projection["rows"], receipt=projection["receipt"],
    )
    if errors:
        raise PipelineError(f"accepted-master correspondence differs: {errors[0]}")
    if (len(projection["rows"]) != ROW_COUNT
            or [row["number"] for row in projection["rows"]] != [str(i) for i in range(1, ROW_COUNT + 1)]):
        raise PipelineError("First Helvetic Confession article order differs")
    return projection


def _public_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    public = [deepcopy(row) for row in rows]
    changes = []
    for index, (original, row) in enumerate(zip(rows, public, strict=True)):
        provenance = row.get("provenance")
        if not isinstance(provenance, dict):
            raise PipelineError(f"row {index} lacks source provenance")
        location = provenance.pop("source_location", None)
        if location != SOURCE.as_posix() or provenance.get("source_url") != SOURCE_URL:
            raise PipelineError(f"row {index} has an unexpected source binding")
        restored = deepcopy(row)
        restored["provenance"]["source_location"] = location
        if _canonical(restored) != _canonical(original):
            raise PipelineError(f"row {index} changes beyond source_location omission")
        changes.append({
            "row_index": index,
            "record_id": row["record_id"],
            "removed_field": "provenance.source_location",
            "removed_value_sha256": sha256(location.encode("utf-8")).hexdigest(),
            "preserved_public_row_sha256": sha256(_canonical(row)).hexdigest(),
        })
    errors = _scan(public, f"public/data/{CATEGORY}/train.jsonl")
    if errors:
        raise PipelineError(errors[0])
    return public, changes


def verify_rehearsal(root: Path, release: Path, selection: dict[str, Any]) -> dict[str, Any]:
    """Replay accepted correspondence and check the exact public path omission."""
    errors: list[str] = []
    try:
        root = Path(root).resolve(strict=True)
        release = Path(release).resolve(strict=True)
        _authority(root)
        if selection != _selection(root):
            raise PipelineError("external release selection differs from the notice binding")
        if json.loads((release / "internal/release-selection.json").read_bytes()) != selection:
            raise PipelineError("stored release selection differs")
        projection = _project_and_verify(root)
        expected_rows, expected_changes = _public_rows(projection["rows"])
        rows_path = release / f"public/data/{CATEGORY}/train.jsonl"
        actual_rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines()]
        if _canonical(actual_rows) != _canonical(expected_rows):
            raise PipelineError("public rows differ from the one-field path omission")
        receipt = json.loads((release / f"internal/projection-receipts/{WORK_ID}.json").read_bytes())
        if (receipt.get("contract") != "ocd-first-helvetic-confession-public-adapter-v1"
                or receipt.get("source_projection_receipt") != projection["receipt"]
                or receipt.get("adapter_changes") != expected_changes
                or receipt.get("master_sha256") != MASTER_SHA256
                or receipt.get("public_rows_sha256") != _sha(rows_path)):
            raise PipelineError("public adapter receipt differs")
        report = json.loads((release / "internal/release-report.json").read_bytes())
        if (report.get("release_id") != RELEASE_ID or report.get("status") != "pass"
                or report.get("accounting") != {"requested": 1, "included": 1, "warned": 0, "failed": 0, "excluded": 0}
                or len(report.get("configurations", [])) != 1):
            raise PipelineError("one-work release accounting differs")
        configuration = report["configurations"][0]
        if (configuration.get("category") != CATEGORY
                or configuration.get("row_count") != ROW_COUNT
                or configuration.get("sha256") != _sha(rows_path)
                or configuration.get("features") != configuration_features(actual_rows)):
            raise PipelineError("public configuration differs")
        notices = notice_texts_for_item(root, selection["items"][0], root / ACCEPTANCE)
        boundary_errors = check_public_boundary(release, report, notices=notices)
        if boundary_errors:
            raise PipelineError(boundary_errors[0])
        check_rows(
            (release / configuration["typed_companion"]["path"]).read_bytes(),
            actual_rows, configuration["features"],
        )
    except (PipelineError, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
    return {"status": "pass" if not errors else "fail", "errors": errors}


def _reader_check(release: Path) -> dict[str, Any]:
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    os.environ["HF_HUB_OFFLINE"] = "1"
    import datasets
    import pyarrow

    rows = [json.loads(line) for line in
            (release / f"public/data/{CATEGORY}/train.jsonl").read_text(encoding="utf-8").splitlines()]
    with tempfile.TemporaryDirectory(prefix="ocd-first-helvetic-reader-") as cache:
        for streaming in (False, True):
            loaded = datasets.load_dataset(
                str(release / "public"), name=CATEGORY, split="train",
                streaming=streaming, cache_dir=cache,
            )
            count = 0
            for count, row in enumerate(loaded, start=1):
                if count > len(rows):
                    raise PipelineError("reader added rows")
                compare_rows(rows[count - 1], row, f"{CATEGORY}/{count - 1}")
            if count != len(rows):
                raise PipelineError("reader omitted rows")
    return {
        "status": "pass", "category": CATEGORY, "rows": len(rows),
        "normal_and_streaming": "pass", "all_original_values_and_order_preserved": True,
        "datasets_version": datasets.__version__, "pyarrow_version": pyarrow.__version__,
        "offline": True, "publication_performed": False,
    }


def rehearse_release(root: Path = ROOT) -> dict[str, Any]:
    root = Path(root).resolve(strict=True)
    evidence = root / EVIDENCE
    if evidence.exists():
        raise FileExistsError(f"rehearsal evidence already exists: {evidence}")
    authority = _authority(root)
    selection = _selection(root)
    projection = _project_and_verify(root)
    rows, changes = _public_rows(projection["rows"])
    with tempfile.TemporaryDirectory(prefix="ocd-first-helvetic-release-") as scratch:
        release = Path(scratch) / "release"
        rows_path = release / f"public/data/{CATEGORY}/train.jsonl"
        rows_path.parent.mkdir(parents=True)
        rows_path.write_bytes(b"".join(_canonical(row) for row in rows))
        features = configuration_features(rows)
        typed_path = release / f"public/data/{CATEGORY}/train.arrow"
        typed_path.write_bytes(encode_rows(rows, features))
        configuration = {
            "category": CATEGORY, "path": f"public/data/{CATEGORY}/train.jsonl",
            "row_count": len(rows), "sha256": _sha(rows_path), "features": features,
            "typed_companion": {"path": f"public/data/{CATEGORY}/train.arrow", "sha256": _sha(typed_path)},
        }
        notices = notice_texts_for_item(root, selection["items"][0], root / ACCEPTANCE)
        (release / "public/README.md").write_text(
            render_dataset_card([configuration], notices=notices), encoding="utf-8", newline="\n"
        )
        _write(release / "internal/release-selection.json", selection)
        _write(release / f"internal/projection-receipts/{WORK_ID}.json", {
            "contract": "ocd-first-helvetic-confession-public-adapter-v1",
            "identity": projection["receipt"]["identity"],
            "master_sha256": MASTER_SHA256,
            "source_projection_receipt": projection["receipt"],
            "adapter_scope": "Remove only optional provenance.source_location from each public row; preserve every other field exactly.",
            "adapter_changes": changes,
            "public_rows_sha256": _sha(rows_path),
            "row_count": len(rows),
        })
        report = {
            "schema_version": "work-bound-1.0",
            "release_version": "ocd-first-helvetic-confession-offline-rehearsal-v1",
            "release_id": RELEASE_ID,
            "status": "pass",
            "items": [{
                "item_id": WORK_ID, "category": CATEGORY, "acceptance_path": ACCEPTANCE.as_posix(),
                "status": "included", "reasons": [], "row_count": len(rows),
                "receipt_path": f"internal/projection-receipts/{WORK_ID}.json",
            }],
            "accounting": {"requested": 1, "included": 1, "warned": 0, "failed": 0, "excluded": 0},
            "configurations": [configuration],
            "generic_route_disposition": {
                "status": "blocked",
                "reason": "Generic release assembly retains the local provenance.source_location path in each accepted projection row.",
            },
        }
        _write(release / "internal/release-report.json", report)
        independent = verify_rehearsal(root, release, selection)
        if independent != {"status": "pass", "errors": []}:
            raise PipelineError(f"independent work-local release verification failed: {independent}")
        _write(release / "internal/checks/independent-check.json", independent)
        reader = _reader_check(release)
        release_evidence = evidence / "release-evidence"
        for path in sorted(release.rglob("*")):
            if path.is_file():
                target = release_evidence / path.relative_to(release)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())

    retained_check = verify_rehearsal(root, release_evidence, selection)
    if retained_check != {"status": "pass", "errors": []}:
        raise PipelineError(f"retained work-local release verification failed: {retained_check}")
    _write(evidence / "selection.json", selection)
    _write(evidence / "reader-proof.json", reader)
    public_rows_path = release_evidence / f"public/data/{CATEGORY}/train.jsonl"
    public_bytes = public_rows_path.read_bytes()
    public_rows = [json.loads(line) for line in public_bytes.decode("utf-8").splitlines()]
    statistics = {
        "release_id": RELEASE_ID, "status": "pass",
        "authority": "First Helvetic Confession source-bound projection, one-field public adapter, and independent work-local verifier",
        "configurations": [{
            "category": CATEGORY, "records": len(public_rows),
            "text_characters": sum(len(row["text"]) for row in public_rows),
            "uncompressed_bytes": len(public_bytes), "sha256": _sha(public_rows_path),
        }],
        "total": {
            "records": len(public_rows),
            "text_characters": sum(len(row["text"]) for row in public_rows),
            "uncompressed_bytes": len(public_bytes),
        },
        "limits": ["Character counts are Unicode code points, not tokenizer counts.",
                   "This offline report does not authorize publication."],
    }
    _write(evidence / "statistics.json", statistics)
    files = {path.relative_to(evidence).as_posix(): _sha(path)
             for path in sorted(release_evidence.rglob("*")) if path.is_file()}
    for name in ("selection.json", "reader-proof.json", "statistics.json"):
        files[name] = _sha(evidence / name)
    _write(evidence / "files.sha256.json", files)
    result = {
        "contract": "ocd-first-helvetic-confession-one-work-offline-release-rehearsal-v1",
        "status": "offline-verified-not-authorized-for-publication",
        "work_id": WORK_ID, "edition_id": EDITION_ID,
        "authority": authority,
        "selection_sha256": _sha(evidence / "selection.json"),
        "release_report_sha256": _sha(release_evidence / "internal/release-report.json"),
        "projection_receipt_sha256": _sha(release_evidence / f"internal/projection-receipts/{WORK_ID}.json"),
        "public_rows_sha256": _sha(public_rows_path),
        "row_count": len(rows), "item_status": "included",
        "adapter": {
            "removed_field": "provenance.source_location", "removed_occurrences": len(changes),
            "text_or_structure_changes": 0,
            "canonical_safe_source_field_retained": "provenance.source_url",
            "private_paths_remaining": 0,
        },
        "independent_check": retained_check,
        "reader_status": reader["status"],
        "reader_normal_and_streaming": reader["normal_and_streaming"],
        "statistics_status": statistics["status"],
        "files_sha256_manifest": _sha(evidence / "files.sha256.json"),
        "human_acceptance": "not-recorded", "rights_clearance": "not-recorded",
        "release_selection": "rehearsal-only", "publication_authorization": "not-recorded",
        "publication_performed": False,
    }
    _write(evidence / "rehearsal-index.json", result)
    return result


if __name__ == "__main__":
    print(json.dumps(rehearse_release(), ensure_ascii=False, sort_keys=True))
