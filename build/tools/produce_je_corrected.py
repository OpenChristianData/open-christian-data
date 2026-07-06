"""Produce JE vol_02 corrected-page sidecars from a frozen WCT build.

This is the durable version of the batch-02a scratch harness:
``correct_position`` -> ``decide`` with ``prompts/je-measurement-thresholds.json``
-> ``reconcile_corrected``. It writes to a caller-supplied output directory and
can compare the result byte-for-byte with an existing committed sidecar set.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.gold_free_corrector.column_vote import correct_position  # noqa: E402
from build.lib.gold_free_corrector.decide import load_thresholds, decide  # noqa: E402
from build.lib.gold_free_corrector.reconcile_corrected import reconcile_corrected  # noqa: E402
from build.lib.s3_reconciler import DEFAULT_MATRIX_POLICY_VERSION  # noqa: E402

WCT_DIR = REPO_ROOT / "reports" / "je-wct" / "vol_02"
THRESHOLDS_PATH = REPO_ROOT / "prompts" / "je-measurement-thresholds.json"
WORK_META_PATH = (
    REPO_ROOT
    / ".shrink-quarantine"
    / "je-surrogate-phase1-20260606"
    / "reports"
    / "reconciled"
    / "je-vol-02"
    / "work_meta.json"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "reports" / "je-corrected" / "vol_02-reproduced"
CORRECTED_SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "corrected-page-v1.schema.json"
OCCURRED_AT = "2026-07-04T00:00:00Z"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _region_class(position: dict) -> str:
    zone = position.get("zone", {})
    value = zone.get("zone_type")
    return str(value) if value else "body"


def corrected_positions_for_page(wct_page: dict, thresholds: dict) -> list:
    """Return decided corrector positions for every WCT position."""
    return [
        decide(
            correct_position(position),
            thresholds,
            region_class=_region_class(position),
        )
        for position in wct_page["positions"]
    ]


def produce_page(
    *,
    wct_path: Path,
    output_dir: Path,
    work_meta: dict,
    thresholds: dict,
    schema: dict,
) -> Path:
    """Produce one corrected-page sidecar and validate it."""
    wct_page = _load_json(wct_path)
    output_path = output_dir / wct_path.name
    corrected = corrected_positions_for_page(wct_page, thresholds)
    reconcile_corrected(
        wct_page,
        work_meta,
        corrected,
        sidecar_path=output_path,
        occurred_at=OCCURRED_AT,
        wct_page_path=wct_path.relative_to(REPO_ROOT).as_posix(),
        matrix_policy_version=DEFAULT_MATRIX_POLICY_VERSION,
    )
    jsonschema.validate(instance=_load_json(output_path), schema=schema)
    return output_path


def _page_paths(wct_dir: Path, pages: list[str] | None) -> list[Path]:
    if pages:
        return [wct_dir / f"{page.removesuffix('.json')}.json" for page in pages]
    return sorted(wct_dir.glob("page_*.json"))


def _compare_dirs(produced_dir: Path, compare_dir: Path, page_paths: list[Path]) -> list[str]:
    mismatches: list[str] = []
    for wct_path in page_paths:
        name = wct_path.name
        produced = produced_dir / name
        expected = compare_dir / name
        if not expected.exists():
            mismatches.append(f"{name}: missing expected sidecar")
            continue
        if produced.read_bytes() != expected.read_bytes():
            mismatches.append(f"{name}: byte mismatch")
    return mismatches


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Produce JE vol_02 corrected-page sidecars.")
    parser.add_argument("--wct-dir", type=Path, default=WCT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--work-meta", type=Path, default=WORK_META_PATH)
    parser.add_argument("--thresholds", type=Path, default=THRESHOLDS_PATH)
    parser.add_argument("--compare-dir", type=Path)
    parser.add_argument("--page", action="append", dest="pages")
    parser.add_argument(
        "--check-existing",
        action="store_true",
        help="Write to a temporary directory and byte-compare with --compare-dir.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    page_paths = _page_paths(args.wct_dir, args.pages)
    if not page_paths:
        print(f"ERROR: no WCT pages found in {args.wct_dir}", file=sys.stderr)
        return 1
    missing = [path for path in page_paths if not path.exists()]
    if missing:
        for path in missing:
            print(f"ERROR: missing WCT page {path}", file=sys.stderr)
        return 1

    work_meta = _load_json(args.work_meta)
    thresholds = load_thresholds(args.thresholds)
    schema = _load_json(CORRECTED_SCHEMA_PATH)

    if args.check_existing:
        if args.compare_dir is None:
            print("ERROR: --check-existing requires --compare-dir", file=sys.stderr)
            return 1
        with tempfile.TemporaryDirectory(prefix="je-corrected-") as tmp:
            output_dir = Path(tmp)
            for path in page_paths:
                produce_page(
                    wct_path=path,
                    output_dir=output_dir,
                    work_meta=work_meta,
                    thresholds=thresholds,
                    schema=schema,
                )
            mismatches = _compare_dirs(output_dir, args.compare_dir, page_paths)
        if mismatches:
            for mismatch in mismatches:
                print(f"MISMATCH: {mismatch}", file=sys.stderr)
            return 1
        print(f"byte-identical corrected pages: {len(page_paths)}")
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for path in page_paths:
        produced = produce_page(
            wct_path=path,
            output_dir=args.output_dir,
            work_meta=work_meta,
            thresholds=thresholds,
            schema=schema,
        )
        print(f"wrote {produced}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
