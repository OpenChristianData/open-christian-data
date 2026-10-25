"""Build a text-preserving, work-bound Abstract of Principles rehearsal."""

from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from build.tools.project_abstract_of_principles import (
    ACCEPTANCE,
    EXPECTED_ACCEPTANCE_SHA256,
    EXPECTED_MASTER_SHA256,
    MASTER,
    README,
    README_SHA256,
    ROOT,
    SOURCE,
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


SOURCE_NOTE = Path("sources/doctrinal-documents/abstract-of-principles/README.source.md")
PUBLIC_NOTICE = Path("data/doctrinal-documents/abstract-of-principles/README.md")
NOTICE_BINDING = Path("library/works/abstract-of-principles/publication/notice-binding.json")
PROJECTION = ACCEPTANCE.parent / "publication/independent-correspondence.json"
EVIDENCE = Path(
    "library/works/abstract-of-principles/publication/"
    "offline-release-rehearsal-20260930"
)
EXPECTED_SOURCE_NOTE_SHA256 = "cd3a5502e7dcc36243f42bdb60dbb006abb987c9b272686e83f0a670fd7c1b60"
EXPECTED_PUBLIC_NOTICE_SHA256 = "5b641cedf8308e5c7e627b99dfab87647bdf7d3df69be412debce33c83016b89"
EXPECTED_ROW_COUNT = 20
CATEGORY = "doctrinal_documents"
RELEASE_ID = "abstract-of-principles-offline-rehearsal-20260930-v1"
SOURCE_MANIFEST = Path(
    "sources/doctrinal-documents/lib063-creeds-json/abstract-of-principles/"
    "abstract-of-principles.source-manifest.json"
)
SOURCE_CONFIG = SOURCE_MANIFEST.parent / "config.json"


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(value))


