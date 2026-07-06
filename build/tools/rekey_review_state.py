"""Re-key review sidecars and correction ledgers from parser remap manifests."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib import review_state  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_field_path(value: str) -> str:
    return value.removeprefix("layers.")


def _split_entry_field(value: str) -> tuple[str, str]:
    if "|" not in value:
        return "", _canonical_field_path(value)
    entry_id, field_path = value.split("|", 1)
    return entry_id, _canonical_field_path(field_path)


def _load_manifests(paths: Iterable[Path]) -> tuple[dict[str, str], set[str], dict[tuple[str, str], tuple[str, str]], set[tuple[str, str]], dict[str, str]]:
    anchor_map: dict[str, str] = {}
    orphaned_anchors: set[str] = set()
    field_map: dict[tuple[str, str], tuple[str, str]] = {}
    orphaned_fields: set[tuple[str, str]] = set()
    signature_map: dict[str, str] = {}

    for path in paths:
        manifest = _load_json(path)
        if "slug_algorithm_version_from" in manifest:
            anchor_map.update({str(k): str(v) for k, v in manifest.get("remap", {}).items()})
            orphaned_anchors.update(str(v) for v in manifest.get("orphaned", []))
        elif "orphaned_field_paths" in manifest:
            for old, new in manifest.get("remap", {}).items():
                field_map[_split_entry_field(str(old))] = _split_entry_field(str(new))
            for value in manifest.get("orphaned_field_paths", []):
                orphaned_fields.add(_split_entry_field(str(value)))
        elif "explicit_remap" in manifest:
            signature_map.update(
                {str(k): str(v) for k, v in manifest.get("explicit_remap", {}).items()}
            )
        else:
            raise ValueError(f"unknown remap manifest shape: {path}")
    return anchor_map, orphaned_anchors, field_map, orphaned_fields, signature_map


def _remap_signature(signature: str, signature_map: dict[str, str]) -> str:
    return signature_map.get(signature, signature)


def _orphan_warning(entry_id: str, field_path: str) -> dict:
    return {
        "reason": "correction_orphaned_by_parser",
        "raw_warning": {
            "producer": "parser_regen",
            "code": "correction_orphaned_by_parser",
            "entry_id": entry_id,
            "field_path": field_path,
        },
        "received_at": _utc_now_iso(),
        "producer": "parser_regen",
        "code": "correction_orphaned_by_parser",
        "entry_id": entry_id,
    }


def _rekey_sidecar(
    sidecar: dict,
    *,
    anchor_map: dict[str, str],
    orphaned_anchors: set[str],
    field_map: dict[tuple[str, str], tuple[str, str]],
    orphaned_fields: set[tuple[str, str]],
    signature_map: dict[str, str],
) -> tuple[dict, int]:
    changed = 0
    entries = sidecar.get("entries", {})
    new_entries: dict[str, dict] = {}
    for entry_id, entry_state in entries.items():
        new_entry_id = anchor_map.get(entry_id, entry_id)
        if new_entry_id != entry_id:
            changed += 1
        if new_entry_id in new_entries:
            merged = new_entries[new_entry_id]
            for bucket in ("warnings_acknowledged", "warnings_dismissed"):
                merged.setdefault(bucket, []).extend(entry_state.get(bucket, []))
            for key in ("last_reviewed_at", "last_reviewer"):
                if entry_state.get(key):
                    merged[key] = entry_state[key]
        else:
            new_entries[new_entry_id] = dict(entry_state)

    for entry_id, entry_state in new_entries.items():
        for bucket in ("warnings_acknowledged", "warnings_dismissed"):
            for decision in entry_state.get(bucket, []):
                old_sig = decision.get("signature")
                if isinstance(old_sig, str):
                    new_sig = _remap_signature(old_sig, signature_map)
                    if new_sig != old_sig:
                        decision["signature"] = new_sig
                        changed += 1

    sidecar["entries"] = new_entries
    dead_letter = sidecar.setdefault("dead_letter", [])
    for entry_id in sorted(orphaned_anchors):
        dead_letter.append(_orphan_warning(entry_id, "<entry>"))
        changed += 1
    for entry_id, field_path in sorted(orphaned_fields):
        dead_letter.append(_orphan_warning(entry_id, field_path))
        changed += 1
    return sidecar, changed


def _rekey_ledger_line(
    entry: dict,
    *,
    anchor_map: dict[str, str],
    field_map: dict[tuple[str, str], tuple[str, str]],
    signature_map: dict[str, str],
) -> tuple[dict, bool]:
    changed = False
    old_entry_id = entry.get("entry_id")
    if isinstance(old_entry_id, str) and old_entry_id in anchor_map:
        entry["entry_id"] = anchor_map[old_entry_id]
        changed = True

    entry_id = str(entry.get("entry_id") or old_entry_id or "")
    field_path = _canonical_field_path(str(entry.get("field_path") or ""))
    mapped = field_map.get((entry_id, field_path)) or field_map.get((str(old_entry_id), field_path))
    if mapped is not None:
        new_entry, new_field = mapped
        if new_entry:
            entry["entry_id"] = new_entry
        entry["field_path"] = new_field
        changed = True

    sig = entry.get("producer_warning_signature")
    if isinstance(sig, str):
        new_sig = _remap_signature(sig, signature_map)
        if new_sig != sig:
            entry["producer_warning_signature"] = new_sig
            changed = True
    return entry, changed


def _rewrite_ledger(
    ledger_path: Path,
    *,
    anchor_map: dict[str, str],
    field_map: dict[tuple[str, str], tuple[str, str]],
    signature_map: dict[str, str],
    dry_run: bool,
) -> int:
    if not ledger_path.exists():
        return 0
    changed = 0
    lines = []
    for raw in ledger_path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        payload = json.loads(raw)
        payload, line_changed = _rekey_ledger_line(
            payload,
            anchor_map=anchor_map,
            field_map=field_map,
            signature_map=signature_map,
        )
        changed += int(line_changed)
        lines.append(json.dumps(payload, ensure_ascii=False))
    if changed and not dry_run:
        tmp = ledger_path.with_name(ledger_path.name + ".tmp-rekey")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp.replace(ledger_path)
    return changed


def run(
    *,
    manifests: list[Path],
    review_state_dir: Path,
    ledger_dir: Path,
    dry_run: bool = False,
) -> dict[str, int]:
    anchor_map, orphaned_anchors, field_map, orphaned_fields, signature_map = _load_manifests(manifests)
    counts = {"sidecars_changed": 0, "ledger_lines_changed": 0, "orphan_warnings": 0}

    for sidecar_path in sorted(review_state_dir.rglob("*.json")):
        sidecar = review_state.load_sidecar(sidecar_path)
        sidecar, changed = _rekey_sidecar(
            sidecar,
            anchor_map=anchor_map,
            orphaned_anchors=orphaned_anchors,
            field_map=field_map,
            orphaned_fields=orphaned_fields,
            signature_map=signature_map,
        )
        if changed:
            counts["sidecars_changed"] += 1
            counts["orphan_warnings"] += len(orphaned_anchors) + len(orphaned_fields)
            if not dry_run:
                review_state.save_sidecar(sidecar_path, sidecar)

    for ledger_path in sorted(ledger_dir.rglob("*.jsonl")):
        counts["ledger_lines_changed"] += _rewrite_ledger(
            ledger_path,
            anchor_map=anchor_map,
            field_map=field_map,
            signature_map=signature_map,
            dry_run=dry_run,
        )
    return counts


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, action="append", required=True)
    parser.add_argument("--review-state-dir", type=Path, default=REPO_ROOT / "review" / "state")
    parser.add_argument("--ledger", type=Path, default=REPO_ROOT / "review" / "corrections")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    counts = run(
        manifests=args.manifest,
        review_state_dir=args.review_state_dir,
        ledger_dir=args.ledger,
        dry_run=args.dry_run,
    )
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
