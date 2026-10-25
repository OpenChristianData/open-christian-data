"""Count verified v2 public rows and text without legacy JSON or WorkCatalog."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ocd_kernel.library._common import PipelineError
from ocd_kernel.release.selection import load_release_selection
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.release.streaming import file_sha256, iter_jsonl


def release_statistics(root: Path, release: Path, selection: dict, *, encoding_name: str | None = None) -> dict:
    """Require independent verification against the original caller selection."""
    report_path = Path(release) / "internal" / "release-report.json"
    report_bytes = report_path.read_bytes()
    checked = verify_release_v2(root, release, selection=selection)
    if checked["status"] != "pass":
        raise PipelineError("release verification failed: " + json.dumps(checked.get("errors", [])))
    if report_path.read_bytes() != report_bytes:
        raise PipelineError("release report changed during verification")
    report = json.loads(report_bytes)
    encoding = None
    if encoding_name is not None:
        import tiktoken
        encoding = tiktoken.get_encoding(encoding_name)
    configurations = []
    for config in report["configurations"]:
        path = Path(release) / config["path"]
        # Bind the bytes actually counted as well as the independently checked tree.
        if file_sha256(path) != config["sha256"]:
            raise PipelineError(f"release changed during counting: {config['category']}")
        count = characters = tokens = 0
        for row in iter_jsonl(path, canonical=True):
            if not isinstance(row.get("text"), str):
                raise PipelineError(f"public text is not a string: {config['category']}")
            count += 1
            characters += len(row["text"])
            if encoding is not None:
                tokens += len(encoding.encode_ordinary(row["text"]))
        if count != config["row_count"] or file_sha256(path) != config["sha256"]:
            raise PipelineError(f"release rows changed during counting: {config['category']}")
        configurations.append({
            "category": config["category"], "records": count,
            "text_characters": characters,
            "uncompressed_bytes": path.stat().st_size, "sha256": config["sha256"],
        })
        if encoding is not None:
            configurations[-1]["tokens"] = tokens
    result = {
        "release_id": report["release_id"], "status": "pass",
        "authority": "independently verified accepted TEI and original release selection",
        "configurations": configurations,
        "total": {key: sum(row[key] for row in configurations)
                  for key in ("records", "text_characters", "uncompressed_bytes")},
        "limits": ["Character counts are Unicode code points, not tokenizer counts.",
                   "This offline report does not authorize publication."],
    }
    if encoding is not None:
        result["tokenizer_encoding"] = encoding_name
        result["total"]["tokens"] = sum(row["tokens"] for row in configurations)
        result["limits"].append("Tokens count each public text field independently, treating special-token spellings as ordinary source text.")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--encoding", help="Optional tiktoken encoding for verified public text.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = release_statistics(args.root, args.release, load_release_selection(args.selection), encoding_name=args.encoding)
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n", encoding="utf-8", newline="\n")
    except (PipelineError, OSError, ValueError, ImportError) as exc:
        parser.error(str(exc))
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
