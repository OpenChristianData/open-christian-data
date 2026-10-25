"""Verify an offline release through normal and streaming Hugging Face readers."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ocd_kernel.library._common import PipelineError
from ocd_kernel.release.public_allowlist import _configurations, _is_link, public_files
from ocd_kernel.release.selection import load_release_selection
from ocd_kernel.release.typed_rows import compare_rows
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.release.streaming import file_sha256, iter_jsonl


def check_reader(root: Path, release: Path, selection: dict, *, reader_only: bool = False,
                 temp_root: Path | None = None) -> dict:
    # Set offline switches before importing the client. No remote input is needed.
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    os.environ["HF_HUB_OFFLINE"] = "1"
    import datasets
    import pyarrow

    if _is_link(release):
        raise PipelineError("release root cannot be a reparse point")
    release = release.resolve(strict=True)
    report_path = release / "internal/release-report.json"
    report_bytes = report_path.read_bytes()
    if reader_only:
        checked = {"status": "not-run", "reason": "independent full verification must be bound separately"}
    else:
        checked = verify_release_v2(root, release, selection=selection)
        if checked["status"] != "pass":
            raise PipelineError(f"release verification failed: {checked['errors']}")
    report = json.loads(report_bytes)
    configurations = _configurations(report["configurations"])
    expected_public = {"README.md"}
    for config in configurations:
        if not isinstance(config.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", config["sha256"]):
            raise PipelineError("invalid public JSONL digest")
        expected_public.add(config["path"].removeprefix("public/"))
        if "typed_companion" in config:
            expected_public.add(config["typed_companion"]["path"].removeprefix("public/"))
    if public_files(release / "public") != expected_public:
        raise PipelineError("public file set differs from reader configurations")
    bindings = {report_path: hashlib.sha256(report_bytes).hexdigest()}
    card = release / "public/README.md"
    bindings[card] = hashlib.sha256(card.read_bytes()).hexdigest()
    results = []
    if temp_root is not None:
        temp_root = Path(temp_root)
        temp_root.mkdir(parents=True, exist_ok=True)
    for config in configurations:
        with tempfile.TemporaryDirectory(prefix="ocd-reader-", dir=temp_root) as cache:
            source = release / config["path"]
            bindings[source] = config["sha256"]
            if file_sha256(source) != config["sha256"]:
                raise PipelineError("public JSONL changed during reader check")
            row_count = sum(1 for _row in iter_jsonl(source, canonical=True))
            if row_count != config["row_count"]:
                raise PipelineError("public JSONL row count differs from reader configuration")
            typed = config.get("typed_companion")
            if typed:
                typed_path = release / typed["path"]
                bindings[typed_path] = typed["sha256"]
                if file_sha256(typed_path) != typed["sha256"]:
                    raise PipelineError("typed companion changed during reader check")
            for streaming in (False, True):
                loaded = datasets.load_dataset(str(release / "public"), name=config["category"],
                                               split="train", streaming=streaming, cache_dir=cache)
                count = 0
                expected_rows = iter_jsonl(source, canonical=True)
                try:
                    for count, row in enumerate(loaded, start=1):
                        expected = next(expected_rows, None)
                        if expected is None:
                            raise PipelineError("reader added rows")
                        compare_rows(expected, row, f"{config['category']}/{count - 1}")
                    if next(expected_rows, None) is not None or count != row_count:
                        raise PipelineError("reader omitted rows")
                finally:
                    expected_rows.close()
                    del loaded
            results.append({"category": config["category"], "rows": row_count,
                            "normal_and_streaming": "pass", "all_original_values_and_order_preserved": True})
    for path, expected in bindings.items():
        if file_sha256(path) != expected:
            raise PipelineError(f"release changed during reader verification: {path.name}")
    return {"status": "reader-only-pass" if reader_only else "pass",
            **({"scope": "reader-values-only"} if reader_only else {}),
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "release": str(release), "release_report_sha256": bindings[report_path],
            "verification": checked, "configurations": results,
            "datasets_version": datasets.__version__, "pyarrow_version": pyarrow.__version__,
            "offline": True, "publication_performed": False,
            "tabular_difference": "Only absent optional fields may gain null values."}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reader-only", action="store_true",
                        help="check offline reader values only; independent full verification is required separately")
    parser.add_argument("--temp-root", type=Path, help="directory for category-scoped reader caches")
    args = parser.parse_args(argv)
    try:
        result = check_reader(args.root, args.release, load_release_selection(args.selection),
                              reader_only=args.reader_only, temp_root=args.temp_root)
    except (PipelineError, OSError, ValueError, TypeError, KeyError) as exc:
        result = {"status": "fail", "error": str(exc), "publication_performed": False}
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] in {"pass", "reader-only-pass"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
