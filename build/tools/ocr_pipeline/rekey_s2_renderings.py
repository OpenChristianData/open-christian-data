"""R-final.1 -- re-key an abbyy/azure S2 cell so its per-page renderings carry
canonical_leaf_id, with the least compute and zero re-OCR.

Mechanism: the S1 manifest now carries canonical_leaf_id on every body page_ref
(R7). render_s2._render_page already reads that leaf from the page_ref and stamps
it onto the rendered page, reseeding rendering_line_id/rendering_block_id off the
leaf. So "re-key" is just render_s2 run against the current leaf-keyed manifest --
no OCR engine runs, no NLP is re-derived from scratch beyond render_s2's own cheap
per-page pass (~20 ms/page). The one expensive part of a render, the rendering-v1
jsonschema re-validation (~0.7 s/page), is skipped via validate_schema=False: it is
a read-only gate that cannot change output bytes, and render_manifest(validate_schema
=False) is proven byte-identical to the validated render (see tests). The cells were
already schema-validated when first produced; byte identity vs a fresh validated
render is proven on a real cell before bulk use.

verify_cell_clid is the fail-closed completeness gate (mirrors
verify_leaf_keying._verify_s2_cell): every S1 body leaf (page_ref carrying
canonical_leaf_id) must have a rendered page carrying that exact leaf. Non-body /
exempt page_refs that carry no clid are not failures.

CLI:
    py -3 build/tools/ocr_pipeline/rekey_s2_renderings.py \
        reports/s1-sidecars/ia-abbyy-v1/vol_01/manifest.json \
        --output-dir reports/s2-renderings/vol_01/ia-abbyy-v1
Exits non-zero when a body leaf is missing/mismatched in the rendered output.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from build.lib.paths import REPO_ROOT
from build.tools.ocr_pipeline.render_s2 import render_manifest

# clid lives on the rendered page record (doc["pages"][i]), never the envelope top
# level -- reading the envelope would always see None (VER-01, NSH leaf-rekey note).


def _eligible_refs(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        ref
        for ref in manifest.get("pages", [])
        if ref.get("status") in {"eligible", "diagnostic_only"}
    ]


def verify_cell_clid(pages_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Fail-closed: every S1 body leaf must have a rendered page carrying that leaf.

    Returns counts plus ok=True only when no body leaf is missing or mismatched.
    page_refs with no canonical_leaf_id are non-body / exempt and are not checked.
    """
    pages_dir = Path(pages_dir)
    body_with = 0
    body_missing = 0
    mismatches: list[str] = []

    for ref in _eligible_refs(manifest):
        leaf = ref.get("canonical_leaf_id")
        if leaf is None:
            continue  # non-body / exempt -- legitimately carries no clid
        native = ref["page_native_id"]
        page_file = pages_dir / f"{native}.rendering-v1.json"
        if not page_file.exists():
            body_missing += 1
            mismatches.append(f"{native}: body leaf {leaf} not rendered")
            continue
        doc = json.loads(page_file.read_text(encoding="utf-8"))
        rendered_pages = doc.get("pages") or []
        rendered = rendered_pages[0] if rendered_pages else {}
        cli = rendered.get("canonical_leaf_id")
        if cli == leaf:
            body_with += 1
        else:
            body_missing += 1
            mismatches.append(f"{native}: render clid={cli!r} != S1 leaf {leaf}")

    return {
        "body_pages_with_clid": body_with,
        "body_pages_missing_clid": body_missing,
        "mismatches": mismatches,
        "ok": body_missing == 0,
    }


def rekey_cell(
    manifest_path: Path | str,
    *,
    repo_root: Path | str = REPO_ROOT,
    output_dir: Path | str | None = None,
    allow_stale_manifest: bool = False,
) -> dict[str, Any]:
    """Re-key one cell: render against the leaf-keyed S1 manifest (no schema
    re-validation), then verify every body leaf carries its clid.

    allow_stale_manifest=True renders per the manifest's authority when the manifest
    lags its on-disk sidecars -- the non-mutating path (render_s2 quarantines the
    extra renderings; the S1 manifest is never rewritten/reindexed here)."""
    manifest_path = Path(manifest_path)
    repo_root = Path(repo_root)
    out = Path(output_dir) if output_dir is not None else manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    result = render_manifest(
        manifest_path,
        repo_root=repo_root,
        output_dir=out,
        force=True,
        validate_schema=False,
        allow_stale_manifest=allow_stale_manifest,
    )
    report = verify_cell_clid(out / "pages", manifest)
    report["written"] = result["written"]
    report["skipped"] = result["skipped"]
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Re-key an abbyy/azure S2 cell so per-page renderings carry canonical_leaf_id."
    )
    parser.add_argument("manifest_path", type=Path, help="S1 sidecar manifest.json for the cell.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="S2 cell dir (default: manifest parent). Renderings land under <dir>/pages/.",
    )
    parser.add_argument(
        "--allow-stale-manifest",
        action="store_true",
        default=False,
        help="Render per the manifest when it lags on-disk sidecars (non-mutating; never reindexes S1).",
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    report = rekey_cell(
        args.manifest_path,
        repo_root=args.repo_root,
        output_dir=args.output_dir,
        allow_stale_manifest=args.allow_stale_manifest,
    )
    print(
        f"re-keyed {args.manifest_path}: written={report['written']} "
        f"body_clid={report['body_pages_with_clid']} "
        f"missing={report['body_pages_missing_clid']} ok={report['ok']}"
    )
    if not report["ok"]:
        for m in report["mismatches"][:20]:
            print(f"  MISMATCH {m}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
