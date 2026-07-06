"""Regenerate Phase C text layers for a pilot record."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.atomic_io import write_json_atomic  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402


WRITER_SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "writer_manifest.schema.json"

PARSER_CONFIG = {
    "adam-clarke": {
        "script": Path("build/parsers/helloao_commentary.py"),
        "writer_identity": "adam_clarke_parser",
        "writer_version": "build/parsers/helloao_commentary.py@v1.0.0",
        "record": Path("data/commentaries/adam-clarke/2-john.json"),
        "data_paths": [
            Path("data/commentaries/adam-clarke/2-john.json"),
            Path("data/commentaries/adam-clarke/_manifest.json"),
        ],
        "argv": ["--commentary", "adam-clarke", "--book", "2JN", "--emit-layers"],
    },
    "ccel_schaff_herzog": {
        "script": Path("build/parsers/ccel_schaff_herzog.py"),
        "writer_identity": "ccel_schaff_herzog_parser",
        "writer_version": "build/parsers/ccel_schaff_herzog.py@v1.0.0",
        "record": Path("data/reference/schaff-herzog-encyclopedia.json"),
        "data_paths": [Path("data/reference/schaff-herzog-encyclopedia.json")],
        "argv": ["--volume", "encyc01", "--emit-layers"],
    },
    "ia_schaff_herzog": {
        "script": Path("build/parsers/ia_schaff_herzog.py"),
        "writer_identity": "ia_schaff_herzog_parser",
        "writer_version": "build/parsers/ia_schaff_herzog.py@v1.0.0",
        "record": Path("data/reference/schaff-herzog-encyclopedia.json"),
        "data_paths": [Path("data/reference/schaff-herzog-encyclopedia.json")],
        "argv": ["--volume", "3", "--emit-layers"],
    },
}


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(
    *,
    parser_key: str,
    run_id: str,
    checksums: dict[str, dict[str, str | None]],
    delta_counts: dict[str, dict[str, int]],
) -> dict:
    config = PARSER_CONFIG[parser_key]
    return {
        "schema_version": "1.0.0",
        "writer": "parser",
        "writer_version": config["writer_version"],
        "writer_identity": config["writer_identity"],
        "run_id": run_id,
        "started_at": _utc_now_iso(),
        "data_paths": list(checksums),
        "checksums": checksums,
        "expected_delta_counts": delta_counts,
        "allowed_field_paths": ["/meta/*", "/data/*/layers"],
        "partial_completion_policy": "all_or_nothing",
        "renames": [],
    }


def run_layer(
    *,
    parser_key: str,
    resource_id: str | None,
    dry_run: bool,
    writer_manifest_out: Path,
    repo_root: Path = REPO_ROOT,
) -> dict:
    if parser_key not in PARSER_CONFIG:
        raise ValueError(f"unknown parser: {parser_key}")
    config = PARSER_CONFIG[parser_key]
    record_path = repo_root / config["record"]
    data_paths = [repo_root / path for path in config["data_paths"]]
    before_checksums = {
        str(path.relative_to(repo_root)).replace("\\", "/"): _sha256(path)
        for path in data_paths
    }
    before_payload = json.loads(record_path.read_text(encoding="utf-8")) if record_path.exists() else None
    command = [sys.executable, str(repo_root / config["script"]), *config["argv"]]
    if dry_run:
        command.append("--dry-run")
    subprocess.run(command, cwd=repo_root, check=True)
    after_checksums = {
        str(path.relative_to(repo_root)).replace("\\", "/"): _sha256(path)
        for path in data_paths
    }
    after_payload = json.loads(record_path.read_text(encoding="utf-8")) if record_path.exists() else None
    entries_changed = _count_changed_entries(before_payload, after_payload)
    checksums = {
        path: {
            "before_sha256": before_checksums[path],
            "after_sha256": after_checksums[path] or "0" * 64,
        }
        for path in before_checksums
    }
    parser_record_paths = {
        str(config["record"]).replace("\\", "/")
        for config in PARSER_CONFIG.values()
    }
    delta_counts = {
        path: {
            "entries_changed": entries_changed if path in parser_record_paths else 1,
            "fields_changed": entries_changed if path in parser_record_paths else 1,
        }
        for path in before_checksums
    }
    run_id = str(uuid.uuid4())
    manifest = _manifest(
        parser_key=parser_key,
        run_id=run_id,
        checksums=checksums,
        delta_counts=delta_counts,
    )
    _ = resource_id
    if not dry_run:
        schema = json.loads(WRITER_SCHEMA_PATH.read_text(encoding="utf-8"))
        write_json_atomic(writer_manifest_out, manifest, schema)
    return manifest


def _count_changed_entries(before_payload: dict | None, after_payload: dict | None) -> int:
    if not before_payload or not after_payload:
        return len((after_payload or {}).get("data", []) or [])
    before_entries = {
        entry.get("entry_id"): entry
        for entry in before_payload.get("data", []) or []
        if isinstance(entry, dict)
    }
    changed = 0
    for entry in after_payload.get("data", []) or []:
        if not isinstance(entry, dict):
            continue
        if before_entries.get(entry.get("entry_id")) != entry:
            changed += 1
    return changed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parser", required=True, choices=sorted(PARSER_CONFIG))
    parser.add_argument("--resource-id", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--writer-manifest-out",
        type=Path,
        default=REPO_ROOT / "review" / "writer-manifests" / "regenerate_layers.json",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    manifest = run_layer(
        parser_key=args.parser,
        resource_id=args.resource_id,
        dry_run=args.dry_run,
        writer_manifest_out=args.writer_manifest_out,
    )
    print(json.dumps({"run_id": manifest["run_id"], "data_paths": manifest["data_paths"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
