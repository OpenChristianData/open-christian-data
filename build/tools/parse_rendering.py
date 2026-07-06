from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.atomic_io import write_json_atomic


OBJECT_SCHEMA = {"type": "object"}


def _load_manifest(rendering_id: str) -> dict[str, Any]:
    manifest_path = Path("data") / rendering_id / "raw" / "manifest.json"
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _raw_path(rendering_id: str) -> Path:
    raw_dir = Path("data") / rendering_id / "raw"
    candidates = [path for path in raw_dir.iterdir() if path.is_file() and not path.name.endswith(".json")]
    if not candidates:
        raise FileNotFoundError(f"no raw source found for {rendering_id}")
    return sorted(candidates)[0]


def _fallback_parse(rendering_id: str, raw_path: Path, fmt: str) -> dict[str, Any]:
    text = raw_path.read_text(encoding="utf-8", errors="replace")
    if fmt == "thml":
        text = re.sub(r"<[^>]+>", " ", text)
    text = " ".join(text.split())
    return {
        "rendering_id": rendering_id,
        "blocks": [
            {
                "block_id": "b_0001",
                "text": text,
                "original_text": text,
                "page": 1,
            }
        ],
    }


def _dispatch_parser(rendering_id: str, raw_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    fmt = str(manifest.get("format") or raw_path.suffix.lstrip(".") or "plain")
    try:
        module = importlib.import_module(f"build.parsers.{fmt}")
    except ModuleNotFoundError:
        return _fallback_parse(rendering_id, raw_path, fmt)
    for name in ("parse_rendering", "parse"):
        func = getattr(module, name, None)
        if callable(func):
            parsed = func(raw_path)
            if isinstance(parsed, dict):
                parsed.setdefault("rendering_id", rendering_id)
                return parsed
    return _fallback_parse(rendering_id, raw_path, fmt)


def parse(rendering_id: str) -> Path:
    manifest = _load_manifest(rendering_id)
    raw_path = _raw_path(rendering_id)
    parsed = _dispatch_parser(rendering_id, raw_path, manifest)
    work_handle = str(manifest["work_handle"])
    target = Path("data") / work_handle / "parses" / f"{rendering_id}.json"
    write_json_atomic(target, parsed, OBJECT_SCHEMA)
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Parse a cached rendering.")
    parser.add_argument("rendering_id")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    parse(args.rendering_id)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
