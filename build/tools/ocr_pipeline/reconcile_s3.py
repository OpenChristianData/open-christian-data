"""S3 stage entry point: reconcile one WCT page in degraded mode (batch B10).

Reads one word-confusion-table-v1 page (B6 / S2.5 output) plus a work-meta envelope
and writes a reconciled_record (validated against the frozen schema by
write_json_atomic) plus two sidecars next to it:
  <stem>.matrix_candidates.json -- matrix-event candidates (matrix-events-v1)
  <stem>.reviewer_queue.json    -- routed positions for the single reviewer

Fail-closed: the reconciled_record must pass the JSON schema before anything lands on
disk. Degraded mode emits no trained matrix labels (lock section 3). The reconciler
design lives in plans/2026-05-28-arch5-reconciler-synthesis.md and the archC lock
(section 2 layer boundary, section 6 item 23 region_class policy). S3 scoring-threshold
tuning is gated by the B8 diagnostics verdict (phase 2); this is the un-tuned builder.

Usage:
    py -3 build/tools/ocr_pipeline/reconcile_s3.py \
        --wct reports/wct/vol_01/page_0010.json \
        --work-meta data/schaff-herzog/vol_01/work_meta.json \
        --output reports/reconciled/vol_01/page_0010.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.atomic_io import write_json_atomic  # noqa: E402
from build.lib.s3_reconciler import reconcile_degraded  # noqa: E402

SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "reconciled_record.schema.json"
MATRIX_EVENTS_SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "matrix-events-v1.schema.json"
OBJECT_SCHEMA = {"type": "object"}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _now_iso() -> str:
    return datetime.now(ZoneInfo("Australia/Melbourne")).isoformat()


def reconcile_page_inline(
    wct_page: dict,
    work_meta: dict,
    output_path: Path,
    occurred_at: str,
    *,
    _schema: dict | None = None,
    _matrix_schema: dict | None = None,
) -> None:
    """Run S3 reconciliation in-process; mirrors main() but accepts dicts directly.

    This avoids spawning a child Python process per page. The caller must supply
    occurred_at (a pre-generated ISO-8601 string) because ZoneInfo may be
    unavailable in worker processes.

    _schema and _matrix_schema are optional pre-loaded schema dicts. When supplied
    (e.g. from a worker initializer) the function skips the per-call disk reads.
    Pass None to fall back to loading from disk -- the standalone-call behaviour.
    """
    result = reconcile_degraded(wct_page, work_meta, occurred_at=occurred_at)

    schema = _schema if _schema is not None else _load(SCHEMA_PATH)
    write_json_atomic(output_path, result.reconciled_record, schema)

    matrix_schema = _matrix_schema if _matrix_schema is not None else _load(MATRIX_EVENTS_SCHEMA_PATH)
    matrix_validator = jsonschema.Draft202012Validator(matrix_schema)
    for candidate in result.matrix_event_candidates:
        errors = list(matrix_validator.iter_errors(candidate))
        if errors:
            raise ValueError(
                f"matrix-event candidate failed schema validation: {errors[0].message}"
            )

    stem = output_path.stem
    write_json_atomic(
        output_path.parent / f"{stem}.matrix_candidates.json",
        {"candidates": result.matrix_event_candidates},
        OBJECT_SCHEMA,
    )
    write_json_atomic(
        output_path.parent / f"{stem}.reviewer_queue.json",
        {"queue": result.reviewer_queue},
        OBJECT_SCHEMA,
    )

    print(
        f"wrote {output_path} -- {len(result.reconciled_record['blocks'])} blocks, "
        f"{len(result.matrix_event_candidates)} matrix candidates, "
        f"{len(result.reviewer_queue)} reviewer-queue items",
        flush=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reconcile one WCT page in degraded mode into a reconciled_record."
    )
    parser.add_argument("--wct", type=Path, required=True, help="word-confusion-table-v1 page JSON.")
    parser.add_argument("--work-meta", type=Path, required=True, help="reconciled_record envelope JSON.")
    parser.add_argument("--output", type=Path, required=True, help="reconciled_record output path.")
    parser.add_argument("--occurred-at", default=None,
                        help="ISO-8601 timestamp for matrix-event candidates (default: now).")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    wct_page = _load(args.wct)
    work_meta = _load(args.work_meta)
    occurred_at = args.occurred_at or _now_iso()

    result = reconcile_degraded(wct_page, work_meta, occurred_at=occurred_at)

    schema = _load(SCHEMA_PATH)
    # Fail-closed: schema validation happens inside write_json_atomic before any write.
    write_json_atomic(args.output, result.reconciled_record, schema)

    # Fail-closed on the matrix sidecar too: every candidate must validate against
    # matrix-events-v1 before it lands, so a future library regression cannot leak a
    # malformed candidate to disk (Codex B10 review hardening finding, 2026-05-30).
    matrix_schema = _load(MATRIX_EVENTS_SCHEMA_PATH)
    matrix_validator = jsonschema.Draft202012Validator(matrix_schema)
    for candidate in result.matrix_event_candidates:
        errors = list(matrix_validator.iter_errors(candidate))
        if errors:
            raise ValueError(f"matrix-event candidate failed schema validation: {errors[0].message}")

    stem = args.output.stem
    write_json_atomic(
        args.output.parent / f"{stem}.matrix_candidates.json",
        {"candidates": result.matrix_event_candidates},
        OBJECT_SCHEMA,
    )
    write_json_atomic(
        args.output.parent / f"{stem}.reviewer_queue.json",
        {"queue": result.reviewer_queue},
        OBJECT_SCHEMA,
    )

    print(
        f"wrote {args.output} -- {len(result.reconciled_record['blocks'])} blocks, "
        f"{len(result.matrix_event_candidates)} matrix candidates, "
        f"{len(result.reviewer_queue)} reviewer-queue items"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
