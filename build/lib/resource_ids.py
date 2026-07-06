"""Canonical meta.id resolver.

All registry joins (producer registry, sidecar loader, ledger applier, dashboard)
key off ``meta.id``. This module is the one place that knows how to derive
``meta.id`` from a record dict, and how to map an ``entry_id`` back to its
resource identifier.

``meta.id`` is kebab-case and is the source of truth. ``entry_id`` first dotted
segment is treated as an opaque parser convention derived from ``meta.id`` —
parsers may choose any prefix they like provided the mapping is documented per
parser. The default mapping is identity (``meta.id`` itself), which the SH and
Clarke parsers follow.
"""

from __future__ import annotations

import re
from typing import Any, Mapping


_KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def resource_id_of(record: Mapping[str, Any]) -> str:
    """Return the canonical resource id (``meta.id``) for a record dict.

    Raises ``KeyError`` when ``meta.id`` is missing; raises ``ValueError`` when
    the value is not a non-empty string.
    """
    try:
        meta = record["meta"]
        rid = meta["id"]
    except (KeyError, TypeError) as exc:
        raise KeyError("record is missing meta.id") from exc
    if not isinstance(rid, str) or not rid:
        raise ValueError("meta.id must be a non-empty string")
    return rid


def is_valid_resource_id(value: str) -> bool:
    """Return True when ``value`` is a valid kebab-case meta.id."""
    return isinstance(value, str) and bool(_KEBAB_RE.match(value))


def entry_id_prefix(entry_id: str) -> str:
    """Return the first dotted segment of an ``entry_id``.

    The first dotted segment is the parser's resource-prefix convention. For
    SH it is ``schaff-herzog``; for Clarke it is ``clarke``. The convention
    is parser-defined; consumers should not infer ``meta.id`` from the prefix
    without checking the parser's documented mapping.
    """
    if not isinstance(entry_id, str) or not entry_id:
        raise ValueError("entry_id must be a non-empty string")
    return entry_id.split(".", 1)[0]
