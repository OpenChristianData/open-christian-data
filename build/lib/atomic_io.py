"""Atomic JSON and JSONL writers with schema validation.

JSON files (sidecars, ledger files, writer manifests):
    1. Serialise to JSON bytes.
    2. Re-parse and JSON-schema-validate against the writer's known-current schema.
    3. Write to a temp file in the same directory.
    4. ``os.replace`` into final position.

A schema-invalid payload fails at step 2 before any disk write; the on-disk file
is unchanged.

JSONL files (audit log, ledger journal):
    1. Acquire a ``.lock`` sentinel (atomic O_CREAT | O_EXCL) containing
       ``{pid, hostname, created_at, target_path}``. 30s acquire timeout; locks
       older than 60s whose owning pid is dead on this host are broken with an
       audit hook.
    2. Append one JSON-encoded line.
    3. JSON-schema-validate the appended line against the line schema.
    4. Release the lock; on validation failure, truncate back to the pre-append
       length so the appended line is unwound.

Crash mid-write leaves the previous good file intact.
validate_payload validates a payload against a JSON schema and raises
SchemaValidationError on failure.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

import jsonschema


# Public knobs (caller may override per-call via keyword args)
LOCK_ACQUIRE_TIMEOUT_SECONDS = 30.0
LOCK_STALE_THRESHOLD_SECONDS = 60.0
LOCK_POLL_INTERVAL_SECONDS = 0.1


# Delays for os.replace retries when a cloud-sync client holds the target open.
# Three attempts cover a typical Sync.com / OneDrive sync pass (~1s total).
_SYNC_RETRY_DELAYS = (0.1, 0.3, 0.6)


def _is_sync_lock_error(exc: OSError) -> bool:
    """True when os.replace is blocked by a cloud-sync client holding the target."""
    if sys.platform == "win32":
        return getattr(exc, "winerror", None) == 5  # ERROR_ACCESS_DENIED
    return exc.errno == 13  # EACCES


def _replace_with_retry(src: Path, dst: Path) -> None:
    """os.replace with retries for transient cloud-sync lock contention.

    Sync.com briefly holds an exclusive open on recently-written files while
    uploading. os.replace raises OSError(WinError 5 / EACCES) in that window.
    """
    for delay in (*_SYNC_RETRY_DELAYS, None):
        try:
            os.replace(src, dst)
            return
        except OSError as exc:
            if delay is not None and _is_sync_lock_error(exc):
                time.sleep(delay)
            else:
                raise


class AtomicWriteError(Exception):
    """Raised when atomic write fails before the visible file would change."""


class SchemaValidationError(AtomicWriteError):
    """Raised when payload does not validate against the supplied schema."""


class LockAcquireTimeout(AtomicWriteError):
    """Raised when a JSONL lock cannot be acquired within the timeout."""


class LockBrokenError(AtomicWriteError):
    """Raised when stale-lock breaking fails (e.g. cross-host stale lock)."""


@dataclass(frozen=True)
class LockMetadata:
    pid: int
    hostname: str
    created_at: str  # ISO 8601 UTC
    target_path: str


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def validate_payload(payload: Any, schema: Mapping[str, Any]) -> None:
    try:
        jsonschema.validate(instance=payload, schema=dict(schema))
    except jsonschema.ValidationError as exc:
        raise SchemaValidationError(str(exc)) from exc


def write_json_atomic(
    target_path: Path | str,
    payload: Mapping[str, Any],
    schema: Mapping[str, Any],
    *,
    indent: int | None = 2,
) -> None:
    """Atomically write ``payload`` as JSON to ``target_path`` after schema validation.

    On schema-validation failure, raises ``SchemaValidationError`` and leaves the
    existing file (if any) untouched. On any other failure mid-write, ``os.replace``
    is not called so the existing file remains the canonical version.
    """
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    text = json.dumps(payload, indent=indent, ensure_ascii=False, sort_keys=False)
    # Re-parse and validate. Re-parsing catches the rare case where a custom
    # encoder hook would produce a string that does not round-trip.
    reparsed = json.loads(text)
    validate_payload(reparsed, schema)

    tmp = target.with_name(target.name + f".tmp-{os.getpid()}-{int(time.time_ns())}")
    try:
        tmp.write_text(text + "\n", encoding="utf-8")
        _replace_with_retry(tmp, target)
    except Exception:
        # Best-effort cleanup of the temp file; do not mask the original error.
        try:
            if tmp.exists():
                tmp.unlink()  # standards: log/temp rotation
        except OSError:
            pass
        raise


def _pid_alive(pid: int) -> bool:
    """Best-effort check that ``pid`` is alive on this host.

    Returns True when uncertain so we err on the side of leaving a possibly-live
    lock alone.
    """
    if pid <= 0:
        return False
    try:
        if sys.platform == "win32":
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            exit_code = ctypes.c_ulong()
            still_active = 259  # STILL_ACTIVE
            ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            kernel32.CloseHandle(handle)
            if not ok:
                return True  # Uncertain; treat as alive.
            return exit_code.value == still_active
        os.kill(pid, 0)
        return True
    except (PermissionError, ProcessLookupError):
        return isinstance(sys.exc_info()[1], PermissionError)
    except OSError:
        return True  # Uncertain; treat as alive.


def _read_lock_metadata(lock_path: Path) -> LockMetadata | None:
    try:
        text = lock_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    try:
        return LockMetadata(
            pid=int(data["pid"]),
            hostname=str(data["hostname"]),
            created_at=str(data["created_at"]),
            target_path=str(data["target_path"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _lock_age_seconds(meta: LockMetadata) -> float:
    try:
        created = datetime.fromisoformat(meta.created_at.replace("Z", "+00:00"))
    except ValueError:
        return float("inf")
    now = datetime.now(tz=timezone.utc)
    return (now - created).total_seconds()


@contextmanager
def acquire_jsonl_lock(
    target_path: Path | str,
    *,
    acquire_timeout: float = LOCK_ACQUIRE_TIMEOUT_SECONDS,
    stale_threshold: float = LOCK_STALE_THRESHOLD_SECONDS,
    on_stale_break: Callable[[LockMetadata], None] | None = None,
) -> Iterator[Path]:
    """Yield the lock file path after exclusively acquiring it.

    The lock file lives at ``<target_path>.lock`` and contains lock metadata. If
    an existing lock is older than ``stale_threshold`` and the owning pid is
    dead on this host (same-host check only), the lock is broken and
    ``on_stale_break`` is invoked with the previous owner's metadata. Cross-host
    stale locks require manual intervention and raise ``LockBrokenError``.
    """
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_name(target.name + ".lock")

    deadline = time.monotonic() + acquire_timeout
    hostname = socket.gethostname()
    pid = os.getpid()

    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            existing = _read_lock_metadata(lock_path)
            if existing is not None and _lock_age_seconds(existing) > stale_threshold:
                if existing.hostname != hostname:
                    raise LockBrokenError(
                        f"stale lock owned by pid={existing.pid} on host={existing.hostname!r} "
                        f"(this host={hostname!r}); manual intervention required"
                    )
                if not _pid_alive(existing.pid):
                    try:
                        lock_path.unlink()  # standards: log/temp rotation
                    except FileNotFoundError:
                        pass
                    if on_stale_break is not None:
                        on_stale_break(existing)
                    continue
            if time.monotonic() >= deadline:
                raise LockAcquireTimeout(
                    f"could not acquire {lock_path} within {acquire_timeout}s"
                )
            time.sleep(LOCK_POLL_INTERVAL_SECONDS)
            continue

        try:
            metadata = {
                "pid": pid,
                "hostname": hostname,
                "created_at": _utc_now_iso(),
                "target_path": str(target),
            }
            os.write(fd, json.dumps(metadata, ensure_ascii=False).encode("utf-8"))
        finally:
            os.close(fd)
        break

    try:
        yield lock_path
    finally:
        try:
            lock_path.unlink()  # standards: log/temp rotation
        except FileNotFoundError:
            pass


def append_jsonl_atomic(
    target_path: Path | str,
    line_payload: Mapping[str, Any],
    line_schema: Mapping[str, Any],
    *,
    acquire_timeout: float = LOCK_ACQUIRE_TIMEOUT_SECONDS,
    stale_threshold: float = LOCK_STALE_THRESHOLD_SECONDS,
    on_stale_break: Callable[[LockMetadata], None] | None = None,
) -> None:
    """Append one JSON line to ``target_path`` after schema-validating the line.

    Validation runs before the append. If validation fails, no I/O occurs against
    the target file (only the lock is acquired and released). If a write succeeds
    but a subsequent post-append validation pass fails (defence in depth — the
    same schema is re-validated on the on-disk line), the file is truncated back
    to its pre-append length so the append is unwound.
    """
    target = Path(target_path)
    text = json.dumps(line_payload, ensure_ascii=False, sort_keys=False)
    reparsed = json.loads(text)
    validate_payload(reparsed, line_schema)

    with acquire_jsonl_lock(
        target,
        acquire_timeout=acquire_timeout,
        stale_threshold=stale_threshold,
        on_stale_break=on_stale_break,
    ):
        pre_size = target.stat().st_size if target.exists() else 0
        with open(target, "ab") as fh:
            fh.write(text.encode("utf-8") + b"\n")
            fh.flush()
            os.fsync(fh.fileno())
        # Defence in depth: re-read the appended line and re-validate.
        with open(target, "rb") as fh:
            fh.seek(pre_size)
            appended = fh.read()
        try:
            decoded = appended.decode("utf-8").rstrip("\n").rstrip("\r")
            on_disk = json.loads(decoded)
            validate_payload(on_disk, line_schema)
        except (SchemaValidationError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            # Unwind: truncate back to pre_size.
            with open(target, "rb+") as fh:
                fh.truncate(pre_size)
            raise SchemaValidationError(
                f"appended line failed post-write validation; unwound: {exc}"
            ) from exc


__all__ = [
    "AtomicWriteError",
    "SchemaValidationError",
    "LockAcquireTimeout",
    "LockBrokenError",
    "LockMetadata",
    "validate_payload",
    "write_json_atomic",
    "append_jsonl_atomic",
    "acquire_jsonl_lock",
]
