"""Canonical Unicode whitespace normalization for TEI projection contracts."""

from __future__ import annotations

import re
from typing import Literal

NormalizationMode = Literal["inline", "block"]
_UNICODE_WHITESPACE = re.compile(r"\s+", flags=re.UNICODE)


def normalize(value: str, mode: NormalizationMode) -> str:
    """Normalize Unicode whitespace without conflating inline and block text."""

    if mode == "inline":
        return _UNICODE_WHITESPACE.sub(" ", value).strip()
    if mode == "block":
        lines = [_UNICODE_WHITESPACE.sub(" ", line).strip() for line in value.split("\n")]
        return "\n".join(lines).strip()
    raise ValueError(f"Unknown normalization mode: {mode!r}")


def normalize_inline(value: str) -> str:
    return normalize(value, "inline")


def normalize_block(value: str) -> str:
    return normalize(value, "block")
