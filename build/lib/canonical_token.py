from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def _canonical_bytes(obj: Any) -> bytes:
    """Produce deterministic UTF-8 JSON bytes for hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def edition_position_ordinal(wct_page: Mapping[str, Any], position_id: str) -> int | None:
    """Return the body-track reading-order index for a WCT position."""
    reading_order = wct_page["reading_order"]
    try:
        return reading_order.index(position_id)
    except ValueError:
        # Absence from reading_order means the position is not a body token.
        return None


def canonical_token_id(
    work_id: str,
    volume_id: str,
    edition_page_key: Mapping[str, Any],
    edition_position_ordinal: int,
) -> str:
    """Return the canonical scan-independent token id."""
    if not isinstance(edition_position_ordinal, int) or isinstance(edition_position_ordinal, bool):
        raise ValueError("edition_position_ordinal must be a non-negative int")
    if edition_position_ordinal < 0:
        raise ValueError("edition_position_ordinal must be a non-negative int")

    normalized = {
        "work_id": str(work_id),
        "volume_id": str(volume_id),
        "edition_page_key": {
            "section": str(edition_page_key["section"]),
            "anchor": int(edition_page_key["anchor"]),
            "ordinal": int(edition_page_key["ordinal"]),
        },
        "edition_position_ordinal": edition_position_ordinal,
    }
    return "ct-sha256:" + hashlib.sha256(_canonical_bytes(normalized)).hexdigest()
