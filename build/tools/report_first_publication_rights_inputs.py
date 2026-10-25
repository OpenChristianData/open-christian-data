"""Index acquisition-sidecar rights inputs for the first publication set.

This is a source-input inventory, not a clearance or release decision. It
reads canonical library sidecars and writes only the requested report path.
"""

from __future__ import annotations

from ocd_kernel.lib.path_io import io_glob, io_path, resolve_path

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from build.tools.derive_library_release_selection import _ocr_tickets
from ocd_kernel.library.identities import discover_library


def _family(provider: str) -> str:
    if "openMGH" in provider:
        return "openmgh"
    if provider in {"CCEL", "Christian Classics Ethereal Library"}:
        return "ccel"
    if provider.startswith("Project Gutenberg"):
        return "project-gutenberg"
    if "Creeds.json" in provider:
        return "creeds-json"
    return "other"


def _edition_acquisition_ids(work: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for form in work.get("textual_forms", []):
        for edition in form.get("editions", []):
            ids.extend(edition.get("acquisition_ids", []))
    return ids


def _acquisitions(work_dir: Path, root: Path) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    forms_root = work_dir / "forms"
    paths = sorted(
        io_glob(forms_root, "*/editions/*/acquisitions/*.json"),
        key=lambda item: item.as_posix(),
    )
    for path in paths:
        content = io_path(path).read_bytes()
        record = json.loads(content)
        if not isinstance(record, dict):
            raise ValueError(f"{work_dir.name}: acquisition is not an object: {path.name}")
        relative = path.relative_to(root).as_posix()
        source_path = record.get("source_path")
        if isinstance(source_path, str) and Path(source_path).suffix.lower() == ".zip":
            raise ValueError(f"{work_dir.name}: ZIP is listed as source: {relative}")
        retained = record.get("retained_files", [])
        if not isinstance(retained, list):
            raise ValueError(f"{work_dir.name}: invalid retained files: {relative}")
        provider = record.get("provider")
        if not isinstance(provider, str) or not provider:
            raise ValueError(f"{work_dir.name}: missing provider: {relative}")
        found.append(
            {
                "acquisition_id": record.get("acquisition_id"),
                "edition_id": record.get("edition_id"),
                "path": relative,
                "sha256": hashlib.sha256(content).hexdigest(),
                "provider": provider,
                "family": _family(provider),
                "source_path": source_path,
                "source_sha256": record.get("source_sha256"),
                "rights": record.get("rights"),
                "warnings": record.get("warnings", []),
                "retained_notice_paths": sorted(
                    item["path"]
                    for item in retained
                    if isinstance(item, dict)
                    and isinstance(item.get("path"), str)
                    and Path(item["path"]).name.lower().startswith("readme")
                ),
            }
        )
    return sorted(found, key=lambda item: (item["edition_id"], item["acquisition_id"]))


def build_index(root: Path) -> dict[str, Any]:
    library = discover_library(root)
    by_id = {work.work_id: work for work in library}
    ocr = _ocr_tickets(root, set(by_id))
    identity_only = {work.work_id for work in library if not work.editions}
    if identity_only != set(ocr):
        raise ValueError(
            "OCR scope tickets and identity-only work sidecars differ: "
            f"ticket_only={sorted(set(ocr) - identity_only)}, "
            f"identity_only={sorted(identity_only - set(ocr))}"
        )

    rows: list[dict[str, Any]] = []
    excluded: list[str] = []
    acquisition_count = 0
    family_works: dict[str, set[str]] = {}
    without_acquisitions: list[str] = []
    for work_record in library:
        work_dir = work_record.path.parent
        work_path = work_dir / "work.json"
        state_path = work_dir / "state.json"
        if not io_path(work_path).is_file() or not io_path(state_path).is_file():
            raise ValueError(f"{work_dir.name}: work/state pair is incomplete")
        work = json.loads(io_path(work_path).read_text(encoding="utf-8"))
        expected = _edition_acquisition_ids(work)
        acquisitions = _acquisitions(work_dir, root)
        actual = [item["acquisition_id"] for item in acquisitions]
        if len(actual) != len(set(actual)) or sorted(actual) != sorted(expected):
            raise ValueError(f"{work_dir.name}: acquisition sidecars differ from work.json IDs")
        if work_dir.name in ocr:
            excluded.append(work_dir.name)
            continue
        if not acquisitions:
            without_acquisitions.append(work_dir.name)
        acquisition_count += len(acquisitions)
        for item in acquisitions:
            family_works.setdefault(item["family"], set()).add(work_dir.name)
        rows.append(
            {
                "work_id": work_dir.name,
                "work_path": work_path.relative_to(root).as_posix(),
                "work_sha256": hashlib.sha256(io_path(work_path).read_bytes()).hexdigest(),
                "acquisitions": acquisitions,
                "rights_disposition": "not-assessed",
            }
        )
    return {
        "contract": "ocd-first-publication-rights-input-index-v1",
        "scope": "Acquisition-sidecar inputs only; no rights clearance or release decision",
        "publication_work_count": len(rows),
        "ocr_excluded_work_count": len(excluded),
        "ocr_excluded_work_ids": excluded,
        "publication_works_without_acquisitions": without_acquisitions,
        "acquisition_count": acquisition_count,
        "distinct_work_counts_by_family": {
            family: len(ids) for family, ids in sorted(family_works.items())
        },
        "works": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Write the deterministic JSON index to this path.",
    )
    args = parser.parse_args()
    root = resolve_path(Path.cwd())
    result = build_index(root)
    io_path(args.output.parent).mkdir(parents=True, exist_ok=True)
    io_path(args.output).write_bytes(
        (json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    )
    print(
        json.dumps(
            {
                "publication_works": result["publication_work_count"],
                "ocr_excluded": result["ocr_excluded_work_count"],
                "publication_without_acquisitions": len(
                    result["publication_works_without_acquisitions"]
                ),
                "acquisitions": result["acquisition_count"],
                "distinct_work_counts_by_family": result["distinct_work_counts_by_family"],
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
