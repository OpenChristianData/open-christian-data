"""Audit source-manifest bindings without importing reconstruction families.

The source manifests remain the authority.  This tool only compares their direct
path/digest bindings with the current checkout and, for legacy manifests, reports
which line-ending materialization would preserve the declared identity.  Legacy
inference is deliberately labeled transitional; it is not written back to a
manifest or to ``.gitattributes``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from ocd_kernel.lib.storage_topology import StorageTopologyError, resolve_repo_path


AUDIT_CONTRACT = "ocd-source-manifest-materialization-audit-v1"
MANAGED_BLOCK_START = "# BEGIN MANAGED SOURCE-MANIFEST MATERIALIZATION"
MANAGED_BLOCK_END = "# END MANAGED SOURCE-MANIFEST MATERIALIZATION"
EXACT_BYTES_MODE = "exact-bytes-v1"
CANONICAL_LF_MODE = "canonical-text-lf-v1"
SUPPORTED_BYTE_MODES = frozenset({EXACT_BYTES_MODE, CANONICAL_LF_MODE})
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_manifest(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_bytes(), object_pairs_hook=_strict_object)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"invalid source manifest JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("source manifest must be a JSON object")
    if payload.get("contract") != "ocd-source-manifest-v1":
        raise ValueError(
            "source manifest contract mismatch: only ocd-source-manifest-v1 is supported"
        )
    return payload


def _error(code: str, message: str, **context: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **context}


def _binding(
    *,
    manifest: str,
    binding_kind: str,
    binding_name: str,
    body: Mapping[str, Any],
    path_key: str,
    sha_key: str,
    bytes_key: str | None = None,
) -> dict[str, Any]:
    logical_path = body.get(path_key)
    digest = body.get(sha_key)
    declared_bytes = body.get(bytes_key) if bytes_key is not None else None
    byte_mode = body.get("byte_mode")
    return {
        "manifest": manifest,
        "binding_kind": binding_kind,
        "binding_name": binding_name,
        "path": logical_path,
        "sha256": digest,
        "bytes": declared_bytes,
        "byte_mode": byte_mode,
    }


def _manifest_bindings(
    manifest_path: Path,
    payload: Mapping[str, Any],
    *,
    repository_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    manifest = manifest_path.relative_to(repository_root).as_posix()
    bindings: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    authorities = payload.get("authorities")
    if not isinstance(authorities, list) or not authorities:
        errors.append(
            _error(
                "invalid-manifest",
                "source manifest authorities must be a nonempty array",
                manifest=manifest,
            )
        )
    else:
        names: set[str] = set()
        for index, authority in enumerate(authorities):
            if not isinstance(authority, Mapping):
                errors.append(
                    _error(
                        "invalid-binding",
                        "authority binding must be an object",
                        manifest=manifest,
                        binding=f"authority[{index}]",
                    )
                )
                continue
            name = authority.get("name")
            if not isinstance(name, str) or not name or name in names:
                errors.append(
                    _error(
                        "invalid-binding",
                        "authority name must be nonempty and unique within its manifest",
                        manifest=manifest,
                        binding=f"authority[{index}]",
                    )
                )
                continue
            names.add(name)
            bindings.append(
                _binding(
                    manifest=manifest,
                    binding_kind="authority",
                    binding_name=name,
                    body=authority,
                    path_key="path",
                    sha_key="sha256",
                    bytes_key="bytes",
                )
            )

    for kind, payload_key, path_key, sha_key in (
        ("converter", "converter", "implementation_path", "implementation_sha256"),
        ("validator", "validator", "implementation_path", "implementation_sha256"),
        ("package_schema", "package_schema", "path", "sha256"),
    ):
        body = payload.get(payload_key)
        if not isinstance(body, Mapping):
            errors.append(
                _error(
                    "invalid-binding",
                    f"{kind} binding must be an object",
                    manifest=manifest,
                    binding=kind,
                )
            )
            continue
        bindings.append(
            _binding(
                manifest=manifest,
                binding_kind=kind,
                binding_name=kind,
                body=body,
                path_key=path_key,
                sha_key=sha_key,
            )
        )
    return bindings, errors


def _validate_binding(binding: Mapping[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    logical_path = binding.get("path")
    digest = binding.get("sha256")
    declared_bytes = binding.get("bytes")
    byte_mode = binding.get("byte_mode")
    context = {
        "manifest": binding["manifest"],
        "binding": f"{binding['binding_kind']}:{binding['binding_name']}",
    }
    if not isinstance(logical_path, str) or not logical_path:
        errors.append(_error("invalid-binding", "binding path is invalid", **context))
    if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
        errors.append(_error("invalid-binding", "binding SHA-256 is invalid", **context))
    if binding.get("binding_kind") == "authority" and (
        not isinstance(declared_bytes, int)
        or isinstance(declared_bytes, bool)
        or declared_bytes < 0
    ):
        errors.append(_error("invalid-binding", "authority byte count is invalid", **context))
    if byte_mode is not None and not isinstance(byte_mode, str):
        errors.append(
            _error(
                "invalid-binding",
                "byte_mode must be a string when present",
                **context,
            )
        )
    elif byte_mode is not None and byte_mode not in SUPPORTED_BYTE_MODES:
        errors.append(
            _error(
                "unsupported-byte-mode",
                f"unsupported byte_mode: {byte_mode!r}",
                **context,
            )
        )
    return errors


def _text_materializations(content: bytes) -> tuple[str, bytes | None, bytes | None]:
    """Return shape, canonical LF bytes, and uniform CRLF bytes.

    BOM, NUL, invalid UTF-8, mixed newlines, and lone CR are deliberately not
    eligible for legacy text equivalence.
    """

    if content.startswith(b"\xef\xbb\xbf") or b"\x00" in content:
        return "binary", None, None
    try:
        content.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return "binary", None, None
    without_pairs = content.replace(b"\r\n", b"")
    if b"\r" in without_pairs:
        return "lone-cr", None, None
    has_pairs = b"\r\n" in content
    has_lf = b"\n" in without_pairs
    if has_pairs and has_lf:
        return "mixed", None, None
    if has_pairs:
        canonical = content.replace(b"\r\n", b"\n")
        return "crlf", canonical, canonical.replace(b"\n", b"\r\n")
    if b"\n" in content:
        return "lf", content, content.replace(b"\n", b"\r\n")
    return "no-eol", None, None


def _identity_matches(content: bytes, binding: Mapping[str, Any]) -> bool:
    declared_bytes = binding.get("bytes")
    return _sha256(content) == binding["sha256"] and (
        declared_bytes is None or declared_bytes == len(content)
    )


def _identities_conflict(bindings: Sequence[Mapping[str, Any]]) -> bool:
    digests = {binding["sha256"] for binding in bindings}
    byte_counts = {
        binding["bytes"] for binding in bindings if binding.get("bytes") is not None
    }
    explicit_modes = {
        binding["byte_mode"]
        for binding in bindings
        if binding.get("byte_mode") is not None
    }
    return len(digests) > 1 or len(byte_counts) > 1 or len(explicit_modes) > 1


def _classify(
    content: bytes,
    bindings: Sequence[Mapping[str, Any]],
) -> tuple[str, bool, str, str | None]:
    """Return classification, exact-match flag, text shape, desired attribute."""

    representative = next(
        (binding for binding in bindings if binding.get("byte_mode") is not None),
        bindings[0],
    )
    byte_mode = representative.get("byte_mode")
    shape, canonical_lf, uniform_crlf = _text_materializations(content)
    if byte_mode == CANONICAL_LF_MODE and shape == "binary":
        return "stale", False, shape, None
    if _identity_matches(content, representative):
        if shape in {"binary", "no-eol"}:
            return "binary/no-EOL", True, shape, "-text"
        if byte_mode == EXACT_BYTES_MODE:
            return "exact", True, shape, "-text"
        if byte_mode == CANONICAL_LF_MODE:
            if shape != "lf":
                return "stale", False, shape, None
            return "exact", True, shape, "text eol=lf"
        if shape not in {"lf", "crlf"}:
            # Exact mixed-newline and lone-CR bytes cannot be materialized by
            # Git's text/eol attributes. Preserve those legacy bindings verbatim.
            return "exact", True, shape, "-text"
        return "exact", True, shape, f"text eol={shape}"

    if byte_mode == EXACT_BYTES_MODE:
        return "stale", False, shape, None
    if canonical_lf is not None and _identity_matches(canonical_lf, representative):
        return "canonical LF-equivalent", False, shape, "text eol=lf"
    if byte_mode is None and uniform_crlf is not None and _identity_matches(
        uniform_crlf, representative
    ):
        return "CRLF-equivalent", False, shape, "text eol=crlf"
    return "stale", False, shape, None


def _binding_summary(binding: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: binding[key]
        for key in (
            "manifest",
            "binding_kind",
            "binding_name",
            "sha256",
            "bytes",
            "byte_mode",
        )
    }


def _path_sort_key(path: str) -> tuple[str, str]:
    return path.casefold(), path


def _logical_top_level(path: str) -> str:
    parts = PurePosixPath(path).parts
    return parts[0] if parts else ""


def audit_source_manifests(
    repository_root: str | Path,
    *,
    check_git: bool = False,
) -> dict[str, Any]:
    """Return a deterministic read-only audit of every source manifest binding."""

    root = Path(repository_root).resolve(strict=True)
    sources_root = root / "sources"
    errors: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    manifest_paths = (
        sorted(
            sources_root.rglob("*source-manifest.json"),
            key=lambda path: _path_sort_key(path.as_posix()),
        )
        if sources_root.is_dir()
        else []
    )
    if not sources_root.is_dir():
        errors.append(
            _error("manifest-root-missing", "repository sources directory is missing")
        )
    elif not manifest_paths:
        errors.append(_error("no-manifests", "no source manifests were found"))

    for manifest_path in manifest_paths:
        manifest = manifest_path.relative_to(root).as_posix()
        try:
            manifest_path.resolve(strict=True).relative_to(root)
        except (OSError, ValueError) as exc:
            errors.append(
                _error(
                    "containment",
                    f"source manifest escapes repository root: {exc}",
                    manifest=manifest,
                )
            )
            continue
        try:
            payload = _load_manifest(manifest_path)
        except ValueError as exc:
            errors.append(_error("invalid-manifest", str(exc), manifest=manifest))
            continue
        manifest_bindings, manifest_errors = _manifest_bindings(
            manifest_path, payload, repository_root=root
        )
        errors.extend(manifest_errors)
        for binding in manifest_bindings:
            binding_errors = _validate_binding(binding)
            errors.extend(binding_errors)
            if not binding_errors:
                bindings.append(binding)

    by_path: dict[str, list[dict[str, Any]]] = {}
    for binding in bindings:
        logical_path = binding["path"]
        assert isinstance(logical_path, str)
        try:
            physical_path = resolve_repo_path(root, logical_path)
        except (StorageTopologyError, OSError, RuntimeError) as exc:
            errors.append(
                _error(
                    "containment",
                    str(exc),
                    path=logical_path,
                    manifest=binding["manifest"],
                    binding=f"{binding['binding_kind']}:{binding['binding_name']}",
                )
            )
            continue
        binding["_physical_path"] = physical_path
        key = logical_path.casefold() if os.name == "nt" else logical_path
        by_path.setdefault(key, []).append(binding)

    entries: list[dict[str, Any]] = []
    for grouped_bindings in by_path.values():
        grouped_bindings.sort(
            key=lambda binding: (
                _path_sort_key(binding["manifest"]),
                binding["binding_kind"],
                binding["binding_name"],
            )
        )
        logical_paths = {binding["path"] for binding in grouped_bindings}
        logical_path = sorted(logical_paths, key=_path_sort_key)[0]
        legacy = any(binding.get("byte_mode") is None for binding in grouped_bindings)
        entry: dict[str, Any] = {
            "path": logical_path,
            "classification": "",
            "exact_match": False,
            "text_shape": None,
            "attribute": None,
            "attribute_projected": _logical_top_level(logical_path) != "raw",
            "legacy_inference": legacy,
            "bindings": [_binding_summary(binding) for binding in grouped_bindings],
            "actual": None,
        }
        if len(logical_paths) > 1 or _identities_conflict(grouped_bindings):
            entry["classification"] = "conflict"
            errors.append(
                _error(
                    "conflict",
                    "the same normalized path has conflicting manifest identities",
                    path=logical_path,
                )
            )
            entries.append(entry)
            continue
        physical_path = grouped_bindings[0]["_physical_path"]
        if not physical_path.is_file():
            entry["classification"] = "missing"
            errors.append(
                _error("missing", "bound file is missing", path=logical_path)
            )
            entries.append(entry)
            continue
        try:
            content = physical_path.read_bytes()
        except OSError as exc:
            entry["classification"] = "missing"
            errors.append(_error("missing", str(exc), path=logical_path))
            entries.append(entry)
            continue
        classification, exact_match, text_shape, attribute = _classify(
            content, grouped_bindings
        )
        entry.update(
            {
                "classification": classification,
                "exact_match": exact_match,
                "text_shape": text_shape,
                "attribute": attribute,
                "actual": {"bytes": len(content), "sha256": _sha256(content)},
            }
        )
        if classification == "stale":
            errors.append(
                _error(
                    "stale",
                    (
                        "current bytes do not match the declared identity or a safe "
                        "line-ending equivalent"
                    ),
                    path=logical_path,
                )
            )
        entries.append(entry)

    entries.sort(key=lambda entry: _path_sort_key(entry["path"]))
    git_report: dict[str, Any] = {
        "checked": False,
        "provenance_membership_rechecked": False,
        "untracked_paths": [],
        "attribute_mismatches": [],
    }
    if check_git:
        git_report, git_errors = _check_git(root, entries)
        errors.extend(git_errors)

    classifications = Counter(entry["classification"] for entry in entries)
    legacy_paths = [entry["path"] for entry in entries if entry["legacy_inference"]]
    report: dict[str, Any] = {
        "contract": AUDIT_CONTRACT,
        "repository_root": str(root),
        "manifest_count": len(manifest_paths),
        "binding_count": len(bindings),
        "path_count": len(entries),
        "classifications": dict(sorted(classifications.items())),
        "transitional_legacy_inference": {
            "active": bool(legacy_paths),
            "path_count": len(legacy_paths),
            "paths": legacy_paths,
            "note": (
                "Missing byte_mode was inferred for reporting only; manifests remain authority "
                "and no inferred mode was written or promoted to canonical status."
            ),
        },
        "entries": entries,
        "git": git_report,
        "errors": sorted(
            errors,
            key=lambda item: (
                str(item.get("path", "")).casefold(),
                str(item.get("manifest", "")).casefold(),
                item["code"],
                item["message"],
            ),
        ),
    }
    report["ok"] = not report["errors"]
    return report


def _projectable_entries(entries: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(
        (
            entry
            for entry in entries
            if entry.get("attribute_projected")
            and isinstance(entry.get("attribute"), str)
            and entry.get("classification")
            not in {"conflict", "missing", "stale"}
        ),
        key=lambda entry: _path_sort_key(str(entry["path"])),
    )


def _attribute_pattern(path: str) -> str:
    escaped = path.replace("\\", "\\\\")
    for special in ("*", "?", "["):
        escaped = escaped.replace(special, f"\\{special}")
    if escaped.startswith(("#", "!")) or any(char.isspace() for char in escaped):
        return json.dumps(escaped, ensure_ascii=True)
    return escaped


def render_gitattributes(report: Mapping[str, Any]) -> str:
    """Render the deterministic managed block; never write it to disk."""

    lines = [
        MANAGED_BLOCK_START,
        "# Generated read-only from source-manifest direct bindings.",
        "# Legacy-inferred rows are transitional until manifests declare byte_mode.",
    ]
    for entry in _projectable_entries(report.get("entries", [])):
        attribute = str(entry["attribute"])
        if attribute == "-text":
            # Clear any eol value inherited from earlier rules as well as
            # disabling conversion, so exact bytes stay fully explicit.
            attribute = "-text !eol"
        lines.append(f"{_attribute_pattern(str(entry['path']))} {attribute}")
    lines.append(MANAGED_BLOCK_END)
    return "\n".join(lines) + "\n"


def _git_attributes(repository_root: Path, paths: Sequence[str]) -> dict[str, dict[str, str]]:
    if not paths:
        return {}
    process = subprocess.run(
        ["git", "check-attr", "-z", "--stdin", "text", "eol"],
        cwd=repository_root,
        input=("\0".join(paths) + "\0").encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    fields = process.stdout.decode("utf-8", errors="strict").split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    if len(fields) % 3:
        raise ValueError("git check-attr returned an invalid NUL-delimited response")
    result: dict[str, dict[str, str]] = {}
    for index in range(0, len(fields), 3):
        path, attribute, value = fields[index : index + 3]
        result.setdefault(path, {})[attribute] = value
    return result


def _check_git(
    repository_root: Path,
    entries: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    projectable = _projectable_entries(entries)
    provenance_paths = sorted(
        {
            str(entry["path"])
            for entry in entries
            if _logical_top_level(str(entry["path"])) != "raw"
        },
        key=_path_sort_key,
    )
    attribute_paths = [str(entry["path"]) for entry in projectable]
    report: dict[str, Any] = {
        "checked": True,
        "provenance_membership_rechecked": False,
        "untracked_paths": [],
        "attribute_mismatches": [],
    }
    errors: list[dict[str, Any]] = []
    try:
        tracked_process = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=repository_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        tracked = {
            path
            for path in tracked_process.stdout.decode("utf-8", errors="strict").split("\0")
            if path
        }
        report["provenance_membership_rechecked"] = True
        report["untracked_paths"] = sorted(
            set(provenance_paths) - tracked, key=_path_sort_key
        )
        attributes = _git_attributes(repository_root, attribute_paths)
    except (FileNotFoundError, subprocess.CalledProcessError, UnicodeError, ValueError) as exc:
        errors.append(_error("git-check-failed", str(exc)))
        return report, errors

    for path in report["untracked_paths"]:
        errors.append(
            _error("untracked", "bound repository-local path is not tracked by Git", path=path)
        )
    for entry in projectable:
        path = str(entry["path"])
        desired = str(entry["attribute"])
        actual = attributes.get(path, {})
        expected = (
            {"text": "unset", "eol": "unspecified"}
            if desired == "-text"
            else {"text": "set", "eol": desired.removeprefix("text eol=")}
        )
        if any(actual.get(name, "unspecified") != value for name, value in expected.items()):
            mismatch = {"path": path, "expected": expected, "actual": actual}
            report["attribute_mismatches"].append(mismatch)
            errors.append(
                _error(
                    "attribute-mismatch",
                    "effective Git attributes do not match the manifest-derived projection",
                    path=path,
                )
            )
    return report, errors


def _human_summary(report: Mapping[str, Any]) -> str:
    state = "PASS" if report["ok"] else "FAIL"
    counts = ", ".join(
        f"{name}={count}" for name, count in report["classifications"].items()
    )
    lines = [
        f"source-manifest materialization: {state}",
        (
            f"manifests={report['manifest_count']} bindings={report['binding_count']} "
            f"paths={report['path_count']}"
        ),
        counts or "classifications=none",
    ]
    legacy = report["transitional_legacy_inference"]
    if legacy["active"]:
        lines.append(
            (
                f"TRANSITIONAL: {legacy['path_count']} paths use reporting-only "
                "legacy byte-mode inference"
            )
        )
    for error in report["errors"]:
        location = error.get("path") or error.get("manifest") or "audit"
        lines.append(f"{error['code']}: {location}: {error['message']}")
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path.cwd(),
        help="repository root (default: current directory)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="print the human check summary (the default action)",
    )
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help="print the audit report as JSON")
    output.add_argument(
        "--print-gitattributes",
        action="store_true",
        help="print the managed attribute block without writing it",
    )
    parser.add_argument(
        "--check-git",
        "--git-provenance",
        action="store_true",
        dest="check_git",
        help="also recheck Git membership and effective attributes",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = audit_source_manifests(args.repository_root, check_git=args.check_git)
    except (OSError, RuntimeError, ValueError) as exc:
        if args.json:
            print(json.dumps({"contract": AUDIT_CONTRACT, "ok": False, "errors": [str(exc)]}))
        else:
            print(f"source-manifest materialization: FAIL\naudit: {exc}")
        return 1
    if args.print_gitattributes:
        print(render_gitattributes(report), end="")
    elif args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(_human_summary(report), end="")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
