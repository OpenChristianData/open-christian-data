"""Remove stale NSH gap records whose recovered OCR is already keyed.

``reconcile_page_classes.py`` treats every ``gaps[]`` page_num as a gap,
regardless of status. For recovered pages that now have fully keyed OCR sidecars,
leaving a ``resolved`` gap entry behind still classifies the page as
``stale_gap_record``. The fix is to remove those gap entries entirely.

This tool removes only the known stale recovered-gap entries listed in
``STALE_GAP_PAGES``. It is idempotent: a second ``--apply`` run removes nothing.
Defaults to a dry run; pass ``--apply`` to write.

Usage:
  py -3 build/tools/reconcile_stale_gaps.py            # dry run (default)
  py -3 build/tools/reconcile_stale_gaps.py --apply
  py -3 build/tools/reconcile_stale_gaps.py --selftest
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

NSH_DIR = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"
SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "source_manifest.schema.json"

STALE_GAP_PAGES: dict[int, tuple[int, ...]] = {
    1: (94, 95),
    6: (462, 463, 464, 465, 466, 467, 468),
    10: (
        343,
        344,
        345,
        346,
        347,
        348,
        349,
        350,
        351,
        352,
        353,
        354,
        355,
        357,
        358,
        360,
        361,
        362,
        363,
        364,
        365,
        367,
    ),
}


def remove_stale_gaps(manifest: dict[str, Any], target_pages: set[int]) -> list[int]:
    """Mutate ``manifest`` in place; remove targeted stale gap entries.

    Returns the sorted page numbers removed. Non-target entries survive unchanged,
    including their order and object identity in the new ``gaps`` list.
    """
    kept: list[Any] = []
    removed: list[int] = []
    for gap in manifest.get("gaps", []):
        if isinstance(gap, dict) and isinstance(gap.get("page_num"), int):
            page_num = gap["page_num"]
            if page_num in target_pages:
                removed.append(page_num)
                continue
        kept.append(gap)
    if removed:
        manifest["gaps"] = kept
    return sorted(removed)


def _write_manifest_preserving(path: Path, manifest: dict[str, Any]) -> None:
    """Atomic write that preserves v4 manifest fields, including page_count."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _validate(manifest: dict[str, Any]) -> None:
    import jsonschema  # local import: only needed when applying

    with SCHEMA_PATH.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    jsonschema.validate(instance=manifest, schema=schema)


def run(repo_root: Path = REPO_ROOT, *, apply: bool = False) -> dict[str, Any]:
    """Remove targeted stale gaps; return a per-volume summary."""
    repo_root = Path(repo_root)
    nsh_dir = repo_root / "raw" / "internet-archive" / "schaff-herzog-pages"
    results: list[dict[str, Any]] = []
    total = 0
    for volume, pages in STALE_GAP_PAGES.items():
        manifest_path = nsh_dir / f"vol_{volume:02d}.manifest.json"
        with manifest_path.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        before_pc = manifest.get("page_count")
        removed = remove_stale_gaps(manifest, set(pages))
        total += len(removed)
        if removed and apply:
            assert manifest.get("page_count") == before_pc, "page_count must be preserved"
            _validate(manifest)
            _write_manifest_preserving(manifest_path, manifest)
        results.append({"volume": volume, "target_pages": list(pages), "removed": removed})
    return {"apply": apply, "total_removed": total, "volumes": results}


def print_report(report: dict[str, Any]) -> None:
    mode = "APPLY" if report["apply"] else "DRY-RUN"
    print(f"=== reconcile stale gaps ({mode}) ===")
    for row in report["volumes"]:
        n = len(row["removed"])
        if n:
            pages = row["removed"]
            span = f"{pages[0]}-{pages[-1]}" if len(pages) > 1 else str(pages[0])
            print(f"vol_{row['volume']:02d}: {n} removed (pages {span})")
    print(f"TOTAL removed: {report['total_removed']}")


def selftest() -> int:
    """One true-positive + true-negative, no disk."""
    ok = True

    def expect(label: str, got: Any, want: Any) -> None:
        nonlocal ok
        if got != want:
            print(f"SELFTEST FAIL: {label} -> {got!r} (want {want!r})")
            ok = False
        else:
            print(f"SELFTEST PASS: {label}")

    survivor = {"page_num": 12, "status": "resolved", "investigation_note": "not targeted"}
    manifest = {
        "page_count": 20,
        "gaps": [
            {"page_num": 10, "status": "resolved", "investigation_note": "stale"},
            survivor,
        ],
    }
    removed = remove_stale_gaps(manifest, {10})
    expect("TP 10 removed", removed, [10])
    expect("count decremented", len(manifest["gaps"]), 1)
    expect("TN 12 survives intact", manifest["gaps"][0], survivor)
    expect("idempotent second run", remove_stale_gaps(manifest, {10}), [])
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Remove stale NSH gap records.")
    parser.add_argument("--apply", action="store_true", help="Write changes (default is dry run).")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    args = parser.parse_args(argv)
    if args.selftest:
        return selftest()
    report = run(Path(args.repo_root), apply=args.apply)
    print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
