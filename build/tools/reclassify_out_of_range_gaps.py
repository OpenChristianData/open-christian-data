"""Reclassify phantom out-of-range NSH gap records (status unresolved -> out_of_range).

An earlier fetch pass (``record_unresolved_gaps`` in ``fetch_ia_pages.py``) was fed
a requested page range that ran to each volume's physical LEAF count instead of
its printed PAGE count, recording ``unresolved`` gap entries for page numbers past
the end of the book (e.g. vol_03 pages 501-531, where the body ends at 500 and the
trailing leaves are unnumbered front/back matter). Those entries are not missing
pages -- they are page numbers that never existed.

ABBYY coverage (``coverage.ia-abbyy.json`` -> ``pages_parsed``) is the independent
true printed-page count (PIPE-29). This tool reclassifies the phantom entries to
the documented status ``out_of_range`` -- preserving the record (and its original
note) rather than deleting it, so the audit trail of "this number was requested and
confirmed non-existent" stays in the manifest. Real gaps are never touched: only
``status == "unresolved"`` entries whose ``page_num`` exceeds the volume's true
page count are reclassified; ``resolved`` / ``permanently_missing`` / any in-range
``unresolved`` (a genuinely missing real page) are left exactly as they are.

Idempotent: a second run reclassifies nothing (the entries are already
``out_of_range``). Defaults to a dry run; pass ``--apply`` to write.

Usage:
  py -3 build/tools/reclassify_out_of_range_gaps.py            # dry run (default)
  py -3 build/tools/reclassify_out_of_range_gaps.py --apply
  py -3 build/tools/reclassify_out_of_range_gaps.py --selftest
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

OUT_OF_RANGE = "out_of_range"
_RECLASSIFY_NOTE = (
    "out_of_range: page {pn} exceeds the volume's true printed-page count {tpc} "
    "(ABBYY pages_parsed) -- a non-page recorded by an over-broad requested range, "
    "not a missing page."
)


def coverage_pages_parsed(repo_root: Path, volume: int) -> int | None:
    """The volume's true printed-page count from ABBYY coverage, or None.

    ``pages_parsed`` in ``coverage.ia-abbyy.json`` is the count of numbered body
    pages the independent ABBYY scan parsed -- the authoritative book length.
    """
    path = Path(repo_root) / "raw" / "internet-archive" / "schaff-herzog-pages" \
        / f"vol_{volume:02d}" / "coverage.ia-abbyy.json"
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    parsed = data.get("pages_parsed")
    return parsed if isinstance(parsed, int) else None


def reclassify_gaps(manifest: dict[str, Any], true_page_count: int) -> list[int]:
    """Mutate ``manifest`` in place; reclassify phantom out-of-range gaps.

    A gap is phantom when ``status == "unresolved"`` AND ``page_num`` exceeds the
    volume's true printed-page count. Returns the sorted page numbers reclassified.
    """
    changed: list[int] = []
    for gap in manifest.get("gaps", []):
        if not isinstance(gap, dict):
            continue
        page_num = gap.get("page_num")
        if (
            gap.get("status") == "unresolved"
            and isinstance(page_num, int)
            and page_num > true_page_count
        ):
            original = gap.get("investigation_note", "")
            reason = _RECLASSIFY_NOTE.format(pn=page_num, tpc=true_page_count)
            gap["status"] = OUT_OF_RANGE
            gap["investigation_note"] = f"{reason} (was: {original})" if original else reason
            changed.append(page_num)
    return sorted(changed)


def _write_manifest_preserving(path: Path, manifest: dict[str, Any]) -> None:
    """Atomic write (OUT-02) that preserves every field, including page_count.

    Does not route through ``fetch_ia_pages.write_manifest_atomic`` because
    reclassify validates separately (see ``_validate`` below) and we avoid the
    extra recompute + re-validation pass that ``write_manifest_atomic`` performs.
    (``_compute_page_count`` in fetch_ia_pages now handles v4 leaves manifests;
    the original page_count-zeroing hazard that motivated this helper is fixed.)
    """
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _validate(manifest: dict[str, Any]) -> None:
    import jsonschema  # local import: only needed when applying

    with SCHEMA_PATH.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    jsonschema.validate(instance=manifest, schema=schema)


def run(repo_root: Path = REPO_ROOT, *, apply: bool = False) -> dict[str, Any]:
    """Reclassify every NSH volume; return a per-volume summary."""
    repo_root = Path(repo_root)
    nsh_dir = repo_root / "raw" / "internet-archive" / "schaff-herzog-pages"
    results: list[dict[str, Any]] = []
    total = 0
    for volume in range(1, 14):
        manifest_path = nsh_dir / f"vol_{volume:02d}.manifest.json"
        if not manifest_path.exists():
            continue
        with manifest_path.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        true_count = coverage_pages_parsed(repo_root, volume)
        if true_count is None:
            # No independent page count -> cannot prove any gap is out-of-range; skip.
            results.append({"volume": volume, "reclassified": [], "skipped_no_coverage": True})
            continue
        before_pc = manifest.get("page_count")
        changed = reclassify_gaps(manifest, true_count)
        total += len(changed)
        if changed and apply:
            assert manifest.get("page_count") == before_pc, "page_count must be preserved"
            _validate(manifest)
            _write_manifest_preserving(manifest_path, manifest)
        results.append({"volume": volume, "true_page_count": true_count, "reclassified": changed})
    return {"apply": apply, "total_reclassified": total, "volumes": results}


def print_report(report: dict[str, Any]) -> None:
    mode = "APPLY" if report["apply"] else "DRY-RUN"
    print(f"=== reclassify out-of-range gaps ({mode}) ===")
    for row in report["volumes"]:
        if row.get("skipped_no_coverage"):
            print(f"vol_{row['volume']:02d}: SKIPPED (no ABBYY coverage)")
            continue
        n = len(row["reclassified"])
        if n:
            pages = row["reclassified"]
            span = f"{pages[0]}-{pages[-1]}" if len(pages) > 1 else str(pages[0])
            print(f"vol_{row['volume']:02d}: {n} reclassified (true_page_count={row['true_page_count']}, pages {span})")
    print(f"TOTAL reclassified: {report['total_reclassified']}")


def selftest() -> int:
    """One true-positive + true-negative per rule, no disk."""
    ok = True

    def expect(label: str, got: Any, want: Any) -> None:
        nonlocal ok
        if got != want:
            print(f"SELFTEST FAIL: {label} -> {got!r} (want {want!r})")
            ok = False
        else:
            print(f"SELFTEST PASS: {label}")

    manifest = {
        "page_count": 500,
        "gaps": [
            {"page_num": 96, "status": "resolved", "investigation_note": "x"},
            {"page_num": 209, "status": "permanently_missing", "investigation_note": "real, image absent"},
            {"page_num": 480, "status": "unresolved", "investigation_note": "in-range real hole"},
            {"page_num": 501, "status": "unresolved", "investigation_note": "no leaf mapping"},
            {"page_num": 531, "status": "unresolved", "investigation_note": "no leaf mapping"},
        ],
    }
    changed = reclassify_gaps(manifest, 500)
    expect("only out-of-range unresolved reclassified", changed, [501, 531])
    statuses = {g["page_num"]: g["status"] for g in manifest["gaps"]}
    expect("TP 501 -> out_of_range", statuses[501], OUT_OF_RANGE)
    expect("TP 531 -> out_of_range", statuses[531], OUT_OF_RANGE)
    expect("TN resolved untouched", statuses[96], "resolved")
    expect("TN permanently_missing untouched", statuses[209], "permanently_missing")
    expect("TN in-range unresolved untouched", statuses[480], "unresolved")
    expect("note preserves original", "was:" in manifest["gaps"][3]["investigation_note"], True)
    expect("idempotent second run", reclassify_gaps(manifest, 500), [])
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reclassify phantom out-of-range NSH gap records.")
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
