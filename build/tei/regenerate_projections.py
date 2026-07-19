"""Regenerate TEI projections and their loss receipts, family by family.

Design section 6 requires a staged rollout: regenerate one family at a time and
run the strict v2 checker immediately after each, rather than regenerating the
whole corpus and inspecting the wreckage afterwards.

Each existing receipt carries the repo-relative IR and output paths it was built
from, so the set of projections is discovered from the committed receipts rather
than from a hand-maintained list that could silently drift out of date.

Usage (from the repo root):

    py -3 -m build.tei.regenerate_projections --list
    py -3 -m build.tei.regenerate_projections --family bcp
    py -3 -m build.tei.regenerate_projections --all
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from build.lib.paths import REPO_ROOT
from build.tei.check_ledger_v2 import check_receipt_v2
from build.tei.project_hf import project_file

IR_DIR = REPO_ROOT / "ir"


@dataclass(frozen=True)
class Projection:
    family: str
    receipt_path: Path
    ir_path: Path
    output_path: Path


def discover(repo_root: Path = REPO_ROOT) -> list[Projection]:
    """Read every committed receipt to learn which projections exist."""

    projections: list[Projection] = []
    for receipt_path in sorted((repo_root / "ir").rglob("*.loss.json")):
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        projections.append(
            Projection(
                family=receipt_path.relative_to(repo_root / "ir").parts[0],
                receipt_path=receipt_path,
                ir_path=repo_root / receipt["ir"]["path"],
                output_path=repo_root / receipt["output"]["path"],
            )
        )
    return projections


def regenerate(projection: Projection, *, repo_root: Path = REPO_ROOT) -> list[str]:
    """Regenerate one projection and return the strict checker's errors."""

    if not projection.ir_path.is_file():
        raise FileNotFoundError(f"IR is missing: {projection.ir_path}")
    project_file(
        projection.ir_path,
        projection.output_path,
        receipt_path=projection.receipt_path,
        repo_root=repo_root,
    )
    return check_receipt_v2(projection.receipt_path, repo_root=repo_root)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--family", help="regenerate one family (e.g. bcp)")
    group.add_argument("--all", action="store_true", help="regenerate every family")
    group.add_argument("--list", action="store_true", help="list families and exit")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    projections = discover()
    if not projections:
        print("No receipts found under ir/ -- nothing to regenerate.")
        return 1

    if args.list:
        for family in sorted({item.family for item in projections}):
            count = sum(1 for item in projections if item.family == family)
            print(f"{family:<12} {count} projection(s)")
        print(f"total: {len(projections)} projection(s)")
        return 0

    selected = (
        projections
        if args.all
        else [item for item in projections if item.family == args.family]
    )
    if not selected:
        print(f"No projections for family {args.family!r}.")
        return 1

    failures = 0
    for index, projection in enumerate(selected, 1):
        relative = projection.receipt_path.relative_to(REPO_ROOT).as_posix()
        print(f"[{index}/{len(selected)}] {relative}")
        errors = regenerate(projection)
        if errors:
            failures += 1
            print(f"  FAIL ({len(errors)} error(s)); first 10:")
            for error in errors[:10]:
                print(f"    - {error}")
        else:
            print("  PASS (strict v2)")

    print(f"\nSummary: {len(selected) - failures} passed, {failures} failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
