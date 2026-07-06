"""Pre-commit gate: every staged data/ JSON file must be paired with a writer manifest.

A1 block-case scope. The gate checks:

  1. For every staged ``.json`` file under ``data/``, at least one staged manifest
     under ``review/writer-manifests/<run_id>.json`` lists that path in its
     ``data_paths``. Non-JSON files under data/ (e.g. MANIFEST.md, README.md)
     are documentation and pass through without a manifest.
  2. For every staged writer manifest, its ``writer_identity`` is present in
     ``build/lib/writer_identities.py`` (the in-source allowlist).

When either check fails, exit 1 with a clear message. The A2 work bolts on
the rich validation -- checksum match, allowed_field_paths, delta tolerance,
rename handling. A1 deliberately ships block-case only so the allow case
cannot be smuggled through a hand-crafted test fixture.

Skips silently when there are no staged ``data/*.json`` paths -- non-data
commits and documentation-only data/ commits fall through to the rest of the
hook chain.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Iterable

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib import writer_identities  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402


WRITER_MANIFEST_SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "writer_manifest.schema.json"


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
    except subprocess.CalledProcessError:
        return []
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


def _load_manifest(path: str, *, repo_root: Path) -> dict | None:
    text = _staged_blob(path, repo_root=repo_root)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def evaluate_gate(
    staged: Iterable[str],
    *,
    load_manifest=None,
    identity_authoriser=writer_identities.is_authorised,
) -> tuple[int, list[str]]:
    """Return ``(exit_code, messages)``.

    ``load_manifest`` is an optional callable ``(path) -> dict | None`` so the
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
    if not data_edits:
        return 0, messages  # No data/ edits; nothing to gate.

    if not manifest_paths:
        messages.append(
            "BLOCKED: data/ edit(s) staged with no review/writer-manifests/<run_id>.json: "
            + ", ".join(data_edits)
        )
        messages.append(
            "Every write to data/ must ship a paired writer manifest. Hand-edits to data/ are forbidden."
        )
        return 1, messages

    loader = load_manifest or (lambda p: _load_manifest(p, repo_root=REPO_ROOT))
    manifests: dict[str, dict] = {}
    covered: dict[str, list[str]] = {}
    failed_identities: list[str] = []
    for mp in manifest_paths:
        body = loader(mp)
        if body is None:
            messages.append(f"manifest at {mp} could not be loaded; staged content unreadable")
            continue
        manifests[mp] = body
        identity = body.get("writer_identity") or "<missing>"
        if not identity_authoriser(identity):
            failed_identities.append(f"  {mp}: writer_identity={identity!r} is not in build/lib/writer_identities.py")
        for dp in body.get("data_paths", []) or []:
            covered.setdefault(dp.replace("\\", "/"), []).append(mp)

    if failed_identities:
        messages.append(
            "BLOCKED: writer manifest(s) carry unregistered writer_identity values. "
            "Add the identity to build/lib/writer_identities.py via a deliberate source change "
            "(test fixtures may NOT register)."
        )
        messages.extend(failed_identities)
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
    staged = _staged_paths(repo_root=args.repo_root)
    rc, messages = evaluate_gate(
        staged,
        load_manifest=lambda p: _load_manifest(p, repo_root=args.repo_root),
    )
    for m in messages:
        print(m, file=sys.stderr if rc else sys.stdout)
    return rc


if __name__ == "__main__":
    sys.exit(main())
