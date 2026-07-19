"""Emit writer manifests for runs that mutate ``data/``.

Every staged ``data/*.json`` change must be paired with a
``review/writer-manifests/<run_id>.json`` carrying a registered ``writer_identity``
(enforced by ``build/tools/check_writer_manifest_gate.py`` in pre-commit). Before this
module the only emitters were one-off tools under ``build/tools/``, so parsers had no
supported way to produce one -- 33 of 55 parsers could not legally write ``data/``.

Why a context manager rather than a post-hoc generator: the manifest records
``before_sha256``/``after_sha256`` per path. Once a writer has overwritten a file its
"before" content is gone, so anything running afterwards can only guess -- reading the
hash from git HEAD is wrong whenever the working tree already diverges from HEAD. The
before-hash must be captured *around* the write, which forces the wrapping shape.

A generator that scanned staged files and emitted a matching manifest would pass the
gate while certifying whatever happened to be on disk, including a bad write. That is a
rubber stamp, not provenance: it can never fail, because it never asks a question it
could answer wrongly. This module computes real hashes and validates its own output.

Usage::

    from build.lib import writer_manifest

    with writer_manifest.run(
        writer_identity="naves_topical_parser",
        writer_version="build/parsers/naves_topical.py@v1.1.0",
        data_paths=[output_path],
    ) as manifest_run:
        entries = parse_and_write(output_path)
        manifest_run.record_delta(output_path, entries_changed=41, fields_changed=978)

The manifest is written only on clean exit. If the body raises, no manifest appears --
matching ``partial_completion_policy: all_or_nothing``, so a half-finished run cannot
leave provenance claiming it completed.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Mapping, Sequence

from build.lib.paths import REPO_ROOT
from build.lib.writer_identities import is_authorised, producer_type_for
from ocd_kernel.lib.atomic_io import write_json_atomic

SCHEMA_VERSION = "1.0.0"
MANIFESTS_DIR = REPO_ROOT / "review" / "writer-manifests"
SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "writer_manifest.schema.json"

# A writer that regenerates a whole data file owns both top-level blocks. This is the
# established convention for full-file parser runs (19 manifests in review/ use it); the
# narrow per-field form (e.g. "/data/*/layers/commentary_text/display") belongs to the
# correction applier, which mutates individual fields rather than rewriting the file.
FULL_FILE_FIELD_PATHS: tuple[str, ...] = ("/meta", "/data")

__all__ = ("run", "ManifestRun", "diff_counts", "FULL_FILE_FIELD_PATHS")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(path: Path, repo_root: Path) -> str:
    """Repo-relative POSIX path. Absolute paths in committed JSON leak the OS username
    and trip the identity gate (OUT-03)."""
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


@dataclass
class ManifestRun:
    """Handle yielded by :func:`run`. Collects per-path delta counts during the run."""

    run_id: str
    writer_identity: str
    writer_version: str
    started_at: str
    repo_root: Path
    data_paths: tuple[Path, ...]
    allowed_field_paths: tuple[str, ...]
    partial_completion_policy: str
    renames: tuple[dict, ...]
    _before: dict[str, str | None] = field(default_factory=dict)
    _deltas: dict[str, dict[str, int]] = field(default_factory=dict)

    def record_delta(self, path: Path | str, *, entries_changed: int, fields_changed: int) -> None:
        """Record the intended change size for ``path``.

        The schema permits exactly ``entries_changed`` and ``fields_changed``; both are
        required per path. Counts are the writer's own claim about what it did -- the A2
        gate will compare them against the real diff, so they must be measured, not
        guessed.
        """
        if entries_changed < 0 or fields_changed < 0:
            raise ValueError(
                f"delta counts must be non-negative: {path} "
                f"entries_changed={entries_changed} fields_changed={fields_changed}"
            )
        key = _relative(Path(path), self.repo_root)
        if key not in self._before:
            raise ValueError(
                f"record_delta called for a path not declared in data_paths: {key}. "
                f"Declared: {sorted(self._before)}"
            )
        self._deltas[key] = {"entries_changed": entries_changed, "fields_changed": fields_changed}

    def _capture_before(self) -> None:
        for path in self.data_paths:
            key = _relative(path, self.repo_root)
            self._before[key] = _sha256(path) if path.exists() else None

    def _build(self) -> dict:
        checksums: dict[str, dict[str, str | None]] = {}
        for path in self.data_paths:
            key = _relative(path, self.repo_root)
            if not path.exists():
                raise FileNotFoundError(
                    f"declared data_path was not written by the run: {key}. "
                    "Every declared path must exist on clean exit."
                )
            checksums[key] = {"before_sha256": self._before[key], "after_sha256": _sha256(path)}
        missing = sorted(set(checksums) - set(self._deltas))
        if missing:
            raise ValueError(
                "record_delta was not called for: "
                + ", ".join(missing)
                + ". The manifest requires an explicit delta claim per data path."
            )
        return {
            "schema_version": SCHEMA_VERSION,
            "writer": producer_type_for(self.writer_identity),
            "writer_version": self.writer_version,
            "writer_identity": self.writer_identity,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "data_paths": sorted(checksums),
            "checksums": checksums,
            "expected_delta_counts": self._deltas,
            "allowed_field_paths": list(self.allowed_field_paths),
            "partial_completion_policy": self.partial_completion_policy,
            "renames": [dict(item) for item in self.renames],
        }


def _index(entries: Sequence[Mapping], key: Callable[[Mapping], str], side: str) -> dict[str, Mapping]:
    """Index entries by key, refusing a key that is not unique.

    A non-unique key silently collapses entries into one another, so a change to a
    collapsed entry vanishes from the delta and the manifest under-reports. Nave's
    ``topic`` is the live example: REVERENCE and SIN each appear twice, while
    ``entry_id`` is unique. Fail loudly rather than emit a quietly wrong count.
    """
    indexed: dict[str, Mapping] = {}
    duplicates: list[str] = []
    for item in entries:
        item_key = key(item)
        if item_key in indexed:
            duplicates.append(item_key)
        indexed[item_key] = item
    if duplicates:
        raise ValueError(
            f"diff_counts key is not unique across the {side} payload: "
            f"{sorted(set(duplicates))[:5]} (and {max(0, len(set(duplicates)) - 5)} more). "
            "Pick a key that uniquely identifies an entry."
        )
    return indexed


def diff_counts(
    before: Mapping | None,
    after: Mapping,
    *,
    key: Callable[[Mapping], str],
) -> tuple[int, int]:
    """Measure ``(entries_changed, fields_changed)`` between two ``{meta, data}`` envelopes.

    The schema permits exactly these two counts, and the A2 gate will compare them
    against the real diff -- so they must be measured against what is actually on disk,
    not asserted. A full-file regeneration rewrites every entry, but "every entry was
    rewritten" is not the same claim as "every entry changed", and only the second is
    reviewable.

    ``key`` extracts each entry's identity, since entry order is not stable across runs
    and matching by index would report a single insertion as a change to every entry
    after it.
    """
    after_by_key = _index(after.get("data", []), key, "after")
    before_by_key = _index((before or {}).get("data", []), key, "before")

    entries_changed = 0
    fields_changed = 0
    for entry_key in set(before_by_key) | set(after_by_key):
        old = before_by_key.get(entry_key)
        new = after_by_key.get(entry_key)
        if old == new:
            continue
        entries_changed += 1
        old_fields = old or {}
        new_fields = new or {}
        fields_changed += sum(
            1
            for name in set(old_fields) | set(new_fields)
            if old_fields.get(name) != new_fields.get(name)
        )
    return entries_changed, fields_changed


def _schema() -> dict:
    """The manifest schema, used to validate this emitter's output before it lands.

    76 of the 89 manifests already in ``review/`` do not validate against their own
    schema, because nothing has ever checked them: the pre-commit gate only verifies
    presence and a registered identity. Validating on write keeps this emitter from
    adding to that pile, and makes the A2 rich-validation work a no-op for its output
    rather than a migration.
    """
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@contextmanager
def run(
    *,
    writer_identity: str,
    writer_version: str,
    data_paths: Sequence[Path | str],
    allowed_field_paths: Sequence[str] = FULL_FILE_FIELD_PATHS,
    run_id: str | None = None,
    renames: Sequence[dict] = (),
    partial_completion_policy: str = "all_or_nothing",
    repo_root: Path = REPO_ROOT,
    manifests_dir: Path | None = None,
) -> Iterator[ManifestRun]:
    """Wrap a run that mutates ``data/`` and emit its writer manifest on clean exit.

    Raises immediately if ``writer_identity`` is not registered in
    ``build/lib/writer_identities.py`` -- an unregistered identity would be rejected by
    pre-commit anyway, and failing here points at the cause instead of at a blocked
    commit hours later (REL-02).
    """
    if not is_authorised(writer_identity):
        raise ValueError(
            f"writer_identity {writer_identity!r} is not registered in "
            "build/lib/writer_identities.py. Register it in the same commit that ships "
            "its first manifest-emitting run."
        )
    if not data_paths:
        raise ValueError("data_paths must name at least one path under data/.")
    if not allowed_field_paths:
        raise ValueError("allowed_field_paths must name at least one JSON Pointer.")

    resolved = tuple(Path(p) for p in data_paths)
    for path in resolved:
        rel = _relative(path, repo_root)
        if not rel.startswith("data/"):
            raise ValueError(f"data_paths entries must live under data/: {rel}")

    handle = ManifestRun(
        run_id=run_id or uuid.uuid4().hex,
        writer_identity=writer_identity,
        writer_version=writer_version,
        started_at=datetime.now(timezone.utc).isoformat(),
        repo_root=repo_root,
        data_paths=resolved,
        allowed_field_paths=tuple(allowed_field_paths),
        partial_completion_policy=partial_completion_policy,
        renames=tuple(renames),
    )
    handle._capture_before()

    yield handle

    # Only reached on clean exit: an exception propagates and writes no manifest, so a
    # failed run cannot leave provenance claiming it finished.
    manifest = handle._build()
    target_dir = manifests_dir or MANIFESTS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    # write_json_atomic schema-validates before os.replace, so an invalid manifest
    # raises and leaves nothing behind rather than landing unchecked.
    write_json_atomic(target_dir / f"{handle.run_id}.json", manifest, _schema())
