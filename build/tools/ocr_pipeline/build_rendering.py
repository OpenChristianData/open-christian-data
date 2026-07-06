from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.atomic_io import write_json_atomic


CATALOG_SCHEMA = json.loads((REPO_ROOT / "schemas" / "v1" / "rendering_catalog.schema.json").read_text(encoding="utf-8"))


def _engine_from_runtime() -> str:
    result = subprocess.run(["tesseract", "--version"], check=True, capture_output=True, text=True)
    first_line = (result.stdout or "").splitlines()[0].strip() if result.stdout else ""
    parts = first_line.split()
    version = parts[1] if len(parts) >= 2 and parts[0].lower() == "tesseract" else first_line
    engine = f"tesseract@{version}" if version else ""
    if not engine or engine == "tesseract@":
        raise ValueError("empty OCR engine version")
    return engine


def validate_catalog_engines(catalog: dict) -> None:
    for rendering in catalog.get("renderings", []):
        if rendering.get("format") == "ocr" and not rendering.get("engine"):
            raise ValueError("OCR rendering engine must be non-empty")


def build_catalog(rendering_id: str, engine: str) -> dict:
    return {
        "work_id": "reference/test-work",
        "edition": "2000",
        "modernisation_intent": "not_applicable",
        "pd_anchor_decision": {
            "chosen_rendering": "anchor",
            "rationale": "Fixture anchor.",
            "decided_at": datetime.now(timezone.utc).isoformat(),
            "alternates_considered": [],
        },
        "renderings": [
            {"rendering_id": "anchor", "role": "pd_anchor", "format": "plain", "license": "public-domain"},
            {
                "rendering_id": rendering_id,
                "role": "pending",
                "source": "fixture",
                "format": "ocr",
                "license": "public-domain",
                "engine": engine,
            },
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build an OCR rendering catalog entry.")
    parser.add_argument("--rendering-id", required=True)
    parser.add_argument("--scan-dir", required=True)
    parser.add_argument("--work-handle", default="reference/test-work/2000")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    engine = _engine_from_runtime()
    catalog = build_catalog(args.rendering_id, engine)
    validate_catalog_engines(catalog)
    write_json_atomic(Path("data") / args.work_handle / "catalog.json", catalog, CATALOG_SCHEMA)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
