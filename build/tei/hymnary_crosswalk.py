"""Exact-acquisition Hymnary correspondence; keys do not identify compositions.

Full-field equality is evidence for a unique correspondence only. Repeated
identical rows remain separate source-bound occurrences with unknown mappings.
"""
from __future__ import annotations

import hashlib
import json

from build.tei.hymnary_csv import read_rows


def inventory(content: bytes) -> dict:
    """Retain every occurrence, binding its locator to the exact CSV bytes."""
    rows = iter(read_rows(content))
    header = next(rows, None)
    if header is None or len(header.fields) != 8:
        raise ValueError("Hymnary crosswalk requires eight source columns")
    columns = [field.value for field in header.fields]
    if len(set(columns)) != 8:
        raise ValueError("Hymnary column labels must be distinct")
    digest = hashlib.sha256(content).hexdigest()
    occurrences = []
    for ordinal, row in enumerate(rows, 1):
        if len(row.fields) != 8:
            raise ValueError(f"Hymnary occurrence {ordinal}: expected eight fields")
        evidence = [columns, [field.value for field in row.fields]]
        key = hashlib.sha256(json.dumps(evidence, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        occurrences.append({
            "source_key": f"sha256:{digest}#bytes-{row.start}-{row.end}",
            "ordinal": ordinal, "start": row.start, "end": row.end,
            "field_match_key": key,
        })
    return {"sha256": digest, "columns": columns, "occurrences": occurrences}


def build_crosswalk(old: bytes, new: bytes) -> dict:
    """Declare unique exact-field matches and preserve all ambiguity explicitly."""
    before, after = inventory(old), inventory(new)
    if before["columns"] != after["columns"]:
        raise ValueError("Hymnary source columns changed")
    old_groups: dict[str, list[str]] = {}
    new_groups: dict[str, list[str]] = {}
    for source, groups in ((before, old_groups), (after, new_groups)):
        for row in source["occurrences"]:
            groups.setdefault(row["field_match_key"], []).append(row["source_key"])
    mappings = []
    for row in before["occurrences"]:
        key = row["field_match_key"]
        candidates = new_groups.get(key, [])
        unique = len(old_groups[key]) == len(candidates) == 1
        mappings.append({"old_source_key": row["source_key"],
                         "new_source_key": candidates[0] if unique else None,
                         "candidate_source_keys": candidates,
                         "disposition": "retain" if unique else "unknown"})
    return {"contract": "ocd-hymnary-acquisition-crosswalk-v1", "old": before,
            "new": after, "mappings": mappings, "composition_identity": None}


def verify_crosswalk(old: bytes, new: bytes, crosswalk: dict) -> None:
    """Recompute evidence from supplied source bytes; reject stale/wrong mappings."""
    if crosswalk != build_crosswalk(old, new):
        raise ValueError("Hymnary crosswalk differs from exact source correspondence")
