"""Read small library records and check that their inputs stayed unchanged."""
from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path
import re
from typing import Callable

from ocd_kernel.lib.path_io import io_path, resolve_path
from ocd_kernel.lib.storage_topology import StorageTopologyError, resolve_repo_path
from ._common import PipelineError, read_input_bytes, sha256_bytes


def normalize_diagnostic(root: Path, message: object) -> str:
    """Remove machine-specific roots from reported errors, not loader errors."""

    text = str(message).replace("\\", "/")
    root_variants = {
        str(Path(root).absolute()).replace("\\", "/"),
        str(resolve_path(Path(root))).replace("\\", "/"),
    }
    for value in sorted(root_variants, key=len, reverse=True):
        value = value.rstrip("/")
        if not value:
            continue
        text = re.sub(
            re.escape(value) + r"(?:/|(?=$|[^A-Za-z0-9._-]))",
            "",
            text,
            flags=re.IGNORECASE,
        )
    return text


class RecordRead:
    """Track small records, directory membership, and file presence for one read.

    Call stable() after collecting inputs. Each caller decides whether a changed
    input should trigger a retry, a reported issue, or an immediate failure.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.absolute()
        self.inputs: dict[str, dict] = {}
        self.paths: dict[str, Path] = {}
        self.discovery: dict[tuple[str, str], dict] = {}
        self.optional_membership: set[tuple[str, str]] = set()
        self.observations: dict[str, dict] = {}
        self.diagnostics: list[dict] = []
        self.routing: dict[str, str] = {}

    def issue(self, section: str, code: str, path: str, message: object,
              *, severity: str = "error") -> None:
        self.diagnostics.append({"section": section, "code": code, "path": path,
                                 "message": normalize_diagnostic(self.root, message),
                                 "severity": severity})

    def physical(self, reference: str) -> Path:
        path = resolve_repo_path(self.root, reference)
        self.routing[reference] = sha256_bytes(str(path).encode("utf-8"))
        return path

    def bytes(self, reference: str, section: str, *, physical: Path | None = None) -> bytes | None:
        parts = [part for part in reference.replace("\\", "/").split("/") if part not in {"", "."}]
        selected_material = (section == 'metadata' and len(parts) >= 4 and parts[0].casefold() == 'exports'
                             and ([part.casefold() for part in parts[-2:]] == ['internal', 'release-selection.json']
                                  or len(parts) >= 5 and parts[-3].casefold() == 'internal'
                                  and parts[-2].casefold() in ('projection-receipts', 'public-row-transforms')
                                  and parts[-1].casefold().endswith('.json')))
        if (parts and (parts[0].casefold() == 'raw' or parts[0].casefold() == 'exports' and not selected_material)
                or reference.casefold().endswith((".xml", ".tei"))):
            raise PipelineError(f"default lookup cannot read a text body: {reference}")
        try:
            path = physical if physical is not None else self.physical(reference)
            body = read_input_bytes(path)
        except (OSError, StorageTopologyError) as exc:
            self.inputs[reference] = {"path": reference, "health": "unavailable", "sha256": None, "bytes": None}
            self.issue(section, "unavailable", reference, exc)
            return None
        self.paths[reference] = path
        self.inputs[reference] = {"path": reference, "health": "valid", "sha256": sha256_bytes(body), "bytes": len(body)}
        return body

    def record(self, reference: str, section: str, loader: Callable[[Path], dict]) -> dict | None:
        if self.bytes(reference, section) is None:
            return None
        try:
            return loader(self.paths[reference])
        except (PipelineError, OSError, UnicodeError) as exc:
            self.issue(section, "invalid" if isinstance(exc, (PipelineError, UnicodeError)) else "unavailable", reference, exc)
            return None

    def observe(self, reference: str) -> dict:
        reference = reference.partition("#")[0]
        try:
            path = self.physical(reference)
            stat = io_path(path).stat()
            observation = {"path": reference, "health": "valid", "present": True,
                           "bytes": stat.st_size if io_path(path).is_file() else None,
                           "kind": "file" if io_path(path).is_file() else "directory"}
        except FileNotFoundError:
            observation = {"path": reference, "health": "valid", "present": False, "bytes": None, "kind": None}
        except (OSError, StorageTopologyError) as exc:
            observation = {"path": reference, "health": "unavailable", "present": None, "bytes": None, "kind": None}
        self.observations[reference] = observation
        return observation

    def members(self, reference: str, pattern: str, section: str, *, optional: bool = False) -> list[str]:
        key = (reference, pattern)
        if optional:
            self.optional_membership.add(key)
        try:
            directory = self.physical(reference)
            names = sorted(path.name for path in io_path(directory).iterdir() if fnmatchcase(path.name, pattern))
        except FileNotFoundError as exc:
            names = []
            if not optional:
                self.issue(section, "unavailable", reference, exc)
            health = "valid" if optional else "unavailable"
        except (OSError, StorageTopologyError) as exc:
            names = []
            health = "unavailable"
            self.issue(section, "unavailable", reference, exc)
        else:
            health = "valid"
        self.discovery[key] = {"path": reference, "pattern": pattern, "members": names, "health": health}
        return names

    def stable(self) -> bool:
        for reference, digest in list(self.routing.items()):
            try:
                if sha256_bytes(str(resolve_repo_path(self.root, reference)).encode("utf-8")) != digest:
                    return False
            except (OSError, StorageTopologyError):
                return False
        for reference, binding in self.inputs.items():
            try:
                path = self.paths.get(reference) or self.physical(reference)
                digest = sha256_bytes(io_path(path).read_bytes())
            except (OSError, StorageTopologyError):
                digest = None
            if digest != binding["sha256"]:
                return False
        for (reference, pattern), binding in list(self.discovery.items()):
            try:
                names = sorted(path.name for path in io_path(self.physical(reference)).iterdir() if fnmatchcase(path.name, pattern))
                health = "valid"
            except FileNotFoundError:
                names = []
                health = "valid" if (reference, pattern) in self.optional_membership else "unavailable"
            except (OSError, StorageTopologyError):
                names, health = [], "unavailable"
            if names != binding["members"] or health != binding["health"]:
                return False
        for reference, observation in list(self.observations.items()):
            if self.observe(reference) != observation:
                return False
        return True

