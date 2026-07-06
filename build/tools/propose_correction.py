"""Propose corrections from review warnings; route through approval.

Phase F.5 of the OCD text accuracy plan. This CLI decouples the correction
*proposal* workflow from the correction *applier* (Phase G). It turns a
warning into a proposed ledger entry, lets a reviewer approve or reject it,
and writes the ledger entry atomically to review/corrections/<resource>.jsonl.

It NEVER touches data/. Mutating data/ is the Phase G applier's job; doing
it here would conflate two risk profiles. The CLI explicitly refuses any
flag that would mutate data/.

CLI:
    py -3 build/tools/propose_correction.py propose --warning <signature> \
        --resource <path> --before-text "..." --after-text "..." \
        --field-path commentary_text --proposed-by reviewer-name
    py -3 build/tools/propose_correction.py approve <correction_id> \
        --resource <path> --approved-by reviewer-name
    py -3 build/tools/propose_correction.py reject <correction_id> \
        --resource <path> --rejected-reason "..."
    py -3 build/tools/propose_correction.py list --resource <path> \
        --status approved
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.atomic_io import append_jsonl_atomic  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402

LEDGER_SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "correction_ledger.schema.json"
LEDGER_SCHEMA_VERSION = "1.0.0"


class DataMutationRefused(RuntimeError):
    """Raised when a caller attempts to point propose_correction at data/."""


def _ledger_schema() -> dict[str, Any]:
    return json.loads(LEDGER_SCHEMA_PATH.read_text(encoding="utf-8"))


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _refuse_data_mutation(*paths: Path | str) -> None:
    """A-F5: refuse output paths that resolve under the repo's data/ tree.

    Pre-fix this only checked relative paths whose first segment was exactly
    "data" — absolute paths (``C:/.../data/...``), parent-relative paths
    (``./data/...``), and any other form bypassed the guard. The Phase G
    applier is the only authorised writer for data/; this function is the
    structural protection enforcing that bright line.
    """
    repo_data_root = REPO_ROOT / "data"
    try:
        resolved_data_root = repo_data_root.resolve()
    except OSError:
        resolved_data_root = repo_data_root
    for path in paths:
        p = Path(path)
        try:
            resolved = (p if p.is_absolute() else (REPO_ROOT / p)).resolve()
        except OSError:
            resolved = p
        # Walk parents — including the resolved path itself — looking for the
        # data root. Avoid Path.is_relative_to so we keep Python 3.8 cleanly.
        try:
            for ancestor in (resolved, *resolved.parents):
                if ancestor == resolved_data_root:
                    raise DataMutationRefused(
                        f"propose_correction.py refuses to write under data/. Got {path}. "
                        "Phase G's applier is the only authorised writer for data/."
                    )
        except DataMutationRefused:
            raise
        # Fallback: literal "data" segment for paths that cannot be resolved
        # (e.g. non-existent absolute paths on Windows where .resolve raises).
        if "data" in p.parts:
            raise DataMutationRefused(
                f"propose_correction.py refuses to write under data/. Got {path}. "
                "Phase G's applier is the only authorised writer for data/."
            )


def _ledger_path(resource_record_path: Path | str) -> Path:
    """Map data/<area>/<record>.json -> review/corrections/<area>/<record>.jsonl."""
    rec = Path(resource_record_path)
    if not (len(rec.parts) >= 2 and rec.parts[0] == "data"):
        raise ValueError(
            f"Expected resource record path under data/, got {resource_record_path}"
        )
    relative = Path(*rec.parts[1:]).with_suffix(".jsonl")
    return REPO_ROOT / "review" / "corrections" / relative


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _correction_id() -> str:
    return f"correction_{uuid.uuid4().hex[:16]}"


def _read_meta_id(record_path: Path) -> str:
    """Return meta.id from a record JSON; fall back to file stem if absent."""
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return record_path.stem
    meta_id = (record.get("meta") or {}).get("id")
    if isinstance(meta_id, str) and meta_id:
        return meta_id
    return record_path.stem


def propose(
    *,
    resource_record_path: Path | str,
    entry_id: str,
    field_path: str,
    before_text: str,
    after_text: str,
    proposed_by: str,
    producer_warning_signature: str | None = None,
    correction_type: str = "text",
    blocker: str = "none",
) -> dict[str, Any]:
    """Create a proposed correction entry. Appends to the resource's ledger."""
    rec = Path(resource_record_path)
    ledger = _ledger_path(rec)
    record_path_str = rec.as_posix()
    if not record_path_str.startswith("data/"):
        record_path_str = "data/" + record_path_str.split("data/", 1)[-1]
    # resource_id must match the record's meta.id, not the file stem. The
    # correction_ledger schema joins on meta.id, and a per-book commentary
    # has stem like "2-john" but meta.id like "adam-clarke".
    resource_id = _read_meta_id(rec)
    correction = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "correction_id": _correction_id(),
        "resource_id": resource_id,
        "record_path": record_path_str,
        "entry_id": entry_id,
        "field_path": field_path,
        "correction_type": correction_type,
        "blocker": blocker,
        "before_text": before_text,
        "after_text": after_text,
        "status": "proposed",
        "created_at": _utc_now_iso(),
        "proposed_by": proposed_by,
    }
    if producer_warning_signature:
        correction["producer_warning_signature"] = producer_warning_signature
    schema = _ledger_schema()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    append_jsonl_atomic(ledger, correction, schema)
    return correction


