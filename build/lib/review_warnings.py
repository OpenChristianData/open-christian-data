"""Compatibility shim. New callers should use build.lib.warning_producers directly."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ocd_kernel.lib.text_extractor import effective_resource_type
from build.lib.warning_producers import discover_producers, run_all_producers


SEVERITIES = ("info", "warning", "error")


@dataclass(frozen=True)
class ReviewWarning:
    code: str
    severity: str
    message: str
    entry_id: str | None = None
    field: str | None = None
    evidence: str | None = None

    def to_record(self) -> dict[str, str | None]:
        return asdict(self)


def collect_review_warnings(entries: list[dict[str, Any]]) -> list[ReviewWarning]:
    record = {"meta": {"schema_type": "commentary", "id": "shim-call"}, "data": entries}
    resource_type = effective_resource_type(record, _schemas_dir())
    meta = {"resource_id": "shim-call", "resource_type": resource_type, "record_path": None}
    producer_results = run_all_producers(record, meta, producers=discover_producers())
    warnings: list[ReviewWarning] = []
    for producer_warnings in producer_results.values():
        for warning in producer_warnings:
            if warning.get("ephemeral"):
                continue
            warnings.append(_to_review_warning(warning))
    warnings.extend(_legacy_compatibility_warnings(entries))
    return warnings


def warning_counts_by_severity(warnings: list[ReviewWarning]) -> dict[str, int]:
    counts = {severity: 0 for severity in SEVERITIES}
    for warning in warnings:
        counts[warning.severity] = counts.get(warning.severity, 0) + 1
    return counts


def _to_review_warning(warning: dict[str, Any]) -> ReviewWarning:
    evidence = warning.get("evidence")
    code = str(warning["code"])
    if code == "archaic_variant":
        code = "historical_lexicon_variant"
    return ReviewWarning(
        code=code,
        severity=str(warning["severity"]),
        message=str(warning["message"]),
        entry_id=warning.get("entry_id"),
        field=warning.get("field_path"),
        evidence=None if evidence is None else _evidence_to_string(evidence),
    )


def _legacy_compatibility_warnings(entries: list[dict[str, Any]]) -> list[ReviewWarning]:
    warnings: list[ReviewWarning] = []
    for index, entry in enumerate(entries, start=1):
        entry_id = _entry_id(entry)
        entry_label = entry_id or f"entry {index}"
        commentary_text = entry.get("commentary_text")
        if not isinstance(commentary_text, str) or not commentary_text.strip():
            warnings.append(
                ReviewWarning(
                    code="missing_commentary_text",
                    severity="error",
                    message=f"{entry_label}: missing or blank commentary_text.",
                    entry_id=entry_id,
                    field="commentary_text",
                )
            )
        else:
            word_count = len(commentary_text.split())
            declared_word_count = entry.get("word_count")
            if isinstance(declared_word_count, int) and declared_word_count != word_count:
                warnings.append(
                    ReviewWarning(
                        code="word_count_mismatch",
                        severity="warning",
                        message=f"{entry_label}: word_count does not match commentary_text.",
                        entry_id=entry_id,
                        field="word_count",
                        evidence=f"declared={declared_word_count}; actual={word_count}",
                    )
                )
            if "word_count" in entry and not isinstance(declared_word_count, int):
                warnings.append(
                    ReviewWarning(
                        code="word_count_not_integer",
                        severity="warning",
                        message=f"{entry_label}: word_count is present but is not an integer.",
                        entry_id=entry_id,
                        field="word_count",
                        evidence=type(declared_word_count).__name__,
                    )
                )
        warnings.extend(_legacy_structure_warnings(entry, entry_label, entry_id))
        warnings.extend(_legacy_metadata_warnings(entry, entry_label, entry_id))
    return warnings


def _legacy_structure_warnings(
    entry: dict[str, Any],
    entry_label: str,
    entry_id: str | None,
) -> list[ReviewWarning]:
    warnings: list[ReviewWarning] = []
    is_intro = entry.get("verse_range") == "intro"
    verse_range_osis = entry.get("verse_range_osis")
    if not is_intro and not verse_range_osis:
        warnings.append(
            ReviewWarning(
                code="verse_entry_missing_verse_range_osis",
                severity="warning",
                message=f"{entry_label}: verse entry has no verse_range_osis.",
                entry_id=entry_id,
                field="verse_range_osis",
            )
        )
    if is_intro and verse_range_osis:
        warnings.append(
            ReviewWarning(
                code="intro_entry_unexpected_verse_range_osis",
                severity="warning",
                message=f"{entry_label}: intro entry has unexpected verse_range_osis.",
                entry_id=entry_id,
                field="verse_range_osis",
                evidence=str(verse_range_osis),
            )
        )
    return warnings


def _legacy_metadata_warnings(
    entry: dict[str, Any],
    entry_label: str,
    entry_id: str | None,
) -> list[ReviewWarning]:
    warnings: list[ReviewWarning] = []
    cross_references = entry.get("cross_references")
    if cross_references is not None and not isinstance(cross_references, list):
        warnings.append(
            ReviewWarning(
                code="cross_references_not_list",
                severity="warning",
                message=f"{entry_label}: cross_references is present but is not a list.",
                entry_id=entry_id,
                field="cross_references",
                evidence=type(cross_references).__name__,
            )
        )
    elif isinstance(cross_references, list):
        for ref_index, ref in enumerate(cross_references, start=1):
            if not isinstance(ref, str):
                warnings.append(
                    ReviewWarning(
                        code="non_string_cross_reference",
                        severity="warning",
                        message=f"{entry_label}: cross reference {ref_index} is not a string.",
                        entry_id=entry_id,
                        field="cross_references",
                        evidence=type(ref).__name__,
                    )
                )

    return warnings


def _entry_id(entry: dict[str, Any]) -> str | None:
    entry_id = entry.get("entry_id")
    if isinstance(entry_id, str) and entry_id.strip():
        return entry_id
    return None


def _evidence_to_string(evidence: Any) -> str:
    if isinstance(evidence, dict):
        return "; ".join(f"{key}={value}" for key, value in sorted(evidence.items()))
    return str(evidence)


def _schemas_dir():
    from pathlib import Path

    return Path(__file__).resolve().parents[2] / "schemas" / "v1"
