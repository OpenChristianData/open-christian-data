"""Materialize one bounded, read-only CVW runtime into a fresh directory.

The materialized directory is an execution copy, not another source or input
authority.  Its backend is the same import closure used by
``cvw_app.serving_identity`` and its frontend is the same built-file profile
sealed by ``ServingIdentity``.  Canonical repository inputs and candidate
directories remain at their caller-selected paths.

This helper deliberately does not start a service.  The returned manifest
contains a command whose entrypoint is the copied protected launcher and whose
``--repository-root``, catalog, and candidate paths remain explicit.  A
successful local copy is not evidence that another host can read it; the
manifest records that host execution is still required.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
from typing import Iterable, Sequence

from cvw_app.serving_identity import (
    BACKEND_ROOTS,
    file_identity,
    local_members,
)
from ocd_kernel.lib.storage_topology import (
    EXTERNAL_DATA_ROOTS,
    StorageTopologyError,
    resolve_repo_path,
)


MATERIALIZATION_CONTRACT = "ocd-cvw-runtime-materialization-v1"
HOST_READABILITY_LIMITATION = (
    "The source-to-destination byte and closure checks ran in the creating "
    "process. Host readability is unproven until the host executes the copied "
    "launcher; no ACL change or host result is inferred here."
)
_REPARSE_POINT = 0x400
_COPY_CHUNK_BYTES = 1024 * 1024
_CURRENT_IMPLEMENTATION_ROOT = Path(__file__).resolve().parents[1]
_GOVERNING_COMPATIBILITY_FILES = (*BACKEND_ROOTS, "cvw_app/materialize_runtime.py")


class MaterializationError(RuntimeError):
    """Raised when a bounded runtime cannot be staged without ambiguity."""


@dataclass(frozen=True)
class MaterializationReport:
    """The verified copy report and its generated protected-launch command."""

    manifest_path: Path
    destination_root: Path
    payload: dict[str, object]

    @property
    def launch_command(self) -> tuple[str, ...]:
        launch = self.payload.get("launch")
        if not isinstance(launch, dict):
            raise MaterializationError("materialization report has no launch command")
        command = launch.get("argv")
        if not isinstance(command, list) or any(not isinstance(item, str) for item in command):
            raise MaterializationError("materialization report launch command is malformed")
        return tuple(command)


def _is_reparse_point(path: Path) -> bool:
    """Return whether *path* is a symlink or Windows reparse point."""

    try:
        info = path.lstat()
    except OSError as error:
        raise MaterializationError(f"cannot inspect path safely: {path} ({error})") from error
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & _REPARSE_POINT
    )


def _assert_no_reparse_ancestors(path: Path, *, label: str) -> None:
    """Reject path components that could redirect a fresh destination."""

    current = path
    while True:
        if current.exists() and _is_reparse_point(current):
            raise MaterializationError(f"{label} contains a reparse point: {current}")
        parent = current.parent
        if parent == current:
            return
        current = parent


def _existing_directory(value: Path | str, label: str) -> Path:
    requested = Path(value).expanduser()
    try:
        resolved = requested.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise MaterializationError(f"{label} is unavailable: {requested} ({error})") from error
    if not resolved.is_dir():
        raise MaterializationError(f"{label} is not a directory: {resolved}")
    return resolved


def _existing_file(value: Path | str, label: str) -> Path:
    requested = Path(value).expanduser()
    try:
        resolved = requested.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise MaterializationError(f"{label} is unavailable: {requested} ({error})") from error
    if not resolved.is_file():
        raise MaterializationError(f"{label} is not a file: {resolved}")
    if _is_reparse_point(requested):
        raise MaterializationError(f"{label} is a reparse point: {requested}")
    return resolved


def _destination_root(
    value: Path | str,
    source_root: Path,
    *,
    protected_roots: Iterable[Path] = (),
) -> Path:
    requested = Path(value).expanduser()
    lexical = Path(os.path.abspath(os.fspath(requested)))
    if os.path.lexists(lexical):
        raise MaterializationError(
            f"destination already exists; refusing to overwrite or delete it: {lexical}"
        )
    parent = lexical.parent
    _assert_no_reparse_ancestors(parent, label="destination parent")
    try:
        parent_resolved = parent.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise MaterializationError(
            f"destination parent is unavailable: {parent} ({error})"
        ) from error
    if not parent_resolved.is_dir():
        raise MaterializationError(f"destination parent is not a directory: {parent_resolved}")
    _assert_no_reparse_ancestors(parent_resolved, label="resolved destination parent")
    resolved = lexical.resolve(strict=False)
    if resolved == source_root or resolved.is_relative_to(source_root):
        raise MaterializationError(
            f"destination must be outside the source implementation root: {resolved}"
        )
    if source_root.is_relative_to(resolved):
        raise MaterializationError(
            f"destination cannot contain the source implementation root: {resolved}"
        )
    for protected in protected_roots:
        if resolved == protected or resolved.is_relative_to(protected):
            raise MaterializationError(
                f"destination resolves inside a protected input root: {resolved}"
            )
    return resolved


def _safe_relative(value: str, label: str) -> Path:
    """Convert a canonical POSIX member name to a safe local relative path."""

    normalized = value.replace("\\", "/")
    path = Path(*normalized.split("/"))
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise MaterializationError(f"{label} escapes its root: {value}")
    return path


def _source_member_path(source_root: Path, relative: str, *, label: str) -> Path:
    path = source_root / _safe_relative(relative, label)
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise MaterializationError(f"{label} is unavailable: {path} ({error})") from error
    if not resolved.is_relative_to(source_root):
        raise MaterializationError(f"{label} resolves outside source root: {path} -> {resolved}")
    if not resolved.is_file():
        raise MaterializationError(f"{label} is not a file: {resolved}")
    if _is_reparse_point(path):
        raise MaterializationError(f"{label} is a reparse point: {path}")
    return resolved


def _require_governing_compatibility(source_root: Path) -> None:
    """Ensure the source is measured by the same launcher/checker contract."""

    for relative in _GOVERNING_COMPATIBILITY_FILES:
        selected = _source_member_path(
            source_root, relative, label="governing compatibility"
        )
        current = _source_member_path(
            _CURRENT_IMPLEMENTATION_ROOT,
            relative,
            label="current governing implementation",
        )
        if file_identity(selected) != file_identity(current):
            raise MaterializationError(
                "source governing implementation differs from the materializer "
                f"contract: {relative}; use a matching implementation checkout"
            )


def _frontend_members(static_root: Path) -> tuple[str, ...]:
    """Return the exact frontend file profile used by ServingIdentity."""

    entrypoint = static_root / "review.html"
    assets = static_root / "assets"
    if not entrypoint.is_file():
        raise MaterializationError(f"built frontend entrypoint is missing: {entrypoint}")
    if not assets.is_dir():
        raise MaterializationError(f"built frontend assets directory is missing: {assets}")
    members = ["review.html"]
    for path in sorted(assets.rglob("*")):
        if _is_reparse_point(path):
            raise MaterializationError(f"built frontend contains a reparse point: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise MaterializationError(f"built frontend member is not a file: {path}")
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(static_root):
            raise MaterializationError(
                f"built frontend member resolves outside static root: {path} -> {resolved}"
            )
        members.append(path.relative_to(static_root).as_posix())
    return tuple(sorted(set(members)))


def _copy_file(source: Path, destination: Path, *, label: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(destination):
        raise MaterializationError(f"destination member already exists: {destination}")
    try:
        with source.open("rb") as source_stream, destination.open("xb") as destination_stream:
            shutil.copyfileobj(source_stream, destination_stream, _COPY_CHUNK_BYTES)
    except OSError as error:
        raise MaterializationError(f"could not copy {label}: {source} -> {destination} ({error})") from error
    if _is_reparse_point(destination):
        raise MaterializationError(f"copied destination member became a reparse point: {destination}")


def _identity_pairs(source_root: Path, destination_root: Path, members: Sequence[str], *, label: str) -> dict[str, dict[str, object]]:
    pairs: dict[str, dict[str, object]] = {}
    for relative in members:
        source = _source_member_path(source_root, relative, label=f"{label} source member")
        destination = destination_root / _safe_relative(relative, f"{label} destination member")
        if not destination.is_file() or _is_reparse_point(destination):
            raise MaterializationError(f"{label} destination member is unavailable: {destination}")
        source_identity = file_identity(source)
        destination_identity = file_identity(destination)
        if source_identity != destination_identity:
            raise MaterializationError(
                f"{label} bytes differ after copy: {relative} "
                f"({source_identity} != {destination_identity})"
            )
        pairs[relative] = {
            "source": source_identity,
            "destination": destination_identity,
        }
    return pairs


def _member_set_digest(members: Sequence[str]) -> str:
    return hashlib.sha256(
        ("\n".join(sorted(members)) + "\n").encode("utf-8")
    ).hexdigest()


def _resolved_input_file(value: Path | str, label: str) -> Path:
    return _existing_file(value, label)


def _resolved_input_directories(values: Iterable[Path | str]) -> tuple[Path, ...]:
    return tuple(
        _existing_directory(value, f"candidate directory {index}")
        for index, value in enumerate(values, start=1)
    )


def _protected_storage_roots(repository_roots: Iterable[Path]) -> tuple[Path, ...]:
    """Resolve every repository and configured physical data-plane root."""

    roots: set[Path] = {_CURRENT_IMPLEMENTATION_ROOT}
    seen: set[Path] = set()
    for repository in repository_roots:
        resolved_repository = repository.resolve(strict=True)
        if resolved_repository in seen:
            continue
        seen.add(resolved_repository)
        roots.add(resolved_repository)
        try:
            roots.update(
                resolve_repo_path(resolved_repository, name)
                for name in sorted(EXTERNAL_DATA_ROOTS)
            )
        except StorageTopologyError as error:
            raise MaterializationError(
                "configured storage topology could not be resolved safely for "
                f"{resolved_repository}: {error}"
            ) from error
    return tuple(sorted(roots))


def _launch_command(
    destination_root: Path,
    canonical_repository_root: Path,
    static_root: Path,
    catalog_path: Path | None,
    candidate_dirs: Sequence[Path],
    declared_library: bool = False,
) -> tuple[str, ...]:
    command = [
        sys.executable,
        str(destination_root / "cvw_app" / "launch_windows.py"),
        "--repository-root",
        str(canonical_repository_root),
        "--static-root",
        str(static_root),
    ]
    if declared_library:
        command.append("--declared-library")
    if catalog_path is not None:
        command.extend(("--catalog", str(catalog_path)))
    for candidate in candidate_dirs:
        command.extend(("--candidate-dir", str(candidate)))
    return tuple(command)


def materialize_runtime(
    source_root: Path | str,
    destination_root: Path | str,
    *,
    static_root: Path | str | None = None,
    repository_root: Path | str | None = None,
    catalog_path: Path | str | None = None,
    candidate_dirs: Iterable[Path | str] = (),
    declared_library: bool = False,
) -> MaterializationReport:
    """Copy and verify a bounded CVW runtime into a fresh external root.

    The source and destination roots are independent.  Only the current
    ``local_members`` closure and the frontend files governed by
    ``ServingIdentity`` are copied.  Existing destinations are refused before
    any write, and the helper never deletes a destination on failure.
    """

    if declared_library and catalog_path is not None:
        raise MaterializationError("declared-library and catalog inputs are mutually exclusive")
    declared_library = catalog_path is None
    source = _existing_directory(source_root, "source implementation root")
    _assert_no_reparse_ancestors(source, label="source implementation root")
    _require_governing_compatibility(source)
    static_source = _existing_directory(
        static_root or source / "cvw_app" / "dist", "built frontend root"
    )
    if not static_source.is_relative_to(source):
        raise MaterializationError(
            "built frontend root must be inside the source implementation root"
        )
    # Keep the launcher's source-tree freshness, review-root, and local-asset
    # checks authoritative before omitting source files from the execution
    # copy.  A copied dist must not turn a stale source checkout into an
    # apparently valid runtime.
    try:
        from cvw_app.launch_windows import _validate_built_frontend

        _validate_built_frontend(static_source)
    except (OSError, RuntimeError, UnicodeError, ValueError) as error:
        raise MaterializationError(
            f"built frontend failed the launcher validation: {error}"
        ) from error
    static_relative = static_source.relative_to(source)

    backend_members = tuple(local_members(source))
    if not backend_members:
        raise MaterializationError("serving identity import closure is empty")
    frontend_members = _frontend_members(static_source)
    for relative in backend_members:
        _source_member_path(source, relative, label="backend")
    for relative in frontend_members:
        _source_member_path(static_source, relative, label="frontend")

    canonical_repository = _existing_directory(
        repository_root or source, "canonical repository root"
    )
    catalog = (
        _resolved_input_file(catalog_path, "WorkCatalog")
        if catalog_path is not None
        else None
    )
    candidates = _resolved_input_directories(candidate_dirs)
    protected_storage_roots = _protected_storage_roots(
        (_CURRENT_IMPLEMENTATION_ROOT, source, canonical_repository)
    )
    destination = _destination_root(
        destination_root,
        source,
        protected_roots=(
            *protected_storage_roots,
            *candidates,
            static_source,
        ),
    )
    launch_static = destination / static_relative

    # mkdir reserves the previously absent destination without replacing an
    # existing path.  A failed copy is intentionally left for operator review;
    # this helper never removes a destination it did not create.
    try:
        destination.mkdir()
    except FileExistsError as error:
        raise MaterializationError(
            f"destination appeared during materialization; refusing overwrite: {destination}"
        ) from error
    except OSError as error:
        raise MaterializationError(f"could not create destination: {destination} ({error})") from error

    for relative in backend_members:
        source_path = _source_member_path(source, relative, label="backend")
        _copy_file(source_path, destination / _safe_relative(relative, "backend"), label="backend")
    for relative in frontend_members:
        source_path = _source_member_path(static_source, relative, label="frontend")
        _copy_file(source_path, launch_static / _safe_relative(relative, "frontend"), label="frontend")

    # Re-read the source closure before sealing the report, so a concurrent
    # source edit cannot be silently represented as a verified copy.
    if tuple(local_members(source)) != backend_members:
        raise MaterializationError("source import closure changed during materialization")
    if _frontend_members(static_source) != frontend_members:
        raise MaterializationError("source frontend member set changed during materialization")
    destination_members = tuple(local_members(destination))
    if destination_members != backend_members:
        raise MaterializationError(
            "materialized import closure differs from source: "
            f"source={backend_members!r}; destination={destination_members!r}"
        )
    destination_frontend_members = _frontend_members(launch_static)
    if destination_frontend_members != frontend_members:
        raise MaterializationError(
            "materialized frontend member set differs from source: "
            f"source={frontend_members!r}; destination={destination_frontend_members!r}"
        )

    backend_identities = _identity_pairs(
        source, destination, backend_members, label="backend"
    )
    frontend_identities = _identity_pairs(
        static_source, launch_static, frontend_members, label="frontend"
    )
    launch = _launch_command(
        destination,
        canonical_repository,
        launch_static,
        catalog,
        candidates,
        declared_library,
    )
    payload: dict[str, object] = {
        "contract": MATERIALIZATION_CONTRACT,
        "source_root": str(source),
        "destination_root": str(destination),
        "destination_protection_roots": [
            str(root)
            for root in sorted(
                {*protected_storage_roots, *candidates, static_source}
            )
        ],
        "scope": {
            "backend_basis": "cvw_app.serving_identity.local_members(source_root)",
            "backend_roots": list(BACKEND_ROOTS),
            "backend_member_count": len(backend_members),
            "backend_member_set_sha256": _member_set_digest(backend_members),
            "frontend_basis": "ServingIdentity frontend manifest: review.html and assets/**",
            "frontend_root_source": str(static_source),
            "frontend_root_destination": str(launch_static),
            "frontend_member_count": len(frontend_members),
            "frontend_member_set_sha256": _member_set_digest(frontend_members),
            "resource_evidence": [
                {
                    "profile": "backend import closure",
                    "evidence": "ServingIdentity.local_members(source_root)",
                    "copied": True,
                },
                {
                    "profile": "built frontend",
                    "evidence": "ServingIdentity frontend manifest inventory",
                    "paths": ["review.html", "assets/**"],
                    "copied": True,
                },
                {
                    "profile": "governing launcher/checker contract",
                    "evidence": "byte-identical cvw_app/launch_windows.py, serving_identity.py, and materialize_runtime.py",
                    "copied": True,
                },
                {
                    "profile": "candidate/source schemas and authorities",
                    "evidence": "launch --repository-root and launcher protected-input binding",
                    "copied": False,
                    "authority": "canonical input repository",
                },
            ],
            "declared_resource_limitation": (
                "The 111-file recovery copy was broader historical evidence. "
                "This manifest records only the current serving closure and "
                "frontend profile; it is not a claim that every historical "
                "copy member is required."
            ),
            "omitted_by_design": [
                "canonical repository inputs",
                "candidate directories",
                "Python site-packages and interpreter runtime",
                "unrelated files outside the sealed backend/frontend profiles",
            ],
        },
        "backend": {
            "members": backend_identities,
            "source_member_set": list(backend_members),
            "destination_member_set": list(destination_members),
            "import_closure_equivalent": destination_members == backend_members,
        },
        "frontend": {
            "members": frontend_identities,
            "source_member_set": list(frontend_members),
            "destination_member_set": list(destination_frontend_members),
            "member_set_equivalent": destination_frontend_members == frontend_members,
        },
        "launch": {
            "entrypoint": str(destination / "cvw_app" / "launch_windows.py"),
            "argv": list(launch),
            "repository_root": str(canonical_repository),
            "catalog": str(catalog) if catalog is not None else None,
            "declared_library": declared_library,
            "candidate_dirs": [str(path) for path in candidates],
            "static_root": str(launch_static),
            "input_authority_note": (
                "The command keeps canonical repository, catalog, and candidate "
                "paths explicit; they are not copied into the runtime root."
            ),
        },
        "host_readability": {
            "status": "unproven",
            "limitation": HOST_READABILITY_LIMITATION,
        },
        "acl_policy": "Files are copied as bytes; no ACL mutation is requested or performed.",
        "manifest_path": str(destination / "cvw-runtime-materialization.json"),
    }
    manifest_path = destination / "cvw-runtime-materialization.json"
    try:
        with manifest_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
    except OSError as error:
        raise MaterializationError(f"could not record materialization manifest: {manifest_path} ({error})") from error
    return MaterializationReport(manifest_path, destination, payload)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Materialize a bounded CVW runtime into a fresh external root"
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Implementation source root (default: this repository root)",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        required=True,
        metavar="PATH",
        help="Fresh external destination directory; an existing path is refused",
    )
    parser.add_argument(
        "--static-root",
        type=Path,
        default=None,
        metavar="PATH",
        help="Built frontend root (default: source-root/cvw_app/dist)",
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=None,
        metavar="PATH",
        help="Canonical input repository root for the generated launch command",
    )
    parser.add_argument("--catalog", type=Path, default=None, metavar="PATH")
    parser.add_argument("--declared-library", action="store_true", help="Use canonical library sidecars without WorkCatalog")
    parser.add_argument(
        "--candidate-dir",
        type=Path,
        action="append",
        default=[],
        metavar="PATH",
        help="Original validated candidate path for the generated launch command; repeat as needed",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    try:
        report = materialize_runtime(
            args.source_root,
            args.destination,
            static_root=args.static_root,
            repository_root=args.repository_root,
            catalog_path=args.catalog,
            candidate_dirs=args.candidate_dir,
            declared_library=args.declared_library,
        )
    except (MaterializationError, OSError, ValueError) as error:
        print(f"cvw runtime materialization failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report.payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
