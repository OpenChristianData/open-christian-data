"""Per-invocation session identity and diagnostics for the local CVW viewer."""

from __future__ import annotations

from ocd_kernel.lib.path_io import io_path, resolve_path

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import threading
from typing import Any
import uuid


SESSION_CONTRACT = "ocd-corpus-review-session-v1"
EVENT_CONTRACT = "ocd-corpus-review-event-v1"


class DiagnosticHealth:
    """One independent warning per session; never writes through the failed sink."""

    def __init__(self) -> None:
        self.degraded = False
        self.failure: dict[str, object] | None = None
        self.cleanup_failure: dict[str, object] | None = None
        self._health_lock = threading.Lock()

    def report(self, error: OSError, **context: object) -> None:
        with self._health_lock:
            detail = {"error_type": type(error).__name__, **context}
            prefix = "CVW_DIAGNOSTICS_DEGRADED "
            if self.degraded:
                if context.get("operation") != "temporary_cleanup" or self.cleanup_failure is not None:
                    return
                self.cleanup_failure = detail
                prefix = "CVW_DIAGNOSTICS_CLEANUP_FAILED "
            else:
                self.degraded = True
                self.failure = detail
            try:
                print(prefix + json.dumps(detail, sort_keys=True), file=sys.stderr)
            except OSError:
                # The in-memory health remains available even if stderr is closed.
                return


def utc_now_iso() -> str:
    """Return a machine-sortable UTC timestamp."""

    return datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def new_session_id() -> str:
    """Return an opaque identifier for one launcher invocation."""

    return uuid.uuid4().hex


def sha256_file(path: Path) -> str:
    """Hash one already-resolved file without loading it all at once."""

    digest = hashlib.sha256()
    with io_path(Path(path)).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def combined_sha256(paths: Iterable[Path]) -> str:
    """Hash a small ordered set of implementation files as one identity."""

    digest = hashlib.sha256()
    for path in paths:
        resolved = resolve_path(Path(path), strict=True)
        digest.update(resolved.name.encode("utf-8"))
        digest.update(b"\0")
        with io_path(resolved).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def make_session_descriptor(
    *,
    session_id: str,
    host: str,
    requested_port: int,
    port: int | None,
    origin: str | None,
    pid: int,
    state: str,
    catalog_sha256: str | None = None,
    candidate_sha256: Iterable[str] = (),
    implementation_sha256: str | None = None,
) -> dict[str, Any]:
    """Build the bounded, read-only descriptor exposed to agents and browsers."""

    return {
        "contract": SESSION_CONTRACT,
        "session": {
            "session_id": session_id,
            "host": host,
            "requested_port": requested_port,
            "port": port,
            "origin": origin,
            "pid": pid,
            "state": state,
            "catalog_sha256": catalog_sha256,
            "candidate_sha256": list(candidate_sha256),
            "implementation_sha256": implementation_sha256,
        },
    }


def update_session_descriptor(
    descriptor: Mapping[str, object],
    **session_fields: object,
) -> dict[str, Any]:
    """Return a descriptor copy with updated fields in its session object."""

    session = descriptor.get("session")
    if not isinstance(session, Mapping):
        raise ValueError("session descriptor must contain a session object")
    updated = dict(session)
    updated.update(session_fields)
    return {
        "contract": descriptor.get("contract", SESSION_CONTRACT),
        "session": updated,
    }


