from __future__ import annotations

import argparse
import hashlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib import request as urllib_request  # standards: download only
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ocd_kernel.lib.atomic_io import write_json_atomic


OBJECT_SCHEMA = {"type": "object"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _infer_format(path: str) -> str:
    suffix = Path(path).suffix.lower().lstrip(".")
    if suffix in {"txt", "text"}:
        return "plain"
    return suffix or "plain"


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}-{int(datetime.now(timezone.utc).timestamp() * 1_000_000)}")
    try:
        tmp.write_bytes(payload)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()  # standards: log/temp rotation


def fetch(url: str, *, work_handle: str | None = None, rendering_id: str | None = None) -> dict:
    parsed = urlparse(url)
    basename = Path(parsed.path).name or "source"
    rid = rendering_id or Path(basename).stem
    fmt = _infer_format(basename)
    with urllib_request.urlopen(urllib_request.Request(url, headers={"User-Agent": "open-christian-data/slot10"})) as resp:
        body = resp.read()

    digest = hashlib.sha256(body).hexdigest()
    raw_path = Path("data") / rid / "raw" / basename
    _atomic_write_bytes(raw_path, body)

    manifest = {
        "rendering_id": rid,
        "source_url": url,
        "source": parsed.netloc,
        "format": fmt,
        "sha256": f"sha256:{digest}",
        "fetched_at": _utc_now(),
    }
    if work_handle is not None:
        manifest["work_handle"] = work_handle

    write_json_atomic(raw_path.with_suffix(raw_path.suffix + ".manifest.json"), manifest, OBJECT_SCHEMA)
    write_json_atomic(raw_path.parent / "manifest.json", manifest, OBJECT_SCHEMA)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch and cache one rendering source.")
    parser.add_argument("source_url")
    parser.add_argument("--work-handle")
    parser.add_argument("--rendering-id")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    fetch(args.source_url, work_handle=args.work_handle, rendering_id=args.rendering_id)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
