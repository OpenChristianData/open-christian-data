"""Read-only OCR coverage inventory for the NSH pipeline."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.atomic_io import write_json_atomic  # noqa: E402
from build.lib.nsh_leaf_model import body_pages, ocr_input  # noqa: E402
from build.lib.ocr_store_paths import s1_sidecars_root, s2_renderings_root  # noqa: E402

SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "ocr-inventory-v1.schema.json"
WORK_ID = "schaff-herzog-encyclopedia"
EDITION_ID = "1908-1914"
GENERATOR = {"tool": "build/tools/ocr_pipeline/ocr_inventory.py", "version": "v1"}
LIST_CAP = 200

_LEAF_ID = re.compile(r"^leaf_0*(\d+)$")
_PAGE_ID = re.compile(r"^page_0*(\d+)$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _volume_label(volume: int) -> str:
    return f"vol_{volume:02d}"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} did not contain a JSON object")
    return data


def _repo_rel(repo_root: Path, path: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def _bounded(values: set[int]) -> tuple[list[int], bool]:
    ordered = sorted(values)
    return ordered[:LIST_CAP], len(ordered) > LIST_CAP


def resolve_present_leaf_nums(
    present_ids: list[str], page_to_leaf: dict[int, int]
) -> dict[str, Any]:
    leaf_nums: list[int] = []
    unresolved: list[str] = []
    style_counts = {"leaf": 0, "page": 0}

    for page_native_id in present_ids:
        leaf_match = _LEAF_ID.match(page_native_id)
        if leaf_match:
            leaf_nums.append(int(leaf_match.group(1)))
            style_counts["leaf"] += 1
            continue

        page_match = _PAGE_ID.match(page_native_id)
        if page_match:
            page_num = int(page_match.group(1))
            leaf_num = page_to_leaf.get(page_num)
            if leaf_num is None:
                unresolved.append(page_native_id)
            else:
                leaf_nums.append(leaf_num)
                style_counts["page"] += 1
            continue

        unresolved.append(page_native_id)

    if style_counts["leaf"] == 0 and style_counts["page"] == 0:
        key_style = "none"
    elif style_counts["leaf"] > style_counts["page"]:
        key_style = "leaf"
    elif style_counts["page"] > style_counts["leaf"]:
        key_style = "page"
    else:
        key_style = "mixed"

    return {
        "leaf_nums": sorted(leaf_nums),
        "unresolved": sorted(unresolved),
        "key_style": key_style,
    }


def compute_coverage(
    expected_body: set[int],
    present_ids: list[str],
    page_to_leaf: dict[int, int],
    failed_ids: list[str] | None = None,
) -> dict[str, Any]:
    failed_ids = failed_ids or []
    failed_resolved = resolve_present_leaf_nums(failed_ids, page_to_leaf)
    failed_leaf_nums = set(failed_resolved["leaf_nums"])
    resolved = resolve_present_leaf_nums(present_ids, page_to_leaf)
    present = set(resolved["leaf_nums"]) - failed_leaf_nums
    covered = expected_body & present
    missing = expected_body - present
    # "extra" = sidecars whose leaf number falls OUTSIDE the body range, i.e.
    # front/back-matter leaves (title page, preface, contents, editor lists).
    # It is a coarse hint, not a classifier: it does not tell you which leaves,
    # that they are leaf_*.json files, or whether they are blank. To inspect
    # them, glob leaf_*.json in the pages dir and classify with nsh_leaf_model
    # (front_matter / back_matter / image_state). See README.md "Store layout".
    extra = present - expected_body
    covered_list, covered_truncated = _bounded(covered)
    missing_list, missing_truncated = _bounded(missing)
    extra_list, extra_truncated = _bounded(extra)

    return {
        "expected": len(expected_body),
        "present": len(present),
        "covered": len(covered),
        "missing_count": len(missing),
        "extra_count": len(extra),
        "failed": len(failed_ids),
        "key_style": resolved["key_style"],
        "unresolved": sorted(set(resolved["unresolved"]) | set(failed_resolved["unresolved"])),
        "covered_leaf_nums": covered_list,
        "covered_leaf_nums_truncated": covered_truncated,
        "missing_leaf_nums": missing_list,
        "missing_leaf_nums_truncated": missing_truncated,
        "extra_leaf_nums": extra_list,
        "extra_leaf_nums_truncated": extra_truncated,
        "_covered_leaf_nums": sorted(covered),
    }


def _public_coverage(coverage: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in coverage.items() if not key.startswith("_")}


def _lineage_entry(by_lineage: dict[str, dict[str, Any]], lineage: str) -> dict[str, Any]:
    return by_lineage.setdefault(
        lineage,
        {"engine_family": "", "volumes_s1": [], "volumes_s2": []},
    )


def _record_lineage(
    by_lineage: dict[str, dict[str, Any]],
    lineage: str,
    engine_family: str,
    stage: str,
    volume: int,
) -> None:
    entry = _lineage_entry(by_lineage, lineage)
    if engine_family and not entry["engine_family"]:
        entry["engine_family"] = engine_family
    bucket = "volumes_s1" if stage == "s1" else "volumes_s2"
    if volume not in entry[bucket]:
        entry[bucket].append(volume)


def _source_denominator(repo_root: Path, volume: int) -> tuple[Path, set[int], dict[int, int]]:
    source_path = (
        repo_root
        / "raw"
        / "internet-archive"
        / "schaff-herzog-pages"
        / f"{_volume_label(volume)}.manifest.json"
    )
    source_doc = _load_json(source_path)
    expected_body = {
        int(leaf["leaf_num"])
        for leaf in ocr_input(source_doc)
        if isinstance(leaf.get("leaf_num"), int)
    }
    page_to_leaf = {
        int(leaf["page_num"]): int(leaf["leaf_num"])
        for leaf in body_pages(source_doc)
        if isinstance(leaf.get("page_num"), int) and isinstance(leaf.get("leaf_num"), int)
    }
    return source_path, expected_body, page_to_leaf


def _s1_rows(
    repo_root: Path,
    volume: int,
    expected_body: set[int],
    page_to_leaf: dict[int, int],
    by_lineage: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, set[int]]]:
    rows: list[dict[str, Any]] = []
    covered_by_lineage: dict[str, set[int]] = {}
    root = s1_sidecars_root(repo_root)
    if not root.exists():
        return rows, covered_by_lineage

    volume_name = _volume_label(volume)
    for s1_manifest_path in sorted(root.glob(f"*/{volume_name}/manifest.json")):
        s1_manifest = _load_json(s1_manifest_path)
        lineage = str(s1_manifest.get("source_lineage_id") or s1_manifest_path.parents[1].name)
        engine_family = str(s1_manifest.get("engine_family", ""))
        rendering_id = str(s1_manifest.get("rendering_id", ""))
        page_refs = list(s1_manifest.get("pages", []))
        present_ids = [
            str(page_ref.get("page_native_id"))
            for page_ref in page_refs
            if page_ref.get("page_native_id") is not None
        ]
        failed_ids = [
            str(page_ref.get("page_native_id"))
            for page_ref in page_refs
            if page_ref.get("page_native_id") is not None
            and page_ref.get("status") != "eligible"
        ]
        coverage = compute_coverage(expected_body, present_ids, page_to_leaf, failed_ids)
        covered_by_lineage[lineage] = set(coverage["_covered_leaf_nums"])
        row = {
            "stage": "s1",
            "source_lineage_id": lineage,
            "engine_family": engine_family,
            "rendering_id": rendering_id,
            **_public_coverage(coverage),
            "cell": _repo_rel(repo_root, s1_manifest_path.parent),
        }
        rows.append(row)
        _record_lineage(by_lineage, lineage, engine_family, "s1", volume)

    return rows, covered_by_lineage


def _s2_rows(
    repo_root: Path,
    volume: int,
    expected_body: set[int],
    page_to_leaf: dict[int, int],
    by_lineage: dict[str, dict[str, Any]],
    s1_covered_by_lineage: dict[str, set[int]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    root = s2_renderings_root(repo_root) / _volume_label(volume)
    if not root.exists():
        return rows

    s2_index_paths = list(root.glob("*/index.json"))
    for s2_index_path in sorted(s2_index_paths):
        s2_index = _load_json(s2_index_path)
        lineage = str(s2_index.get("source_lineage_id") or s2_index_path.parent.name)
        present_ids = [str(page_id) for page_id in s2_index.get("pages", [])]
        coverage = compute_coverage(expected_body, present_ids, page_to_leaf)
        covered_leaf_nums = set(coverage["_covered_leaf_nums"])
        s1_frontier = s1_covered_by_lineage.get(lineage, set())
        s2_lag = len(s1_frontier - covered_leaf_nums)
        engine_family = str(_lineage_entry(by_lineage, lineage).get("engine_family", ""))
        row = {
            "stage": "s2",
            "source_lineage_id": lineage,
            "engine_family": engine_family,
            "rendering_id": "",
            **_public_coverage(coverage),
            "s2_lag": s2_lag,
            "cell": _repo_rel(repo_root, s2_index_path.parent),
        }
        rows.append(row)
        _record_lineage(by_lineage, lineage, engine_family, "s2", volume)

    return rows


def _legacy_gen1_witnesses(repo_root: Path, volume: int) -> list[dict[str, Any]]:
    witnesses: list[dict[str, Any]] = []
    root = repo_root / "data" / "reference" / "schaff" / "encyclopedia" / EDITION_ID
    for path in sorted(root.glob(f"*/{_volume_label(volume)}.json")):
        witnesses.append(
            {
                "store": "legacy_gen1",
                "path": _repo_rel(repo_root, path),
                "volume": volume,
                "note": "published legacy assembled volume; recorded as witness only",
            }
        )
    return witnesses


def _legacy_azure_witnesses(repo_root: Path, volume: int) -> list[dict[str, Any]]:
    root = repo_root / "raw" / "internet-archive" / "schaff-herzog-pages" / _volume_label(volume)
    azure_files = sorted(root.glob("*.azure.json"))
    if not azure_files:
        return []
    return [
        {
            "store": "legacy_unnormalized",
            "path": _repo_rel(repo_root, root),
            "volume": volume,
            "note": f"{len(azure_files)} stray azure JSON file(s); recorded as witness only",
        }
    ]


def build_inventory(
    repo_root: Path | str = REPO_ROOT,
    volumes: list[int] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root)
    selected = volumes if volumes is not None else list(range(1, 14))
    by_lineage: dict[str, dict[str, Any]] = {}
    volume_entries: dict[str, Any] = {}
    witnesses: list[dict[str, Any]] = []
    errors: list[str] = []

    for volume in sorted(selected):
        volume_name = _volume_label(volume)
        try:
            source_path, expected_body, page_to_leaf = _source_denominator(root, volume)
        except (FileNotFoundError, json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"{volume_name}: {exc}")
            continue

        s1_cells, s1_covered_by_lineage = _s1_rows(
            root, volume, expected_body, page_to_leaf, by_lineage
        )
        s2_cells = _s2_rows(
            root, volume, expected_body, page_to_leaf, by_lineage, s1_covered_by_lineage
        )
        cells = sorted(
            s1_cells + s2_cells,
            key=lambda row: (row["stage"], row["source_lineage_id"], row["cell"]),
        )
        volume_entries[volume_name] = {
            "denominator": {
                "expected_ocr_body_leaves": len(expected_body),
                "source_manifest": _repo_rel(root, source_path),
            },
            "cells": cells,
            "stage_summary": {
                "s1": {
                    "lineages_present": len(
                        {cell["source_lineage_id"] for cell in cells if cell["stage"] == "s1"}
                    )
                },
                "s2": {
                    "lineages_present": len(
                        {cell["source_lineage_id"] for cell in cells if cell["stage"] == "s2"}
                    )
                },
            },
        }
        witnesses.extend(_legacy_gen1_witnesses(root, volume))
        witnesses.extend(_legacy_azure_witnesses(root, volume))

    by_lineage_sorted = {
        lineage: {
            "engine_family": entry["engine_family"],
            "volumes_s1": sorted(entry["volumes_s1"]),
            "volumes_s2": sorted(entry["volumes_s2"]),
        }
        for lineage, entry in sorted(by_lineage.items())
    }

    index = {
        "schema_version": "ocr-inventory-v1",
        "generated_at": generated_at or _utc_now(),
        "generator": dict(GENERATOR),
        "work_id": WORK_ID,
        "edition_id": EDITION_ID,
        "volumes": dict(sorted(volume_entries.items())),
        "by_lineage": by_lineage_sorted,
        "witnesses": sorted(witnesses, key=lambda row: (row["store"], row["volume"], row["path"])),
    }
    if errors:
        index["errors"] = errors
    return index


def _parse_volumes(raw: str) -> list[int]:
    if "-" in raw:
        start, end = raw.split("-", 1)
        return list(range(int(start), int(end) + 1))
    return [int(part) for part in raw.split(",") if part]


def _load_schema() -> dict[str, Any]:
    return _load_json(SCHEMA_PATH)


def _print_build_summary(index: dict[str, Any], output: Path) -> None:
    volume_count = len(index["volumes"])
    cell_count = sum(len(volume["cells"]) for volume in index["volumes"].values())
    witness_count = len(index["witnesses"])
    print(f"wrote {output.as_posix()}")
    print(f"volumes={volume_count} cells={cell_count} witnesses={witness_count}")
    if index.get("errors"):
        print(f"errors={len(index['errors'])}")


def _cell_status(cell: dict[str, Any]) -> str:
    parts = [
        f"{cell['covered']}/{cell['expected']}",
        f"extra={cell['extra_count']}",
        f"missing={cell['missing_count']}",
    ]
    if cell["stage"] == "s2":
        parts.append(f"s2_lag={cell.get('s2_lag', 0)}")
    if cell["failed"]:
        parts.append(f"failed={cell['failed']}")
    return " ".join(parts)


def print_status(index: dict[str, Any], volume: int | None = None, lineage: str | None = None) -> None:
    rows: list[tuple[str, str, str, str]] = []
    for volume_name, volume_entry in index["volumes"].items():
        if volume is not None and volume_name != _volume_label(volume):
            continue
        for cell in volume_entry["cells"]:
            if lineage is not None and cell["source_lineage_id"] != lineage:
                continue
            rows.append(
                (
                    volume_name,
                    cell["source_lineage_id"],
                    cell["stage"],
                    _cell_status(cell),
                )
            )

    header = ("volume", "lineage", "stage", "coverage")
    widths = [
        max([len(header[0])] + [len(row[0]) for row in rows]),
        max([len(header[1])] + [len(row[1]) for row in rows]),
        max([len(header[2])] + [len(row[2]) for row in rows]),
        max([len(header[3])] + [len(row[3]) for row in rows]),
    ]
    fmt = "  ".join(f"{{:<{width}}}" for width in widths)
    print(fmt.format(*header))
    print(fmt.format(*("-" * width for width in widths)))
    for row in rows:
        print(fmt.format(*row))
    print(
        "legend: extra = front/back-matter leaves beyond the current body denominator -- "
        "OCR-eligible later (migration target), not terminal."
    )


def _build_command(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root)
    output = repo_root / args.output
    index = build_inventory(repo_root, volumes=_parse_volumes(args.volumes))
    write_json_atomic(output, index, _load_schema())
    _print_build_summary(index, output)
    return 0


def _status_command(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root)
    index = build_inventory(repo_root, volumes=_parse_volumes(args.volumes))
    volume = int(args.volume) if args.volume is not None else None
    print_status(index, volume=volume, lineage=args.lineage)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or print NSH OCR inventory.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--repo-root", default=".")
    build_parser.add_argument("--volumes", default="1-13")
    build_parser.add_argument("--output", default="reports/ocr-inventory/index.json")
    build_parser.set_defaults(func=_build_command)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--repo-root", default=".")
    status_parser.add_argument("--volumes", default="1-13")
    status_parser.add_argument("--volume")
    status_parser.add_argument("--lineage")
    status_parser.set_defaults(func=_status_command)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
