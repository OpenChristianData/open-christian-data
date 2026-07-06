from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.atomic_io import AtomicWriteError, write_json_atomic


DATASET_CARD_TEMPLATE = REPO_ROOT / "docs" / "HUGGINGFACE_DATASET_CARD.md"
OBJECT_SCHEMA = {"type": "object"}
CONFIGS = ("original", "modernised")
R65_PLACEHOLDER = "<!-- R65_TABLE_ROWS -->"
SCHAFF_HANDLE = "reference/schaff/encyclopedia/1908-1914"


class MisplacedRecord(Exception):
    """Raised when a record JSON file is nested below an allowed config dir."""


def _normalise_path(path: Path) -> str:
    return path.as_posix()


def _atomic_write_text(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + f".tmp-{os.getpid()}-{int(time.time_ns())}")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        try:
            if tmp.exists():
                tmp.unlink()  # standards: log/temp rotation
        except OSError:
            pass
        raise


def _iter_config_dirs(data_root: Path, config: str) -> Iterable[Path]:
    for candidate in data_root.rglob(config):
        if candidate.is_dir():
            yield candidate


def _reject_misplaced_records(data_root: Path) -> None:
    for config in CONFIGS:
        for config_dir in _iter_config_dirs(data_root, config):
            work_dir = config_dir.parent
            for record_path in sorted(config_dir.rglob("*.json")):
                rel_parts = record_path.relative_to(work_dir).parts
                if len(rel_parts) != 2 or rel_parts[0] != config:
                    raise MisplacedRecord(_normalise_path(record_path))


def _discover_records(data_root: Path, config: str) -> list[Path]:
    return sorted(path for path in data_root.rglob(f"{config}/*.json") if path.is_file())


def _work_handle_for_record(data_root: Path, record_path: Path) -> str:
    work_dir = record_path.parent.parent
    return _normalise_path(work_dir.relative_to(data_root))


def _work_handle_from_record(record: Mapping[str, Any], data_root: Path, record_path: Path) -> str:
    meta = record.get("meta")
    if isinstance(meta, Mapping):
        record_id = meta.get("id")
        if isinstance(record_id, str) and "/" in record_id:
            return record_id.rsplit("/", 1)[0]
    return _work_handle_for_record(data_root, record_path)


def _load_records(paths: Iterable[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        records.append(json.loads(path.read_text(encoding="utf-8")))
    return records


def _jsonl(records: Iterable[Mapping[str, Any]]) -> str:
    lines = [json.dumps(record, ensure_ascii=False, sort_keys=False) for record in records]
    return "\n".join(lines) + ("\n" if lines else "")


def _dataset_infos(record_counts: Mapping[str, int]) -> dict[str, Any]:
    return {
        config: {
            "description": f"Open Christian Data {config} records.",
            "features": None,
            "splits": {
                "train": {
                    "name": "train",
                    "num_bytes": 0,
                    "num_examples": record_counts[config],
                }
            },
        }
        for config in CONFIGS
    }


def _coverage_rows(data_root: Path, records_by_config: Mapping[str, list[Path]]) -> list[str]:
    original_handles = set()
    for record_path in records_by_config["original"]:
        record = json.loads(record_path.read_text(encoding="utf-8"))
        original_handles.add(_work_handle_from_record(record, data_root, record_path))

    modernised_handles = set()
    for record_path in records_by_config["modernised"]:
        record = json.loads(record_path.read_text(encoding="utf-8"))
        modernised_handles.add(_work_handle_from_record(record, data_root, record_path))
    handles = sorted(original_handles | modernised_handles)

    rows: list[str] = []
    for handle in handles:
        if handle == SCHAFF_HANDLE:
            continue
        original = "present" if handle in original_handles else "absent"
        modernised = "present" if handle in modernised_handles else "absent"
        rationale = (
            "Modernised sibling present."
            if modernised == "present"
            else "Modernise is optional under ADR-0003."
        )
        rows.append(f"| {handle} | {original} | {modernised} | {rationale} |")
    return rows


def _render_dataset_card(data_root: Path, records_by_config: Mapping[str, list[Path]]) -> str:
    if not DATASET_CARD_TEMPLATE.exists():
        raise FileNotFoundError(f"dataset card template not found: {DATASET_CARD_TEMPLATE}")

    template = DATASET_CARD_TEMPLATE.read_text(encoding="utf-8")
    if R65_PLACEHOLDER not in template:
        raise ValueError(f"dataset card template missing {R65_PLACEHOLDER}")

    rows = _coverage_rows(data_root, records_by_config)
    replacement = "\n".join(rows)
    return template.replace(R65_PLACEHOLDER, replacement)


def export_dataset(data_root: Path, output: Path) -> None:
    _reject_misplaced_records(data_root)

    records_by_config = {config: _discover_records(data_root, config) for config in CONFIGS}
    for config in CONFIGS:
        records = _load_records(records_by_config[config])
        _atomic_write_text(output / config / "records.jsonl", _jsonl(records))

    record_counts = {config: len(records_by_config[config]) for config in CONFIGS}
    write_json_atomic(output / "dataset_infos.json", _dataset_infos(record_counts), OBJECT_SCHEMA)
    _atomic_write_text(output / "README.md", _render_dataset_card(data_root, records_by_config))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export OCD records as a local HuggingFace dataset.")
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("exports"))
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv or []))
    try:
        export_dataset(Path(args.data_root), Path(args.output))
    except MisplacedRecord:
        raise
    except AtomicWriteError as exc:
        print(f"atomic write failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
