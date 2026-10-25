"""Additive package locator sidecar preserving existing public row identity."""
from __future__ import annotations

import hashlib
import json


def _read(content: bytes) -> list[dict]:
    rows = [json.loads(line) for line in content.decode("utf-8").splitlines() if line.strip()]
    ids = [row["record_id"] for row in rows]
    if any(not isinstance(value, str) or not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("Package contains invalid or duplicate public record IDs")
    return rows


def build_packaging_crosswalk(old: bytes, new: bytes) -> dict:
    """Only packaging bytes may vary; semantic fields and occurrence order cannot."""
    before, after = _read(old), _read(new)
    # Canonical JSON also distinguishes bool/int and rejects NaN.
    def canonical(rows):
        return json.dumps(rows, sort_keys=True, allow_nan=False, separators=(",", ":"))
    if canonical(before) != canonical(after):
        raise ValueError("Packaging changed public occurrence inventory, order, or meaning")
    old_lines = [n for n, line in enumerate(old.decode().splitlines(), 1) if line.strip()]
    new_lines = [n for n, line in enumerate(new.decode().splitlines(), 1) if line.strip()]
    return {"contract": "ocd-packaging-crosswalk-v1",
            "old_sha256": hashlib.sha256(old).hexdigest(),
            "new_sha256": hashlib.sha256(new).hexdigest(),
            "occurrences": [{"record_id": row["record_id"], "disposition": "retain",
                             "old_line": old_line, "new_line": new_line}
                            for row, old_line, new_line in zip(before, old_lines, new_lines, strict=True)]}


def read_repackaged_rows(old: bytes, new: bytes, crosswalk: dict) -> list[dict]:
    """Consumer validates exact package binding before returning unchanged rows."""
    if crosswalk != build_packaging_crosswalk(old, new):
        raise ValueError("Package locator crosswalk mismatch")
    return _read(new)
