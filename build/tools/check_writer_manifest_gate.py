"""Pre-commit gate for staged writer manifests and paired ``data/`` JSON files.

The gate checks:

  1. Every staged writer manifest under ``review/writer-manifests/`` validates
     against ``schemas/v1/writer_manifest.schema.json``.
  2. The selected repository's staged ``build/lib/writer_identities.py``
     matches the source backing the executing identity authorizer.
  3. Every staged writer manifest carries a ``writer_identity`` present in
     ``build/lib/writer_identities.py`` (the in-source allowlist).
  4. For every staged ``.json`` file under ``data/``, at least one staged
     manifest lists that path in its ``data_paths``. Non-JSON files under
     data/ (e.g. MANIFEST.md, README.md) are documentation and pass through
     without a manifest.

Only staged paths are inspected. Already-committed historical manifests that
are not staged remain grandfathered, while every newly staged or modified
manifest must pass the schema and identity checks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterable

import jsonschema

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib import writer_identities  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402


WRITER_MANIFEST_SCHEMA_RELATIVE_PATH = "schemas/v1/writer_manifest.schema.json"
WRITER_IDENTITIES_RELATIVE_PATH = "build/lib/writer_identities.py"
EXECUTING_WRITER_IDENTITIES_PATH = Path(writer_identities.__file__).resolve()


class ManifestLoadError(ValueError):
    """A staged writer manifest cannot be loaded or contains invalid JSON."""


class StagedPathDiscoveryError(RuntimeError):
    """Git could not determine which paths are staged for the current index."""


class StagedSchemaError(ValueError):
    """The writer-manifest schema could not be loaded from the staged index."""


class StagedIdentityAllowlistError(ValueError):
    """The staged identity allowlist cannot safely back the executing authorizer."""


_UNREADABLE_STAGED_BLOB = object()


def _staged_paths(*, repo_root: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(repo_root),
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", None) or str(exc)
        raise StagedPathDiscoveryError(
            f"git staged-path discovery failed: {str(detail).strip()}"
        ) from exc
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def _staged_blob(path: str, *, repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "show", f":0:{path}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(repo_root),
            check=True,
        )
    except subprocess.CalledProcessError:
        return None
    return result.stdout


def _staged_blob_bytes(path: str, *, repo_root: Path) -> bytes | None:
    try:
        result = subprocess.run(
            ["git", "show", f":0:{path}"],
            capture_output=True,
            cwd=str(repo_root),
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout


def _load_manifest(path: str, *, repo_root: Path) -> object:
    text = _staged_blob(path, repo_root=repo_root)
    if text is None:
        return _UNREADABLE_STAGED_BLOB
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ManifestLoadError(
            f"staged manifest at {path} contains malformed JSON at line {exc.lineno}, "
            f"column {exc.colno}: {exc.msg}"
        ) from exc


def _manifest_validator(*, repo_root: Path) -> jsonschema.Draft202012Validator:
    schema_text = _staged_blob(WRITER_MANIFEST_SCHEMA_RELATIVE_PATH, repo_root=repo_root)
    if schema_text is None:
        raise StagedSchemaError(
            "writer-manifest schema could not be loaded from the staged index at "
            f"{WRITER_MANIFEST_SCHEMA_RELATIVE_PATH}"
        )
    try:
        schema = json.loads(schema_text)
    except json.JSONDecodeError as exc:
        raise StagedSchemaError(
            "staged writer-manifest schema contains malformed JSON at "
            f"line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as exc:
        raise StagedSchemaError(f"staged writer-manifest schema is invalid: {exc.message}") from exc
    return jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())


def _normalized_source_digest(content: bytes, *, label: str) -> str:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StagedIdentityAllowlistError(
            f"{label} is not readable UTF-8 at byte {exc.start}"
        ) from exc
    # Git stores LF while Windows working trees may use CRLF. Normalize only
    # line endings so equivalent Python source receives the same digest.
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def _verify_staged_identity_allowlist(*, repo_root: Path) -> None:
    """Trust the imported authorizer only when staged source matches; never execute staged code."""

    staged_source = _staged_blob_bytes(WRITER_IDENTITIES_RELATIVE_PATH, repo_root=repo_root)
    if staged_source is None:
        raise StagedIdentityAllowlistError(
            "writer-identity allowlist could not be loaded from the staged index at "
            f"{WRITER_IDENTITIES_RELATIVE_PATH}"
        )
    try:
        executing_source = EXECUTING_WRITER_IDENTITIES_PATH.read_bytes()
    except OSError as exc:
        raise StagedIdentityAllowlistError(
            "executing writer-identity allowlist source is unreadable"
        ) from exc

    staged_digest = _normalized_source_digest(
        staged_source, label="staged writer-identity allowlist"
    )
    executing_digest = _normalized_source_digest(
        executing_source, label="executing writer-identity allowlist"
    )
    if staged_digest != executing_digest:
        raise StagedIdentityAllowlistError(
            "staged writer-identity allowlist differs from the executing allowlist; "
            "refusing to authorize identities "
            f"(staged sha256={staged_digest}, executing sha256={executing_digest})"
        )


def _schema_error_path(error: jsonschema.ValidationError) -> str:
    path = "/".join(str(part) for part in error.absolute_path)
    return path or "<root>"


def evaluate_gate(
    staged: Iterable[str],
    *,
    load_manifest: Callable[[str], object | None] | None = None,
    repo_root: Path = REPO_ROOT,
) -> tuple[int, list[str]]:
    """Return ``(exit_code, messages)``.

    ``load_manifest`` is an optional callable ``(path) -> object | None`` so the
    gate can be tested without going through git. When not provided, manifests
    are loaded from the staged index via ``git show :0:<path>``.
    """
    staged_list = [p.replace("\\", "/") for p in staged]
    # Only JSON files are parser output. Markdown docs (MANIFEST.md, README.md)
    # under data/ are human-written documentation and don't carry writer identity.
    data_edits = sorted({p for p in staged_list if p.startswith("data/") and p.endswith(".json")})
    manifest_paths = sorted(
        {p for p in staged_list if p.startswith("review/writer-manifests/") and p.endswith(".json")}
    )

    messages: list[str] = []
    try:
        _verify_staged_identity_allowlist(repo_root=repo_root)
    except StagedIdentityAllowlistError as exc:
        return 1, [f"BLOCKED: {exc}"]

    if not data_edits and not manifest_paths:
        return 0, messages  # No staged data or manifest edits; nothing to gate.

    if data_edits and not manifest_paths:
        messages.append(
            "BLOCKED: data/ edit(s) staged with no review/writer-manifests/<run_id>.json: "
            + ", ".join(data_edits)
        )
        messages.append(
            "Every write to data/ must ship a paired writer manifest. Hand-edits to data/ are forbidden."
        )
        return 1, messages

    loader = load_manifest or (lambda p: _load_manifest(p, repo_root=repo_root))
    custom_loader = load_manifest is not None
    covered: dict[str, list[str]] = {}
    failed_identities: list[str] = []
    manifest_errors = False
    try:
        validator = _manifest_validator(repo_root=repo_root)
    except StagedSchemaError as exc:
        return 1, [f"BLOCKED: {exc}"]
    for mp in manifest_paths:
        try:
            body = loader(mp)
        except (ManifestLoadError, json.JSONDecodeError) as exc:
            manifest_errors = True
            messages.append(f"BLOCKED: {exc}")
            continue
        if body is _UNREADABLE_STAGED_BLOB or (custom_loader and body is None):
            manifest_errors = True
            messages.append(
                f"BLOCKED: manifest at {mp} could not be loaded from the staged index; "
                "staged content unreadable"
            )
            continue

        if isinstance(body, dict):
            identity = body.get("writer_identity") or "<missing>"
            if not isinstance(identity, str) or not writer_identities.is_authorised(identity):
                failed_identities.append(
                    f"  {mp}: writer_identity={identity!r} is not in build/lib/writer_identities.py"
                )

        schema_errors = sorted(
            validator.iter_errors(body),
            key=lambda error: (tuple(str(part) for part in error.absolute_path), error.message),
        )
        if schema_errors:
            manifest_errors = True
            messages.append(
                f"BLOCKED: staged writer manifest at {mp} fails validation against "
                "schemas/v1/writer_manifest.schema.json:"
            )
            messages.extend(
                f"  {_schema_error_path(error)}: {error.message}" for error in schema_errors
            )
            continue

        assert isinstance(body, dict)  # The schema's root type is object.
        for dp in body["data_paths"]:
            covered.setdefault(dp.replace("\\", "/"), []).append(mp)

    if failed_identities:
        messages.append(
            "BLOCKED: writer manifest(s) carry unregistered writer_identity values. "
            "Add the identity to build/lib/writer_identities.py via a deliberate source change "
            "(test fixtures may NOT register)."
        )
        messages.extend(failed_identities)
    if failed_identities or manifest_errors:
        return 1, messages

    uncovered = [p for p in data_edits if p not in covered]
    if uncovered:
        messages.append("BLOCKED: data/ edit(s) not declared in any staged manifest:")
        for p in uncovered:
            messages.append(f"  {p}")
        return 1, messages

    return 0, messages


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root (defaults to the OCD repo containing this script).",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        staged = _staged_paths(repo_root=args.repo_root)
    except StagedPathDiscoveryError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1
    rc, messages = evaluate_gate(staged, repo_root=args.repo_root)
    for m in messages:
        print(m, file=sys.stderr if rc else sys.stdout)
    return rc


if __name__ == "__main__":
    sys.exit(main())
