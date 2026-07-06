from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.page_order import volume_duplicate_stems  # noqa: E402
from build.lib.ocr_store_paths import S1_SIDECARS_ROOT  # noqa: E402
from build.tools.ocr_pipeline.sidecar_utils import count_sidecars  # noqa: E402

_NSH_INPUT_ROOT = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"


KNOWN_ENGINES = [
    "tesseract-py314-v1",
    "kraken-py312-v1",
    "kraken-greek-py312-v1",
    "surya-py312-v1",
    "ia-abbyy-v1",
    "ia-abbyy-haucgoog-v1",
    "ia-abbyy-dli-v1",
    "ia-abbyy-haucgoog-c1-v1",
    "ia-abbyy-haucgoog-c2-v1",
    "ia-abbyy-haucgoog-c3-v1",
    "ia-abbyy-haucgoog-c4-v1",
]


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object in {path}")
    return data


def _manifest_count(manifest_path: Path) -> int | None:
    if not manifest_path.exists():
        return None
    manifest = _read_json(manifest_path)
    pages = manifest.get("pages", [])
    if not isinstance(pages, list):
        raise ValueError(f"expected pages list in {manifest_path}")
    return len(pages)


def _state_count(state_path: Path) -> int | None:
    if not state_path.exists():
        return None
    state = _read_json(state_path)
    emitted_pages = state.get("emitted_pages", [])
    if not isinstance(emitted_pages, list):
        raise ValueError(f"expected emitted_pages list in {state_path}")
    return len(emitted_pages)


def _sidecar_health(
    pages_dir: Path,
    *,
    exclude_stems: frozenset[str] = frozenset(),
) -> tuple[int, int, int]:
    failed = 0
    corrupt = 0
    seen_native_ids: set[str] = set()
    duplicate_native_ids = 0
    if not pages_dir.exists():
        return failed, corrupt, duplicate_native_ids

    for sidecar_path in pages_dir.glob("*.json"):
        if sidecar_path.stem in exclude_stems:
            continue
        if not sidecar_path.is_file():
            continue
        try:
            sidecar = _read_json(sidecar_path)
        except (json.JSONDecodeError, ValueError, OSError):
            corrupt += 1
            continue

        native_id = sidecar.get("page_native_id")
        if isinstance(native_id, str) and native_id:
            if native_id in seen_native_ids:
                duplicate_native_ids += 1
            seen_native_ids.add(native_id)
        failure_class = sidecar.get("page_extras_carried", {}).get("failure_class")
        if isinstance(failure_class, str) and failure_class:
            failed += 1
    return failed, corrupt, duplicate_native_ids


def check_engine_volume(
    engine: str,
    volume: int,
    *,
    output_root: Path,
    input_root: Path = _NSH_INPUT_ROOT,
) -> dict:
    run_dir = output_root / engine / f"vol_{volume:02d}"
    pages_dir = run_dir / "pages"
    input_vol_dir = input_root / f"vol_{volume:02d}"
    duplicate_stems = volume_duplicate_stems(input_vol_dir)
    sidecar_count = count_sidecars(pages_dir, exclude_stems=duplicate_stems)
    manifest_path = run_dir / "manifest.json"
    state_path = run_dir / "manifest.state.json"
    manifest_count = _manifest_count(manifest_path)
    state_count = _state_count(state_path)
    failed, corrupt, duplicate_native_ids = _sidecar_health(pages_dir, exclude_stems=duplicate_stems)
    missing_manifest = sidecar_count > 0 and not manifest_path.exists()
    missing_state = sidecar_count > 0 and not state_path.exists()
    # state_count (emitted_pages) counts only successful pages; failed and
    # corrupt sidecars are written to disk but omitted from the state. So the
    # invariant is: successful sidecars on disk == state_count, i.e.
    # state_count == sidecar_count - failed - corrupt. (failed/corrupt > 0 also
    # force drift independently below, so this clause is the canonical signal
    # only when there are no failures.)
    successful_on_disk = sidecar_count - failed - corrupt
    drift = (
        missing_manifest
        or missing_state
        or (manifest_count is not None and sidecar_count != manifest_count)
        or (state_count is not None and state_count != successful_on_disk)
        or failed > 0
        or corrupt > 0
        or duplicate_native_ids > 0
    )
    return {
        "engine": engine,
        "volume": volume,
        "sidecar_count": sidecar_count,
        "manifest_count": manifest_count,
        "state_count": state_count,
        "missing_manifest": missing_manifest,
        "missing_state": missing_state,
        "drift": drift,
        "failed": failed,
        "corrupt": corrupt,
        "duplicate_native_ids": duplicate_native_ids,
    }


def _count_cell(value: int | None) -> str:
    if value is None:
        return "--"
    return str(value)


def _print_report(rows: list[dict]) -> None:
    print("engine                     vol  sidecars  manifest  state  failed  corrupt  dup_id  drift")
    for row in rows:
        drift_label = "DRIFT" if row["drift"] else "OK"
        volume_label = f"{row['volume']:02d}"
        manifest_cell = "MISSING" if row.get("missing_manifest") else _count_cell(row["manifest_count"])
        state_cell = "MISSING" if row.get("missing_state") else _count_cell(row["state_count"])
        print(
            f"{row['engine']:<26}"
            f"{volume_label:>3}"
            f"{row['sidecar_count']:>10d}"
            f"{manifest_cell:>10}"
            f"{state_cell:>7}"
            f"{row['failed']:>8d}"
            f"{row['corrupt']:>9d}"
            f"{row['duplicate_native_ids']:>8d}"
            f"{drift_label:>6}"
        )


def run_doctor(volumes: list[int], engines: list[str], *, output_root: Path) -> int:
    rows = [
        check_engine_volume(engine, volume, output_root=output_root)
        for engine in engines
        for volume in volumes
    ]
    _print_report(rows)
    return 1 if any(row["drift"] for row in rows) else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check OCR sidecar manifests for stale counts.")
    parser.add_argument("--volume", type=int, action="append", required=True)
    parser.add_argument("--engine", action="append")
    parser.add_argument("--all-engines", action="store_true")
    parser.add_argument("--output-root", type=Path, default=S1_SIDECARS_ROOT)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    engines = args.engine if args.engine and not args.all_engines else KNOWN_ENGINES
    if args.engine and args.all_engines:
        engines = KNOWN_ENGINES
    return run_doctor(args.volume, engines, output_root=args.output_root)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