def _copy_exact(source: Path, target: Path) -> None:
    content = source.read_bytes()
    if target.exists() and target.read_bytes() != content:
        raise PipelineError(f"existing Abstract release evidence differs: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)


def _selection(root: Path) -> dict[str, Any]:
    binding = json.loads((root / NOTICE_BINDING).read_bytes())
    if binding.get("work_id") != WORK_ID or binding.get("edition_id") != "abstract-of-principles-creeds-json":
        raise PipelineError("Abstract notice binding identity differs")
    return {
        "schema_version": "2.0",
        "release_id": RELEASE_ID,
        "items": [
            {
                "item_id": WORK_ID,
                "category": CATEGORY,
                "acceptance_path": ACCEPTANCE.as_posix(),
                "public_notices": binding["public_notices"],
            }
        ],
    }


def _public_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Remove only the retained local path that the public boundary forbids."""
    # Projected rows reuse one provenance mapping in memory.  Copy each row
    # separately so a removal cannot mutate another row through that alias.
    public = [deepcopy(row) for row in rows]
    changes = []
    for index, (source_row, row) in enumerate(zip(rows, public, strict=True)):
        provenance = row.get("provenance")
        if not isinstance(provenance, dict):
            raise PipelineError(f"Abstract row {index} lacks provenance")
        location = provenance.pop("source_location", None)
        if location != SOURCE.as_posix():
            raise PipelineError(f"Abstract row {index} source location differs")
        if provenance.get("source_url") != "https://github.com/NonlinearFruit/Creeds.json":
            raise PipelineError(f"Abstract row {index} canonical source URL differs")
        restored = deepcopy(row)
        restored["provenance"]["source_location"] = location
        if _canonical(restored) != _canonical(source_row):
            raise PipelineError(f"Abstract row {index} changes beyond source_location omission")
        changes.append(
            {
                "row_index": index,
                "record_id": row["record_id"],
                "removed_field": "provenance.source_location",
                "removed_value_sha256": sha256(location.encode("utf-8")).hexdigest(),
                "preserved_public_row_sha256": sha256(_canonical(row)).hexdigest(),
            }
        )
    private_errors = _scan(public, f"public/data/{CATEGORY}/train.jsonl")
    if private_errors:
        raise PipelineError(private_errors[0])
    return public, changes


def _authority(root: Path) -> dict[str, str]:
    public_schema = root / "schemas/v2/public-row.schema.json"
    schema = json.loads(public_schema.read_bytes())
    provenance = schema["properties"]["provenance"]
    if (
        "source_location" in provenance.get("required", [])
        or "source_url" not in provenance.get("properties", {})
    ):
        raise PipelineError("public provenance schema no longer permits the bounded omission")
    values = {
        "source_sha256": _sha(root / SOURCE),
        "source_readme_sha256": _sha(root / README),
        "master_sha256": _sha(root / MASTER),
        "acceptance_sha256": _sha(root / ACCEPTANCE),
        "source_note_sha256": _sha(root / SOURCE_NOTE),
        "public_notice_sha256": _sha(root / PUBLIC_NOTICE),
        "notice_binding_sha256": _sha(root / NOTICE_BINDING),
        "projection_correspondence_sha256": _sha(root / PROJECTION),
        "public_row_schema_sha256": _sha(public_schema),
    }
    expected = {
        "source_sha256": SOURCE_SHA256,
        "source_readme_sha256": README_SHA256,
        "master_sha256": EXPECTED_MASTER_SHA256,
        "acceptance_sha256": EXPECTED_ACCEPTANCE_SHA256,
        "source_note_sha256": EXPECTED_SOURCE_NOTE_SHA256,
        "public_notice_sha256": EXPECTED_PUBLIC_NOTICE_SHA256,
    }
    if any(values[key] != digest for key, digest in expected.items()):
        raise PipelineError("Abstract source, accepted authority, or notice changed")
    return values


@contextmanager
def _isolated_authority(root: Path):
    """Snapshot only this work so concurrent library edits cannot affect replay."""
    with tempfile.TemporaryDirectory(prefix="aop-") as scratch:
        isolated = Path(scratch) / "root"
        work = Path("library/works/abstract-of-principles")
        work_source = root / work
        for source in work_source.rglob("*"):
            if source.is_file():
                target = _io_path(isolated / work / source.relative_to(work_source))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(_io_path(source).read_bytes())
        for relative in (SOURCE, README, SOURCE_MANIFEST, SOURCE_CONFIG):
            target = _io_path(isolated / relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_io_path(root / relative).read_bytes())
        yield isolated


def _project_and_verify(root: Path) -> dict[str, Any]:
    with _isolated_authority(root) as isolated:
        acceptance = isolated / ACCEPTANCE
        projection = project_accepted_doctrinal_documents(
            isolated, acceptance_path=acceptance
        )
        errors = verify_accepted_doctrinal_documents(
            isolated,
            acceptance_path=acceptance,
            rows=projection["rows"],
            receipt=projection["receipt"],
        )
    if errors:
        raise PipelineError(f"accepted-master correspondence differs: {errors[0]}")
    return projection


def verify_rehearsal(root: Path, release: Path, selection: dict[str, Any]) -> dict[str, Any]:
    """Independently replay the source-bound projection and public adapter."""
    errors: list[str] = []
    try:
        root = Path(root).resolve(strict=True)
        release = Path(release).resolve(strict=True)
        _authority(root)
        if selection != _selection(root):
            raise PipelineError("Abstract rehearsal selection differs")
        if json.loads((release / "internal/release-selection.json").read_bytes()) != selection:
            raise PipelineError("stored Abstract release selection differs")
        projection = _project_and_verify(root)
        expected_rows, expected_changes = _public_rows(projection["rows"])
        rows_path = release / f"public/data/{CATEGORY}/train.jsonl"
        actual_rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines()]
        if _canonical(actual_rows) != _canonical(expected_rows):
            raise PipelineError("public rows differ from the bounded path-removal adapter")
        receipt = json.loads(
            (release / f"internal/projection-receipts/{WORK_ID}.json").read_bytes()
        )
        if (
            receipt.get("contract") != "ocd-abstract-of-principles-public-adapter-v1"
            or receipt.get("master_sha256") != EXPECTED_MASTER_SHA256
            or receipt.get("source_projection_receipt") != projection["receipt"]
            or receipt.get("adapter_changes") != expected_changes
            or receipt.get("public_rows_sha256") != _sha(rows_path)
        ):
            raise PipelineError("Abstract adapter receipt differs")
        report = json.loads((release / "internal/release-report.json").read_bytes())
        notices = notice_texts_for_item(root, selection["items"][0], root / ACCEPTANCE)
        boundary_errors = check_public_boundary(release, report, notices=notices)
        if boundary_errors:
            raise PipelineError(boundary_errors[0])
        configuration = report["configurations"][0]
        if (
            configuration.get("category") != CATEGORY
            or configuration.get("row_count") != EXPECTED_ROW_COUNT
            or report.get("accounting")
            != {"requested": 1, "included": 1, "warned": 0, "failed": 0, "excluded": 0}
        ):
            raise PipelineError("Abstract release accounting differs")
        check_rows(
            (release / configuration["typed_companion"]["path"]).read_bytes(),
            actual_rows,
            configuration["features"],
        )
    except (PipelineError, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
    return {"status": "pass" if not errors else "fail", "errors": errors}


def _reader_check(release: Path) -> dict[str, Any]:
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    os.environ["HF_HUB_OFFLINE"] = "1"
    import datasets
    import pyarrow

    rows_path = release / f"public/data/{CATEGORY}/train.jsonl"
    rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines()]
    with tempfile.TemporaryDirectory(prefix="ocd-abstract-reader-") as cache:
        for streaming in (False, True):
            loaded = datasets.load_dataset(
                str(release / "public"),
                name=CATEGORY,
                split="train",
                streaming=streaming,
                cache_dir=cache,
            )
            count = 0
            for count, row in enumerate(loaded, start=1):
                if count > len(rows):
                    raise PipelineError("Abstract reader added rows")
                compare_rows(rows[count - 1], row, f"{CATEGORY}/{count - 1}")
            if count != len(rows):
                raise PipelineError("Abstract reader omitted rows")
    return {
        "status": "pass",
        "category": CATEGORY,
        "rows": len(rows),
        "normal_and_streaming": "pass",
        "all_original_values_and_order_preserved": True,
        "datasets_version": datasets.__version__,
        "pyarrow_version": pyarrow.__version__,
        "offline": True,
        "publication_performed": False,
    }


def rehearse_release(
    root: Path = ROOT,
    *,
    evidence_dir: Path | None = None,
) -> dict[str, Any]:
    root = Path(root).resolve(strict=True)
    evidence = Path(evidence_dir) if evidence_dir is not None else root / EVIDENCE
    authority = _authority(root)
    selection = _selection(root)
    projection = _project_and_verify(root)
    rows, changes = _public_rows(projection["rows"])
    if len(rows) != EXPECTED_ROW_COUNT:
        raise PipelineError("Abstract release row count differs")

    with tempfile.TemporaryDirectory(prefix="ocd-abstract-principles-release-") as scratch:
        release = Path(scratch) / "release"
        rows_path = release / f"public/data/{CATEGORY}/train.jsonl"
        rows_path.parent.mkdir(parents=True)
        rows_path.write_bytes(b"".join(_canonical(row) for row in rows))
        features = configuration_features(rows)
        typed_path = release / f"public/data/{CATEGORY}/train.arrow"
        typed_path.write_bytes(encode_rows(rows, features))
        configuration = {
            "category": CATEGORY,
            "path": f"public/data/{CATEGORY}/train.jsonl",
            "row_count": len(rows),
            "sha256": _sha(rows_path),
            "features": features,
            "typed_companion": {
                "path": f"public/data/{CATEGORY}/train.arrow",
                "sha256": _sha(typed_path),
            },
        }
        notices = notice_texts_for_item(root, selection["items"][0], root / ACCEPTANCE)
        (release / "public/README.md").write_text(
            render_dataset_card([configuration], notices=notices),
            encoding="utf-8",
            newline="\n",
        )
        _write(release / "internal/release-selection.json", selection)
        receipt = {
            "contract": "ocd-abstract-of-principles-public-adapter-v1",
            "identity": projection["receipt"]["identity"],
            "master_sha256": EXPECTED_MASTER_SHA256,
            "source_projection_receipt": projection["receipt"],
            "adapter_scope": "Remove only optional provenance.source_location from each public row; retain provenance.source_url and all text, structure, source references, and remaining fields exactly.",
            "adapter_changes": changes,
            "public_rows_sha256": _sha(rows_path),
            "row_count": len(rows),
        }
        _write(release / f"internal/projection-receipts/{WORK_ID}.json", receipt)
        report = {
            "schema_version": "work-bound-1.0",
            "release_version": "ocd-abstract-of-principles-offline-rehearsal-v1",
            "release_id": RELEASE_ID,
            "status": "pass",
            "items": [
                {
                    "item_id": WORK_ID,
                    "category": CATEGORY,
                    "acceptance_path": ACCEPTANCE.as_posix(),
                    "status": "included",
                    "reasons": [],
                    "row_count": len(rows),
                    "receipt_path": f"internal/projection-receipts/{WORK_ID}.json",
                }
            ],
            "accounting": {"requested": 1, "included": 1, "warned": 0, "failed": 0, "excluded": 0},
            "configurations": [configuration],
            "generic_route_disposition": {
                "status": "blocked",
                "reason": "The maintained generic release checker rejects the retained local provenance.source_location path on all 20 otherwise verified rows.",
            },
        }
        _write(release / "internal/release-report.json", report)
        independent = verify_rehearsal(root, release, selection)
        if independent != {"status": "pass", "errors": []}:
            raise PipelineError(f"Abstract independent rehearsal verification differs: {independent}")
        _write(release / "internal/checks/independent-check.json", independent)
        reader = _reader_check(release)

        paths = [path for path in sorted(release.rglob("*")) if path.is_file()]
        release_evidence = evidence / "release-evidence"
        for path in paths:
            _copy_exact(path, release_evidence / path.relative_to(release))

    retained_check = verify_rehearsal(root, release_evidence, selection)
    if retained_check != {"status": "pass", "errors": []}:
        raise PipelineError(f"retained Abstract rehearsal differs: {retained_check}")
    _write(evidence / "selection.json", selection)
    _write(evidence / "reader-proof.json", reader)
    files = {
        path.relative_to(evidence).as_posix(): _sha(path)
        for path in sorted(release_evidence.rglob("*"))
        if path.is_file()
    }
    files["selection.json"] = _sha(evidence / "selection.json")
    files["reader-proof.json"] = _sha(evidence / "reader-proof.json")
    _write(evidence / "files.sha256.json", files)
    result = {
        "contract": "ocd-abstract-of-principles-one-work-offline-release-rehearsal-v1",
        "status": "offline-verified-not-authorized-for-publication",
        "work_id": WORK_ID,
        "edition_id": "abstract-of-principles-creeds-json",
        "authority": authority,
        "selection_sha256": _sha(evidence / "selection.json"),
        "release_report_sha256": _sha(release_evidence / "internal/release-report.json"),
        "projection_receipt_sha256": _sha(
            release_evidence / f"internal/projection-receipts/{WORK_ID}.json"
        ),
        "public_rows_sha256": _sha(
            release_evidence / f"public/data/{CATEGORY}/train.jsonl"
        ),
        "row_count": len(rows),
        "item_status": "included",
        "adapter": {
            "removed_field": "provenance.source_location",
            "removed_occurrences": len(changes),
            "text_or_structure_changes": 0,
            "canonical_safe_source_field_retained": "provenance.source_url",
            "private_paths_remaining": 0,
        },
        "independent_check": retained_check,
        "reader_status": reader["status"],
        "reader_normal_and_streaming": reader["normal_and_streaming"],
        "files_sha256_manifest": _sha(evidence / "files.sha256.json"),
        "human_acceptance": "not-recorded",
        "rights_clearance": "not-recorded",
        "release_selection": "rehearsal-only",
        "publication_authorization": "not-recorded",
        "publication_performed": False,
    }
    _write(evidence / "rehearsal-index.json", result)
    return result


if __name__ == "__main__":
    print(json.dumps(rehearse_release(), ensure_ascii=False, sort_keys=True))
