"""Build word-confusion-table-v1 pages for the JE surrogate oracle sample.

Reads quarantined per-page rendering-v1 files (post-R4 layout,
output_dir/pages/*.rendering-v1.json) for each available engine, stamps the JE
edition page key in memory, and calls the current WCT builder to produce one WCT
page per frozen 02a sample page. Outputs to reports/je-wct/vol_02-r2/page_NNNN.json.

JE is a measurement oracle only -- never published, never in data/.

Usage:
    py -3 build/tools/build_je_wct_batch.py [--force]

    --force / -f   Re-build pages that already exist on disk.

All 34 frozen-evidence sample pages are attempted by default. Per-page errors are logged and counted;
the script exits 1 if any page failed.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.atomic_io import write_json_atomic  # noqa: E402
from build.lib.edition_page_key import body_edition_key  # noqa: E402
from build.lib.wct_builder import LayoutEscalation  # noqa: E402
from build.lib.wct_semantic_validator import validate_page  # noqa: E402
from build.tools.ocr_pipeline.build_wct import build_from_renderings  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WORK_ID = "jewish-encyclopedia.vol_02"
VOLUME_ID = "vol_02"

# Engines in priority order. All available engines are used; missing pages
# for individual engines are skipped with a warning (not a hard failure).
ENGINES = [
    "ia-abbyy-v1",
    "tesseract-py314-v1",
    "kraken-py312-v1",
    "kraken-greek-py312-v1",
    "azure-ai-vision-v1",
]

QUARANTINE_REPORTS = REPO_ROOT / ".shrink-quarantine" / "je-surrogate-phase1-20260606" / "reports"
S2_ROOT = QUARANTINE_REPORTS / "je-s2-renderings" / VOLUME_ID
IA_MANIFEST_PATH = REPO_ROOT / "raw" / "jewish-encyclopedia" / "ia-pages" / "vol_02.manifest.json"
FROZEN_WCT_DIR = REPO_ROOT / "reports" / "je-wct" / VOLUME_ID
WCT_OUTPUT_DIR = REPO_ROOT / "reports" / "je-wct" / "vol_02-r2"
WCT_SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "word-confusion-table-v1.schema.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_ia_manifest(path: Path) -> dict[str, dict]:
    """Load the IA pages manifest and return a page_id -> page_info dict.

    Keys are formatted as page_NNNN (zero-padded page_num).
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {f"page_{p['page_num']:04d}": p for p in raw["pages"]}


def _source_image(page_info: dict) -> dict:
    """Build the source_image dict for build_wct_page from an IA page manifest entry.

    Strips the leading 'sha256:' prefix from the stored hash value (OUT-03:
    the path is already repo-root-relative in the manifest).
    """
    sha256 = page_info["sha256"]
    if sha256.startswith("sha256:"):
        sha256 = sha256[7:]
    return {"path": page_info["local_path"], "sha256": sha256}


def _load_rendering(path: Path, page_num: int) -> dict:
    """Load one rendering and stamp JE's body edition key without mutating evidence."""
    rendering = json.loads(path.read_text(encoding="utf-8"))
    page = rendering["pages"][0]
    page["edition_page_key"] = body_edition_key(page_num)
    # JE vol_02 is a body-page oracle panel, not an NSH primary-scan lineage.
    # For current WCT schema compatibility we use the edition page number as the
    # canonical leaf coordinate; this keeps all 34 body pages non-exempt while
    # preserving the image SHA/path as the replay anchor.
    page["canonical_leaf_id"] = page_num
    return rendering


def _collect_page_rendering_paths(
    page_id: str,
    s2_root: Path,
    engines: list[str],
) -> dict[str, Path]:
    """Return {engine: path} for engines that have a per-page rendering file.

    Post-R4 layout: s2_root/{engine}/pages/{page_id}.rendering-v1.json
    """
    result: dict[str, Path] = {}
    for engine in engines:
        candidate = s2_root / engine / "pages" / f"{page_id}.rendering-v1.json"
        if candidate.exists():
            result[engine] = candidate
    return result


def _page_ids_from_s2(s2_root: Path, engines: list[str]) -> list[str]:
    """Collect all page_ids that have at least one rendering available.

    Prefers the ABBYY engine as the canonical page list; falls back to the
    first available engine.
    """
    for engine in engines:
        pages_dir = s2_root / engine / "pages"
        if pages_dir.is_dir():
            ids = sorted(
                p.name.replace(".rendering-v1.json", "")
                for p in pages_dir.glob("*.rendering-v1.json")
            )
            if ids:
                return ids
    return []


def _page_ids_from_frozen_wct(frozen_wct_dir: Path) -> list[str]:
    if not frozen_wct_dir.is_dir():
        return []
    return sorted(path.stem for path in frozen_wct_dir.glob("page_*.json"))


