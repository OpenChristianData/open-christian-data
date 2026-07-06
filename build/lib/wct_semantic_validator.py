"""Semantic validation for word-confusion-table-v1 records.

Pure JSON Schema cannot bind segmentation_relation to token_span_type, so the
invariant from the reconciled arch B design (section 2) is enforced here and
covered by tests, not by a JSON Schema keyword. token_span_type carries the
categorical; segmentation_relation carries the cardinality; the two must agree.

This module is the home for further WCT cross-field rules as they are added.
"""

from __future__ import annotations

# token_span_type -> the only segmentation_relation that is consistent with it.
# skip => gap, exact => 1:1, split => 1:n, merge => n:1,
# insertion => 1:1 (on the inserted token). Reconciled arch B design section 2.
_EXPECTED_RELATION = {
    "exact": "1:1",
    "split": "1:n",
    "merge": "n:1",
    "skip": "gap",
    "insertion": "1:1",
}


def validate_span_record(span_record: dict) -> list[str]:
    """Return invariant-violation messages for a single span record (empty = ok)."""
    errors: list[str] = []
    span_type = span_record.get("token_span_type")
    relation = span_record.get("segmentation_relation")
    expected = _EXPECTED_RELATION.get(span_type)
    if expected is not None and relation != expected:
        span_id = span_record.get("span_record_id", "<unknown>")
        errors.append(
            f"span_record {span_id!r}: token_span_type {span_type!r} requires "
            f"segmentation_relation {expected!r}, got {relation!r}"
        )
    return errors


def validate_page(page: dict) -> list[str]:
    """Return all segmentation-invariant violations across a WCT page (empty = ok)."""
    errors: list[str] = []
    for position in page.get("positions", []):
        for span_record in position.get("span_records", []):
            errors.extend(validate_span_record(span_record))
    return errors
