"""Run Schaff-Herzog S0 ingest reports and integrity gate."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "reports" / "ingest"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.s0_ingest import (  # noqa: E402
    available_engines_for_volume,
    build_page_leaf_bijection,
    corpus_page_count,
    integrity_flags_to_dicts,
    load_volume_manifest,
    s0_integrity_check,
)


def _relative_path(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _atomic_write_json(target: Path, payload: dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_name(f"{target.name}.tmp")
    temp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(target)


def _manifest_paths() -> list[Path]:
    raw_base = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"
    return sorted(raw_base.glob("vol_*.manifest.json"))


def run() -> int:
    total_flags = 0
    per_volume_counts: dict[str, int] = {}

    for manifest_path in _manifest_paths():
        manifest = load_volume_manifest(manifest_path)
        volume = manifest.get("volume")
        if not isinstance(volume, int):
            volume = int(manifest_path.name.removesuffix(".manifest.json").removeprefix("vol_"))

        bijection = build_page_leaf_bijection(manifest)
        engines = available_engines_for_volume(volume, REPO_ROOT)
        flags = s0_integrity_check(volume, REPO_ROOT)
        total_flags += len(flags)
        per_volume_counts[str(volume)] = bijection["numbered_page_count"]

        _atomic_write_json(
            OUTPUT_DIR / f"s0_bijection_vol_{volume:02d}.json",
            {
                "manifest_path": _relative_path(manifest_path),
                "volume": volume,
                "bijection": bijection,
                "available_engines": engines,
                "hard_flags": integrity_flags_to_dicts(flags),
                "hard_flag_count": len(flags),
            },
        )

    summary = corpus_page_count(REPO_ROOT)
    summary["total_hard_flags"] = total_flags
    summary["volume_count"] = len(per_volume_counts)
    _atomic_write_json(OUTPUT_DIR / "s0_corpus_summary.json", summary)

    print(
        "S0 ingest: "
        f"volumes={summary['volume_count']} "
        f"numbered_pages={summary['corpus_numbered_page_count']} "
        f"total_leaves={summary['corpus_total_leaf_count']} "
        f"hard_flags={total_flags}"
    )
    return 1 if total_flags else 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