def _build_one_page(
    *,
    page_id: str,
    s2_root: Path,
    engines: list[str],
    ia_page_info: dict,
    wct_output_dir: Path,
    force: bool,
) -> dict:
    out_path = wct_output_dir / f"{page_id}.json"
    if out_path.exists() and not force:
        return {"page_id": page_id, "status": "skipped", "message": f"{page_id}: skipped"}

    rendering_paths = _collect_page_rendering_paths(page_id, s2_root, engines)
    if not rendering_paths:
        return {"page_id": page_id, "status": "failed", "message": f"{page_id}: no renderings found"}

    page_num = int(ia_page_info["page_num"])
    source_image = _source_image(ia_page_info)
    schema = json.loads(WCT_SCHEMA_PATH.read_text(encoding="utf-8"))

    try:
        renderings = [
            _load_rendering(path, page_num)
            for path in rendering_paths.values()
        ]
        wct_page = build_from_renderings(
            renderings,
            source_image=source_image,
            work_id=WORK_ID,
            volume_id=VOLUME_ID,
            page_id=page_id,
        )
        write_json_atomic(out_path, wct_page, schema)
        engines_present = sorted(rendering_paths.keys())
        return {
            "page_id": page_id,
            "status": "built",
            "message": (
                f"{page_id}: {len(wct_page['positions'])} positions, "
                f"{len(wct_page['available_engines'])} engines "
                f"({', '.join(engines_present)})"
            ),
        }
    except LayoutEscalation as exc:
        return {
            "page_id": page_id,
            "status": "failed",
            "message": f"{page_id}: LayoutEscalation (no Surya fallback) -- {exc}",
        }
    except (ValueError, KeyError) as exc:
        return {"page_id": page_id, "status": "failed", "message": f"{page_id}: ERROR -- {exc}"}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build WCT pages for the JE surrogate oracle sample (36 pages)."
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Re-build pages that already exist on disk.",
    )
    parser.add_argument(
        "--s2-root",
        type=Path,
        default=S2_ROOT,
        help="Override S2 renderings root (default: reports/je-s2-renderings/vol_02).",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=IA_MANIFEST_PATH,
        help="Override IA pages manifest path.",
    )
    parser.add_argument(
        "--wct-dir",
        type=Path,
        default=WCT_OUTPUT_DIR,
        help="Override WCT output directory.",
    )
    parser.add_argument(
        "--page",
        action="append",
        dest="pages",
        help="Build only this page id (repeatable, e.g. page_0010).",
    )
    parser.add_argument(
        "--frozen-wct-dir",
        type=Path,
        default=FROZEN_WCT_DIR,
        help="Frozen WCT directory whose page set defines the 34-page batch.",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=max(1, min(4, (os.cpu_count() or 2) // 2)),
        help="Number of page workers (default: half CPUs, capped at 4).",
    )
    args = parser.parse_args(argv)

    s2_root = args.s2_root
    ia_manifest_path = args.manifest
    wct_output_dir = args.wct_dir

    # Pre-flight checks
    if not ia_manifest_path.exists():
        print(f"ERROR: IA pages manifest not found: {ia_manifest_path}", file=sys.stderr)
        return 1
    if not s2_root.exists():
        print(f"ERROR: S2 renderings root not found: {s2_root}", file=sys.stderr)
        return 1

    ia_manifest = _load_ia_manifest(ia_manifest_path)
    all_page_ids = sorted(args.pages) if args.pages else _page_ids_from_frozen_wct(args.frozen_wct_dir)
    if not all_page_ids:
        all_page_ids = _page_ids_from_s2(s2_root, ENGINES)
    if not all_page_ids:
        print("ERROR: no per-page rendering files found under S2 root", file=sys.stderr)
        return 1

    wct_output_dir.mkdir(parents=True, exist_ok=True)

    built = skipped = failed = 0
    jobs = []
    for page_id in all_page_ids:
        ia_page_info = ia_manifest.get(page_id)
        if ia_page_info is None:
            print(f"  {page_id}: not in IA manifest -- skip", file=sys.stderr)
            failed += 1
            continue
        jobs.append(
            {
                "page_id": page_id,
                "s2_root": s2_root,
                "engines": ENGINES,
                "ia_page_info": ia_page_info,
                "wct_output_dir": wct_output_dir,
                "force": args.force,
            }
        )

    if args.jobs <= 1:
        results = [_build_one_page(**job) for job in jobs]
    else:
        results = []
        with ProcessPoolExecutor(max_workers=args.jobs) as executor:
            futures = [executor.submit(_build_one_page, **job) for job in jobs]
            for future in as_completed(futures):
                results.append(future.result())
        results.sort(key=lambda item: item["page_id"])

    for result in results:
        status = result["status"]
        if status == "built":
            print(f"  {result['message']}")
            built += 1
        elif status == "skipped":
            skipped += 1
        else:
            print(f"  {result['message']}", file=sys.stderr)
            failed += 1

    print(f"\n{built} built, {skipped} skipped, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
