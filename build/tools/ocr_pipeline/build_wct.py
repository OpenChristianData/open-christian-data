"""S2.5 stage entry point: build one word-confusion-table-v1 page (batch B6).

Reads the per-engine rendering-v1 records for a single page image and emits one
word-confusion-table-v1 page via build.lib.wct_builder. Fail-closed: the output
must pass BOTH the JSON schema (enforced by write_json_atomic) AND the
segmentation-invariant semantic validator (build.lib.wct_semantic_validator)
before anything is written to disk.

The alignment design lives in plans/2026-05-28-archA-alignment-reconciled-design.md
(THE WCT contract). This tool is the un-tuned builder; tuning is gated by the B8
first-diagnostics verdict.

Usage:
    py -3 build/tools/ocr_pipeline/build_wct.py \
        --rendering path/to/rendering_surya.json \
        --rendering path/to/rendering_tesseract.json \
        --source-image-path raw/internet-archive/schaff-herzog-pages/vol_01/page_0010.jpg \
        --source-image-sha256 <64 hex> \
        --output reports/wct/vol_01/page_0010.json

Exactly one rendering must carry engine_family "surya" (the layout authority).
work_id / volume_id / page_id default from the first rendering and may be
overridden. Relative paths only in committed output (identity-leak guardrail).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.atomic_io import write_json_atomic  # noqa: E402
from build.lib.wct_builder import build_wct_page  # noqa: E402
from build.lib.wct_semantic_validator import validate_page  # noqa: E402

SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "word-confusion-table-v1.schema.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def derive_canonical_leaf_id(renderings: list[dict]) -> int | None:
    """The page-level cross-engine join key for one WCT page (R4b).

    The key is the primary-scan leaf coordinate (canonical_leaf_id), NOT the
    filename stem -- the stem join silently mis-aligned an engine OCR'd before a
    rename with one OCR'd after it. Every engine rendering that carries
    canonical_leaf_id must agree; a disagreement is exactly that mis-alignment and
    fails closed here. Renderings that carry NO canonical_leaf_id are exempt
    (non-NSH sources such as JE never carry a leaf) and fall back to the filename
    join. Single source of truth: build_from_files AND the WCT clid-stamp tool
    (rebuild_wct_clid) both derive the key through this function.
    """
    leaf_ids = {
        r["pages"][0]["canonical_leaf_id"]
        for r in renderings
        if r["pages"][0].get("canonical_leaf_id") is not None
    }
    if len(leaf_ids) > 1:
        raise ValueError(
            "cross-engine join failed: renderings disagree on canonical_leaf_id "
            f"{sorted(leaf_ids)} (filenames "
            f"{[r['pages'][0].get('page_native_id') for r in renderings]}) -- one engine "
            "was OCR'd against a different leaf for this stem"
        )
    return next(iter(leaf_ids)) if leaf_ids else None


def derive_edition_page_key(renderings: list[dict]) -> dict | None:
    """Derive the scan-independent edition page key for one WCT page.

    Every rendering that carries ``edition_page_key`` must agree. A disagreement
    means two engines stamped different edition pages for the same WCT join, so
    fail closed just like the canonical leaf check.
    """
    keys = [
        dict(page_key)
        for r in renderings
        if (page_key := r["pages"][0].get("edition_page_key")) is not None
    ]
    if not keys:
        return None
    first = keys[0]
    if any(key != first for key in keys[1:]):
        raise ValueError(
            "cross-engine join failed: renderings disagree on edition_page_key "
            f"{keys} (filenames "
            f"{[r['pages'][0].get('page_native_id') for r in renderings]}) -- one engine "
            "was OCR'd against a different edition page for this stem"
        )
    return first


def build_from_files(
    rendering_paths: list[Path],
    *,
    source_image: dict,
    work_id: str | None = None,
    volume_id: str | None = None,
    page_id: str | None = None,
) -> dict:
    """Build and fail-closed-validate one WCT page from rendering-v1 files."""
    if not rendering_paths:
        raise ValueError("no rendering files supplied")
    renderings = [_load(p) for p in rendering_paths]
    return build_from_renderings(
        renderings,
        source_image=source_image,
        work_id=work_id,
        volume_id=volume_id,
        page_id=page_id,
    )


def build_from_renderings(
    renderings: list[dict],
    *,
    source_image: dict,
    work_id: str | None = None,
    volume_id: str | None = None,
    page_id: str | None = None,
) -> dict:
    """Build and fail-closed-validate one WCT page from loaded rendering-v1 records."""
    if not renderings:
        raise ValueError("no renderings supplied")
    first = renderings[0]
    work_id = work_id or first["work_id"]
    volume_id = volume_id or f"vol_{int(first['volume']):02d}"
    page_id = page_id or first["pages"][0]["page_native_id"]
    canonical_leaf_id = derive_canonical_leaf_id(renderings)
    edition_page_key = derive_edition_page_key(renderings)

    page = build_wct_page(
        renderings,
        work_id=work_id,
        volume_id=volume_id,
        page_id=page_id,
        canonical_leaf_id=canonical_leaf_id,
        edition_page_key=edition_page_key,
        source_image=source_image,
    )

    # Fail-closed on the segmentation invariant before any disk write. JSON schema
    # validation happens inside write_json_atomic; this covers what schema cannot.
    semantic_errors = validate_page(page)
    if semantic_errors:
        raise ValueError(
            "WCT page failed semantic validation (segmentation invariant):\n  "
            + "\n  ".join(semantic_errors)
        )
    return page


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build one word-confusion-table-v1 page from per-engine rendering-v1 records."
    )
    parser.add_argument(
        "--rendering", dest="renderings", action="append", type=Path, required=True,
        help="A rendering-v1 JSON file (repeat per engine; one must be surya).",
    )
    parser.add_argument("--source-image-path", required=True,
                        help="Repo-root-relative path to the source page image.")
    parser.add_argument("--source-image-sha256", required=True,
                        help="64-hex sha256 of the source page image.")
    parser.add_argument("--work-id", default=None)
    parser.add_argument("--volume-id", default=None)
    parser.add_argument("--page-id", default=None)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    source_image = {"path": args.source_image_path, "sha256": args.source_image_sha256}
    page = build_from_files(
        args.renderings,
        source_image=source_image,
        work_id=args.work_id,
        volume_id=args.volume_id,
        page_id=args.page_id,
    )
    schema = _load(SCHEMA_PATH)
    write_json_atomic(args.output, page, schema)
    print(
        f"wrote {args.output} -- {len(page['positions'])} positions, "
        f"{len(page['available_engines'])} engines, "
        f"{len(page['reading_order'])} in reading order"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
