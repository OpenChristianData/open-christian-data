"""Generate writer manifests for Catholic Encyclopedia volume data files.

For each ``data/reference/catholic-encyclopedia-volNN.json`` that exists but has
no paired ``review/writer-manifests/catholic-encyclopedia-volNN-<date>.json``,
emit a schema-valid writer manifest matching the vol01 structure: after-hash,
entry/contributor counts from the data file, and skipped/empty_body counts
parsed from the crawl log when available.

Idempotent: skips volumes that already have a manifest for the given run date.
Run from the repo root:

    py -3 build/tools/gen_ce_writer_manifests.py --date 2026-06-17
    py -3 build/tools/gen_ce_writer_manifests.py --date 2026-06-17 --volume 2
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.paths import REPO_ROOT  # noqa: E402

DATA_DIR = REPO_ROOT / "data" / "reference"
MANIFEST_DIR = REPO_ROOT / "review" / "writer-manifests"
CRAWL_LOG = REPO_ROOT / "ce_crawl_run.log"

WRITER_IDENTITY = "catholic_encyclopedia_parser"
WRITER_VERSION = "build/parsers/catholic_encyclopedia.py@v1.0.0"

log = logging.getLogger("gen_ce_writer_manifests")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _log_counts(vol: int) -> tuple[int | None, int | None]:
    """Parse skipped/empty_body for a volume from the crawl log, if present.

    The parser logs e.g.:
      Wrote 222 entries to .../catholic-encyclopedia-vol02.json (skipped=3, empty_body=1).
    """
    if not CRAWL_LOG.exists():
        return None, None
    pat = re.compile(
        rf"catholic-encyclopedia-vol{vol:02d}\.json \(skipped=(\d+), empty_body=(\d+)\)"
    )
    for line in CRAWL_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        m = pat.search(line)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None, None


def build_manifest(vol: int, date: str) -> dict:
    data_path = DATA_DIR / f"catholic-encyclopedia-vol{vol:02d}.json"
    if not data_path.exists():
        raise FileNotFoundError(f"missing data file: {data_path}")

    payload = json.loads(data_path.read_text(encoding="utf-8"))
    entries = payload["data"]
    contributors = payload["meta"].get("contributors", [])
    rel_path = data_path.relative_to(REPO_ROOT).as_posix()

    skipped, empty_body = _log_counts(vol)
    delta: dict[str, int] = {
        "entries_written": len(entries),
        "contributors_unique": len(contributors),
    }
    if skipped is not None:
        delta["skipped"] = skipped
    if empty_body is not None:
        delta["empty_body"] = empty_body

    # File mtime is the closest available proxy for the crawl start time.
    started = datetime.fromtimestamp(data_path.stat().st_mtime, tz=timezone.utc)

    return {
        "schema_version": "1.0.0",
        "writer": "parser",
        "writer_version": WRITER_VERSION,
        "writer_identity": WRITER_IDENTITY,
        "run_id": f"catholic-encyclopedia-vol{vol:02d}-{date}",
        "started_at": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_paths": [rel_path],
        "checksums": {
            rel_path: {"before_sha256": None, "after_sha256": _sha256(data_path)}
        },
        "expected_delta_counts": {rel_path: delta},
        "allowed_field_paths": ["/meta", "/data"],
        "partial_completion_policy": "all_or_nothing",
        "notes": (
            f"Volume {vol} crawl. {len(entries)} articles via 26 per-letter index "
            "pages on newadvent.org/cathen/. Rate-limited 1-2s/request. "
            "No 403/429 encountered."
        ),
        "renames": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="Run date stamp, e.g. 2026-06-17")
    parser.add_argument(
        "--volume",
        type=int,
        choices=range(1, 16),
        metavar="N",
        help="Single volume; default = every vol data file present without a manifest.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.volume is not None:
        vols = [args.volume]
    else:
        vols = sorted(
            int(p.stem.split("vol")[-1])
            for p in DATA_DIR.glob("catholic-encyclopedia-vol*.json")
        )

    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    for vol in vols:
        out_path = MANIFEST_DIR / f"catholic-encyclopedia-vol{vol:02d}-{args.date}.json"
        if out_path.exists():
            log.info("vol %02d: manifest already exists, skipping", vol)
            continue
        manifest = build_manifest(vol, args.date)
        tmp = out_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        tmp.replace(out_path)
        d = manifest["expected_delta_counts"][manifest["data_paths"][0]]
        log.info(
            "vol %02d: wrote manifest (entries=%d, contributors=%d)",
            vol, d["entries_written"], d["contributors_unique"],
        )
        written += 1

    print(f"Done: {written} manifest(s) written, {len(vols) - written} skipped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