@dataclass
class SessionRecorder:
    """Append per-session JSONL events and the latest session receipt.

    The output directory is caller-selected and optional.  With no directory,
    observability remains available through launcher stdout without creating a
    second persistent CVW state store.
    """

    session_id: str
    output_dir: Path | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _event_path: Path | None = field(default=None, init=False)
    _receipt_path: Path | None = field(default=None, init=False)
    health: DiagnosticHealth = field(default_factory=DiagnosticHealth, init=False)
    origin: str | None = field(default=None, init=False)
    startup_snapshot: Mapping[str, object] | None = field(default=None, init=False)
    _strict: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", self.session_id):
            raise ValueError("session ID must be a bounded filename-safe identifier")
        if self.output_dir is None:
            return
        root = resolve_path(Path(self.output_dir).expanduser())
        if io_path(root).exists() and not io_path(root).is_dir():
            raise ValueError(f"session output is not a directory: {root}")
        io_path(root).mkdir(parents=True, exist_ok=True)
        self.output_dir = root
        self._event_path = root / f"{self.session_id}.events.jsonl"
        self._receipt_path = root / f"{self.session_id}.receipt.json"

    def initialize(self, output_dir: Path | None, descriptor: Mapping[str, object]) -> None:
        """Probe both requested sinks strictly, after launcher destination checks."""
        self.output_dir = output_dir
        self.__post_init__()
        self._strict = True
        try:
            self.write_receipt(descriptor)
            self.emit("session_start")
        finally:
            self._strict = False

    def _io_failure(self, error: OSError, operation: str, **context: object) -> None:
        if self._strict:
            raise error
        self.health.report(error, session_id=self.session_id, operation=operation, **context)

    @property
    def event_path(self) -> Path | None:
        return self._event_path

    @property
    def receipt_path(self) -> Path | None:
        return self._receipt_path

    def emit(self, event: str, **fields: object) -> None:
        """Append one structured event when a destination was requested."""

        if self._event_path is None:
            return
        payload: dict[str, object] = {
            "contract": EVENT_CONTRACT,
            "timestamp": utc_now_iso(),
            "session_id": self.session_id,
            "event": event,
            "origin": self.origin,
        }
        payload.update(fields)
        line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        try:
            with self._lock:
                with io_path(self._event_path).open("a", encoding="utf-8", newline="\n") as stream:
                    stream.write(line + "\n")
                    stream.flush()
        except OSError as error:
            self._io_failure(error, "event_append", request_id=fields.get("request_id"))

    def write_receipt(self, descriptor: Mapping[str, object]) -> None:
        """Write the latest descriptor snapshot for handoff and diagnostics."""

        if self._receipt_path is None:
            return
        payload = dict(descriptor)
        if self.startup_snapshot is not None:
            payload["startup_snapshot"] = self.startup_snapshot
        if self.health.degraded:
            payload["diagnostics"] = {"state": "degraded", "first_failure": self.health.failure, "cleanup_failure": self.health.cleanup_failure}
        # Same-directory exclusive temp + os.replace matches kernel atomic IO,
        # without importing schema/ledger machinery. Windows sharing violations
        # preserve the last receipt and degrade persistence; no durability claim.
        text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        temporary = self._receipt_path.with_name(self._receipt_path.name + f".tmp-{uuid.uuid4().hex}")
        owned = False
        try:
            with self._lock:
                with io_path(temporary).open("x", encoding="utf-8", newline="\n") as stream:
                    owned = True
                    stream.write(text + "\n")
                    stream.flush()
                os.replace(io_path(temporary), io_path(self._receipt_path))
        except OSError as error:
            self._io_failure(error, "receipt_replace")
        finally:
            if owned:
                try:
                    io_path(temporary).unlink(missing_ok=True)
                except OSError as error:
                    self.health.report(error, session_id=self.session_id, operation="temporary_cleanup", path=str(temporary))

    def paths(self) -> dict[str, str]:
        """Return serializable paths without exposing absent destinations."""

        result: dict[str, str] = {}
        if self._event_path is not None:
            result["event_log"] = str(self._event_path)
        if self._receipt_path is not None:
            result["receipt"] = str(self._receipt_path)
        return result


__all__ = [
    "EVENT_CONTRACT",
    "SESSION_CONTRACT",
    "SessionRecorder",
    "combined_sha256",
    "make_session_descriptor",
    "new_session_id",
    "sha256_file",
    "update_session_descriptor",
    "utc_now_iso",
]