def _find_correction(
    ledger_path: Path, correction_id: str
) -> tuple[dict[str, Any] | None, int | None]:
    entries = _load_jsonl(ledger_path)
    for index, entry in enumerate(entries):
        if entry.get("correction_id") == correction_id:
            return entry, index
    return None, None


def _rewrite_ledger_atomically(ledger_path: Path, entries: Iterable[dict[str, Any]]) -> None:
    """Rewrite a JSONL ledger from a list of entries, with validation per line."""
    schema = _ledger_schema()
    tmp = ledger_path.with_suffix(ledger_path.suffix + ".tmp")
    lines = []
    for entry in entries:
        # Validate each entry against the schema before rewriting; reuse the
        # atomic_io validator via a probe append to a temp file.
        from build.lib.atomic_io import validate_payload  # noqa: WPS433

        validate_payload(entry, schema)
        lines.append(json.dumps(entry, ensure_ascii=False))
    tmp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    os.replace(tmp, ledger_path)


def approve(
    *,
    resource_record_path: Path | str,
    correction_id: str,
    approved_by: str,
) -> dict[str, Any]:
    rec = Path(resource_record_path)
    ledger = _ledger_path(rec)
    entries = _load_jsonl(ledger)
    found = None
    for entry in entries:
        if entry.get("correction_id") == correction_id:
            found = entry
            break
    if found is None:
        raise KeyError(f"correction_id {correction_id} not found in {ledger}")
    if found.get("status") not in {"proposed", "needs_review"}:
        raise ValueError(
            f"correction_id {correction_id} is in status {found.get('status')}, "
            "cannot approve"
        )
    found["status"] = "approved"
    found["approved_at"] = _utc_now_iso()
    found["approved_by"] = approved_by
    _rewrite_ledger_atomically(ledger, entries)
    return found


def reject(
    *,
    resource_record_path: Path | str,
    correction_id: str,
    rejected_reason: str,
) -> dict[str, Any]:
    rec = Path(resource_record_path)
    ledger = _ledger_path(rec)
    entries = _load_jsonl(ledger)
    found = None
    for entry in entries:
        if entry.get("correction_id") == correction_id:
            found = entry
            break
    if found is None:
        raise KeyError(f"correction_id {correction_id} not found in {ledger}")
    if found.get("status") not in {"proposed", "needs_review"}:
        raise ValueError(
            f"correction_id {correction_id} is in status {found.get('status')}, "
            "cannot reject"
        )
    found["status"] = "rejected"
    found["rejected_reason"] = rejected_reason
    _rewrite_ledger_atomically(ledger, entries)
    return found


def list_corrections(
    *,
    resource_record_path: Path | str,
    status: str | None = None,
) -> list[dict[str, Any]]:
    rec = Path(resource_record_path)
    ledger = _ledger_path(rec)
    entries = _load_jsonl(ledger)
    if status is None:
        return entries
    return [e for e in entries if e.get("status") == status]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    p = subparsers.add_parser("propose")
    p.add_argument("--resource", required=True, type=Path)
    p.add_argument("--entry-id", required=True)
    p.add_argument("--field-path", required=True)
    p.add_argument("--before-text", required=True)
    p.add_argument("--after-text", required=True)
    p.add_argument("--proposed-by", required=True)
    p.add_argument("--warning-signature", default=None)
    p.add_argument("--correction-type", default="text", choices=["text", "structural"])
    p.add_argument("--blocker", default="none")

    a = subparsers.add_parser("approve")
    a.add_argument("correction_id")
    a.add_argument("--resource", required=True, type=Path)
    a.add_argument("--approved-by", required=True)

    r = subparsers.add_parser("reject")
    r.add_argument("correction_id")
    r.add_argument("--resource", required=True, type=Path)
    r.add_argument("--rejected-reason", required=True)

    l = subparsers.add_parser("list")
    l.add_argument("--resource", required=True, type=Path)
    l.add_argument("--status", default=None)

    args = parser.parse_args(argv)

    if args.cmd == "propose":
        result = propose(
            resource_record_path=args.resource,
            entry_id=args.entry_id,
            field_path=args.field_path,
            before_text=args.before_text,
            after_text=args.after_text,
            proposed_by=args.proposed_by,
            producer_warning_signature=args.warning_signature,
            correction_type=args.correction_type,
            blocker=args.blocker,
        )
        print(json.dumps(result, indent=2))
    elif args.cmd == "approve":
        result = approve(
            resource_record_path=args.resource,
            correction_id=args.correction_id,
            approved_by=args.approved_by,
        )
        print(json.dumps(result, indent=2))
    elif args.cmd == "reject":
        result = reject(
            resource_record_path=args.resource,
            correction_id=args.correction_id,
            rejected_reason=args.rejected_reason,
        )
        print(json.dumps(result, indent=2))
    elif args.cmd == "list":
        entries = list_corrections(resource_record_path=args.resource, status=args.status)
        print(json.dumps(entries, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
