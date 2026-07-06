"""Validate and report evidence-bearing correction ledger records."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any


STATUSES = {"proposed", "approved", "rejected", "applied"}
CORRECTION_TYPES = {"text", "structure", "metadata", "witness-note"}
REQUIRED_FIELDS = {
    "correction_id",
    "resource_id",
    "entry_id",
    "field",
    "original_value",
    "proposed_value",
    "correction_type",
    "reason",
    "evidence_source",
    "evidence_quote_or_locator",
    "reviewer",
    "status",
    "confidence",
    "created_at",
    "updated_at",
}


@dataclass(frozen=True)
class CorrectionRecord:
    correction_id: str
    resource_id: str
    entry_id: str
    field: str
    original_value: str
    proposed_value: str
    correction_type: str
    reason: str
    evidence_source: str
    evidence_quote_or_locator: str
    reviewer: str
    status: str
    confidence: float
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, str | float]:
        return self.__dict__.copy()


def load_correction_ledger(path: Path) -> list[CorrectionRecord]:
    """Load and validate a JSONL correction ledger."""
    path = Path(path)
    records: list[CorrectionRecord] = []
    if not path.exists():
        raise FileNotFoundError(f"Correction ledger not found: {path}")
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON on line {line_number}: {exc}") from exc
        records.append(_record_from_object(item, line_number))
    _validate_unique_ids(records)
    return records


def validate_correction_ledger(path: Path) -> list[CorrectionRecord]:
    return load_correction_ledger(path)


def list_corrections_by_status(path: Path, status: str) -> list[CorrectionRecord]:
    if status not in STATUSES:
        raise ValueError(f"Invalid status: {status}")
    return [record for record in load_correction_ledger(path) if record.status == status]


def render_ledger_html(records: list[CorrectionRecord]) -> str:
    rows = "\n".join(_render_record(record) for record in records)
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            "<title>Correction ledger review</title>",
            "</head>",
            "<body>",
            "<main>",
            "<h1>Correction ledger review</h1>",
            rows or "<p>No correction records.</p>",
            "</main>",
            "</body>",
            "</html>",
        ]
    )


def write_ledger_html(records: list[CorrectionRecord], output_path: Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_ledger_html(records), encoding="utf-8")
    return output_path


def _record_from_object(item: Any, line_number: int) -> CorrectionRecord:
    if not isinstance(item, dict):
        raise ValueError(f"Ledger line {line_number} must be an object.")
    missing = sorted(REQUIRED_FIELDS - set(item))
    if missing:
        raise ValueError(f"Ledger line {line_number} missing required fields: {', '.join(missing)}")

    status = _required_string(item, "status", line_number)
    if status not in STATUSES:
        raise ValueError(f"Invalid status on line {line_number}: {status}")

    correction_type = _required_string(item, "correction_type", line_number)
    if correction_type not in CORRECTION_TYPES:
        raise ValueError(f"Invalid correction_type on line {line_number}: {correction_type}")

    confidence = item.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        raise ValueError(f"Ledger line {line_number} confidence must be a number.")
    if not 0 <= float(confidence) <= 1:
        raise ValueError(f"Ledger line {line_number} confidence must be between 0 and 1.")

    created_at = _required_string(item, "created_at", line_number)
    updated_at = _required_string(item, "updated_at", line_number)
    _validate_timezone_aware(created_at, line_number, "created_at")
    _validate_timezone_aware(updated_at, line_number, "updated_at")

    return CorrectionRecord(
        correction_id=_required_string(item, "correction_id", line_number),
        resource_id=_required_string(item, "resource_id", line_number),
        entry_id=_required_string(item, "entry_id", line_number),
        field=_required_string(item, "field", line_number),
        original_value=_required_string(item, "original_value", line_number),
        proposed_value=_required_string(item, "proposed_value", line_number),
        correction_type=correction_type,
        reason=_required_string(item, "reason", line_number),
        evidence_source=_required_string(item, "evidence_source", line_number),
        evidence_quote_or_locator=_required_string(item, "evidence_quote_or_locator", line_number),
        reviewer=_required_string(item, "reviewer", line_number),
        status=status,
        confidence=float(confidence),
        created_at=created_at,
        updated_at=updated_at,
    )


def _required_string(item: dict[str, Any], field: str, line_number: int) -> str:
    value = item.get(field)
    if not isinstance(value, str):
        raise ValueError(f"Ledger line {line_number} field {field} must be a string.")
    return value


def _validate_timezone_aware(value: str, line_number: int, field: str) -> None:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise ValueError(f"Ledger line {line_number} field {field} must be timezone-aware.")


def _validate_unique_ids(records: list[CorrectionRecord]) -> None:
    seen: set[str] = set()
    for record in records:
        if record.correction_id in seen:
            raise ValueError(f"Duplicate correction_id: {record.correction_id}")
        seen.add(record.correction_id)


def _render_record(record: CorrectionRecord) -> str:
    return "\n".join(
        [
            "<article>",
            f"<h2>{escape(record.correction_id)}: {escape(record.status)}</h2>",
            f"<p>{escape(record.resource_id)} / {escape(record.entry_id)} / {escape(record.field)}</p>",
            f"<p><strong>Original:</strong> {escape(record.original_value)}</p>",
            f"<p><strong>Proposed:</strong> {escape(record.proposed_value)}</p>",
            f"<p><strong>Evidence:</strong> {escape(record.evidence_source)} - "
            f"{escape(record.evidence_quote_or_locator)}</p>",
            f"<p>{escape(record.reason)}</p>",
            "</article>",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--html", type=Path, help="Optional HTML report output path.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--status", required=True, choices=sorted(STATUSES))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "validate":
        records = validate_correction_ledger(args.ledger)
    elif args.command == "list":
        records = list_corrections_by_status(args.ledger, args.status)
    else:
        raise ValueError(f"Unsupported command: {args.command}")
    if args.html:
        write_ledger_html(records, args.html)
    print(json.dumps([record.to_dict() for record in records], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
