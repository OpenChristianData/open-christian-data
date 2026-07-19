"""In-memory single-step sidecar schema migrations.

Read-only consumers upgrade old sidecars in memory via ``upgrade`` and never write
back. Writers (``update_review_state.py``, the correction applier) refuse to mutate
old-schema sidecars and require an explicit ``migrate-sidecars`` step.

Migrations are single-step only: a migration must bump exactly one component of
the version triple by one and reset lower components to zero. Direct skips such
as ``1.0.0 -> 1.2.0`` are forbidden — the upgrade walker chains through every
intermediate. ``tests/test_sidecar_migrations.py`` includes a chain-equivalence
test that asserts every reachable end-state matches a hand-written expected
fixture.
"""

from __future__ import annotations

import re
from typing import Callable, Mapping, MutableMapping


_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


class MigrationError(Exception):
    """Raised when a sidecar cannot be migrated."""


# Current writer schema version. Bump together with ``ocd_kernel/schemas/v1/review_state.schema.json``.
CURRENT_VERSION = "1.0.0"


# Registry of single-step migrations: (from_version, to_version) -> callable.
# Each callable receives the sidecar dict and returns a new dict at to_version.
# A1 ships an empty registry: 1.0.0 has no successor yet. Future versions add
# single-step entries here.
MIGRATIONS: dict[tuple[str, str], Callable[[Mapping], dict]] = {}


def _parse_version(value: str) -> tuple[int, int, int]:
    match = _VERSION_RE.match(value)
    if not match:
        raise MigrationError(f"invalid version string: {value!r}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def is_single_step(from_version: str, to_version: str) -> bool:
    """Return True iff ``from_version -> to_version`` is a valid single-step bump.

    Valid bumps:
      * major: ``X.Y.Z -> (X+1).0.0``
      * minor: ``X.Y.Z -> X.(Y+1).0``
      * patch: ``X.Y.Z -> X.Y.(Z+1)``
    """
    a = _parse_version(from_version)
    b = _parse_version(to_version)
    if b == (a[0] + 1, 0, 0):
        return True
    if b == (a[0], a[1] + 1, 0):
        return True
    if b == (a[0], a[1], a[2] + 1):
        return True
    return False


def validate_registry(migrations: Mapping[tuple[str, str], Callable]) -> None:
    """Raise ``MigrationError`` when the registry contains a non-single-step entry."""
    for (from_v, to_v) in migrations:
        if not is_single_step(from_v, to_v):
            raise MigrationError(
                f"registry entry {from_v!r}->{to_v!r} is not a single-step bump"
            )


def chain(
    from_version: str,
    to_version: str,
    *,
    migrations: Mapping[tuple[str, str], Callable] | None = None,
) -> list[tuple[str, str]]:
    """Return the list of single-step (from, to) edges required to go from ``from_version`` to ``to_version``.

    Raises ``MigrationError`` when no path exists in the supplied registry. The
    chain is monotonic: each step must be a single-step bump that exists in
    the registry. Direct skips raise even when the endpoints exist.
    """
    if from_version == to_version:
        return []
    reg = MIGRATIONS if migrations is None else migrations
    validate_registry(reg)
    by_from: dict[str, str] = {}
    for (f, t) in reg:
        if f in by_from and by_from[f] != t:
            raise MigrationError(
                f"registry has ambiguous successor for {f!r}: {by_from[f]!r} and {t!r}"
            )
        by_from[f] = t

    steps: list[tuple[str, str]] = []
    current = from_version
    visited: set[str] = set()
    while current != to_version:
        if current in visited:
            raise MigrationError(f"cycle detected at {current!r}")
        visited.add(current)
        nxt = by_from.get(current)
        if nxt is None:
            raise MigrationError(
                f"no migration path from {from_version!r} to {to_version!r} (stuck at {current!r})"
            )
        steps.append((current, nxt))
        current = nxt
    return steps


def upgrade(
    sidecar: Mapping,
    *,
    target_version: str = CURRENT_VERSION,
    migrations: Mapping[tuple[str, str], Callable] | None = None,
) -> dict:
    """Return ``sidecar`` upgraded to ``target_version`` by chaining single-step migrations.

    Raises ``MigrationError`` when the sidecar's ``schema_version`` is newer than
    ``target_version`` (downgrades are forbidden) or when no chain exists.
    """
    if "schema_version" not in sidecar:
        raise MigrationError("sidecar is missing schema_version")
    current = sidecar["schema_version"]
    if _parse_version(current) > _parse_version(target_version):
        raise MigrationError(
            f"sidecar schema_version {current!r} is newer than target {target_version!r}; "
            "downgrade is not supported"
        )
    if current == target_version:
        # Return a shallow copy so the caller can safely mutate.
        return dict(sidecar)
    reg = MIGRATIONS if migrations is None else migrations
    steps = chain(current, target_version, migrations=reg)
    working: MutableMapping = dict(sidecar)
    for (f, t) in steps:
        step = reg[(f, t)]
        working = dict(step(working))
        working["schema_version"] = t
    return dict(working)
