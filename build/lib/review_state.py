"""Sidecar review-state loading, derivation, validation, and human-readable dump.

Sidecar path mirrors the record path: ``data/<path>/<record>.json`` ->
``review/state/<path>/<record>.json``. Read-only consumers upgrade old sidecars
in memory via :mod:`sidecar_migrations` and never write back. Writers refuse to
mutate old-schema sidecars; ``build/tools/migrate_sidecars.py`` is the only
authorised mutation path.

Run ``python -m build.lib.review_state dump <sidecar_or_record_path>`` to see a
plain-English summary of a sidecar's contents — used by the A1 vertical-slice
loop to confirm reviewers can read sidecar state without raw JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import jsonschema

from build.lib import sidecar_migrations
from build.lib.atomic_io import write_json_atomic


SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "v1" / "review_state.schema.json"


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def derive_sidecar_path(record_path: Path | str, *, repo_root: Path | None = None) -> Path:
    """Map ``data/<...>/<record>.json`` to ``review/state/<...>/<record>.json``.

    ``record_path`` may be absolute or relative. When ``repo_root`` is None, the
    function strips a leading ``data/`` segment regardless of position; passing
    ``repo_root`` lets the caller anchor the mapping to a specific repository root.
    """
    rec = Path(record_path)
    if repo_root is not None:
        rec_abs = (Path(repo_root) / rec).resolve() if not rec.is_absolute() else rec.resolve()
        try:
            rel = rec_abs.relative_to(Path(repo_root).resolve() / "data")
        except ValueError as exc:
            raise ValueError(
                f"record path {rec_abs} is not inside {repo_root}/data"
            ) from exc
        return Path(repo_root).resolve() / "review" / "state" / rel

    parts = list(rec.parts)
    try:
        data_idx = parts.index("data")
    except ValueError as exc:
        raise ValueError(
            f"record path {rec} does not contain a 'data/' segment"
        ) from exc
    new_parts = parts[:data_idx] + ["review", "state"] + parts[data_idx + 1:]
    return Path(*new_parts) if new_parts else Path()


def empty_sidecar(
    *,
    record_path: str,
    record_resource_id: str,
    record_checksum_sha256: str,
    parser_version_seen: str,
) -> dict:
    """Return a fresh sidecar dict with zero entries and all axes ``unverified``."""
    return {
        "schema_type": "review_state",
        "schema_version": sidecar_migrations.CURRENT_VERSION,
        "record_path": record_path,
        "record_resource_id": record_resource_id,
        "record_checksum_sha256": record_checksum_sha256,
        "parser_version_seen": parser_version_seen,
        "confidence": {
            "structural_fidelity": "unverified",
            "text_fidelity": "unverified",
            "edition_provenance": "unverified",
        },
        "entries": {},
        "dead_letter": [],
    }


def load_sidecar(path: Path | str, *, schema: Mapping[str, Any] | None = None) -> dict:
    """Read a sidecar from disk and upgrade in memory to current schema.

    Read-only: the on-disk file is never rewritten. Schema validation runs after
    in-memory upgrade so an old-schema sidecar is validated against the current
    schema only after migration.
    """
    p = Path(path)
    payload = json.loads(p.read_text(encoding="utf-8"))
    upgraded = sidecar_migrations.upgrade(payload)
    eff_schema = dict(schema) if schema is not None else load_schema()
    jsonschema.validate(instance=upgraded, schema=eff_schema)
    return upgraded


def save_sidecar(path: Path | str, sidecar: Mapping[str, Any], *, schema: Mapping[str, Any] | None = None) -> None:
    """Atomically write ``sidecar`` to ``path`` after validating against the current schema."""
    eff_schema = dict(schema) if schema is not None else load_schema()
    write_json_atomic(path, sidecar, eff_schema)


def _format_timestamp(value: str) -> str:
    """Render an ISO 8601 timestamp in a friendly local form, preserving timezone."""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt.tzinfo else value


def render_dump(sidecar: Mapping[str, Any]) -> str:
    """Return a plain-English summary of a sidecar.

    The output is designed for terminals — no JSON soup. Reviewers should be able
    to read it and answer ``what's been dismissed / acknowledged / outstanding``
    without opening the underlying file.
    """
    lines: list[str] = []
    rid = sidecar.get("record_resource_id", "<unknown>")
    rpath = sidecar.get("record_path", "<unknown>")
    lines.append(f"Sidecar for {rid}")
    lines.append(f"  Record:        {rpath}")
    lines.append(f"  Schema:        {sidecar.get('schema_version', '<unknown>')}")
    lines.append(f"  Parser seen:   {sidecar.get('parser_version_seen', '<unknown>')}")
    checksum = sidecar.get("record_checksum_sha256")
    if checksum:
        lines.append(f"  Record sha256: {checksum[:12]}...{checksum[-4:]}")

    conf = sidecar.get("confidence", {}) or {}
    lines.append("")
    lines.append("Confidence axes:")
    for axis in ("structural_fidelity", "text_fidelity", "edition_provenance"):
        lines.append(f"  {axis:<22} {conf.get(axis, '<unset>')}")

    entries = sidecar.get("entries", {}) or {}
    lines.append("")
    if not entries:
        lines.append("No entry-level review activity yet.")
    else:
        lines.append(f"Entry-level activity ({len(entries)} entries):")
        for entry_id in sorted(entries):
            es = entries[entry_id] or {}
            ack = es.get("warnings_acknowledged", []) or []
            dis = es.get("warnings_dismissed", []) or []
            lines.append(f"  - {entry_id}")
            if ack:
                lines.append(f"      acknowledged ({len(ack)}):")
                for w in ack:
                    lines.append(_format_decision(w, verb="ack"))
            if dis:
                lines.append(f"      dismissed ({len(dis)}):")
                for w in dis:
                    lines.append(_format_decision(w, verb="dis"))
            last = es.get("last_reviewed_at")
            who = es.get("last_reviewer")
            if last or who:
                ts = _format_timestamp(last) if last else "<unknown>"
                lines.append(f"      last reviewed: {ts} by {who or '<unknown>'}")

    dead_letter = sidecar.get("dead_letter", []) or []
    lines.append("")
    if dead_letter:
        lines.append(f"Dead-letter buffer: {len(dead_letter)} entries (in-sidecar)")
        for entry in dead_letter[:5]:
            reason = entry.get("reason", "<unknown>")
            producer = entry.get("producer", "<unknown>")
            code = entry.get("code", "<unknown>")
            lines.append(f"  - reason={reason}  producer={producer}  code={code}")
        if len(dead_letter) > 5:
            lines.append(f"  ... and {len(dead_letter) - 5} more")
    else:
        lines.append("Dead-letter buffer: empty")

    spill_count = sidecar.get("spill_count")
    spill_path = sidecar.get("spill_path")
    if spill_count or spill_path:
        lines.append(f"Spilled to {spill_path}: {spill_count} entries (out-of-sidecar)")

    return "\n".join(lines) + "\n"


def _format_decision(decision: Mapping[str, Any], *, verb: str) -> str:
    producer = decision.get("producer", "<unknown>")
    code = decision.get("code", "<unknown>")
    reason = decision.get("reason", "<unknown>")
    note = decision.get("note")
    sig = decision.get("signature", "")
    sig_short = sig if len(sig) <= 40 else sig[:37] + "..."
    base = f"        [{verb}] {producer}/{code}  reason={reason}  sig={sig_short}"
    if note:
        base += f"\n              note: {note}"
    return base


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m build.lib.review_state",
        description="Read-only sidecar inspection.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    dump = sub.add_parser("dump", help="Print a plain-English summary of a sidecar.")
    dump.add_argument(
        "path",
        type=Path,
        help="Path to a sidecar JSON file (review/state/<...>) or a record JSON file (data/<...>).",
    )
    args = parser.parse_args(argv)

    if args.command == "dump":
        target = args.path
        # If the path looks like a record (under data/), derive its sidecar
        # path before any existence check. The record file itself is not a
        # sidecar even if it happens to exist.
        if "data" in target.parts:
            try:
                target = derive_sidecar_path(target)
            except ValueError:
                pass
        if not target.exists():
            print(f"No sidecar found at {target}", file=sys.stderr)
            return 2
        sidecar = load_sidecar(target)
        sys.stdout.write(render_dump(sidecar))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(_cli())
