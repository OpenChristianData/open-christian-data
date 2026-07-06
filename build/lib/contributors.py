"""contributors.py
Utility for normalising raw contributor values to the Contributor schema shape.

Schema target (schemas/v1/_defs/contributor.schema.json):
  {"name": str, "role"?: str, "affiliation"?: str, "url"?: str}

Usage in parsers:
  from build.lib.contributors import normalize_contributors
  ...
  "contributors": normalize_contributors(config.get("contributors", []))
"""

from __future__ import annotations


def as_contributor(v: object) -> dict:
    """Coerce a single raw contributor value to a Contributor object.

    - dict  → returned as-is (assumed already in Contributor shape)
    - str   → wrapped as {"name": v}
    - other → raises TypeError
    """
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        return {"name": v}
    raise TypeError(
        f"Expected str or dict for contributor, got {type(v).__name__}: {v!r}"
    )


def normalize_contributors(raw: list) -> list:
    """Convert a list of raw contributor values (strings or dicts) to Contributor objects.

    Each item is coerced via as_contributor(). Empty list returns empty list.
    """
    return [as_contributor(c) for c in raw]
