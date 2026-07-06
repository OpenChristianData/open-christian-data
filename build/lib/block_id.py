"""Stable content-hash block ids for layered array fields."""

from __future__ import annotations

import hashlib


def block_id(normalised_block_text: str, disambiguator: int = 0) -> str:
    """Return the Phase C block id for a normalised text block.

    The first occurrence of a block uses the first 16 hex characters of its
    SHA-256. Later identical blocks append ``.<n>`` where ``n`` is the
    occurrence disambiguator.
    """
    if disambiguator < 0:
        raise ValueError("disambiguator must be >= 0")
    base = hashlib.sha256(normalised_block_text.encode("utf-8")).hexdigest()[:16]
    if disambiguator == 0:
        return base
    return f"{base}.{disambiguator}"


__all__ = ["block_id"]
