"""Phase 0 validator: ensure every resource in data/ has a valid sources/<resource>/witnesses.json file.

For each resource currently in ``data/`` (grouped by ``meta.id``):

  * ``sources/<meta.id>/witnesses.json`` must exist.
  * The file must validate against ``schemas/v1/witness_inventory.schema.json``.
  * Every witness's ``related_resource_id`` must match the resource it lives under.
  * Every witness must have ``verified`` set; when ``verified: true``,
    ``checksum_sha256`` and ``captured_at_utc`` must be non-null.

Output: one line per resource showing PASS / MISSING / FAIL plus a per-witness
breakdown for FAIL entries. Exits non-zero when any resource fails.

URL reachability is reported as a follow-up check that runs only when
``--check-urls`` is passed; it is opt-in because Phase 0 done gate is bounded
and network calls are not appropriate for CI by default.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request  # standards: download only

import jsonschema

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))
from build.lib.paths import REPO_ROOT  # noqa: E402


SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "witness_inventory.schema.json"


def _enumerate_resources(data_root: Path) -> dict[str, list[Path]]:
    by_id: dict[str, list[Path]] = defaultdict(list)
    for path in sorted(data_root.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        meta = payload.get("meta") if isinstance(payload, dict) else None
        if not isinstance(meta, dict):
            continue
        rid = meta.get("id")
        if isinstance(rid, str) and rid:
            by_id[rid].append(path)
    return by_id


def _check_inventory(
    resource_id: str,
    path: Path,
    schema: dict,
    *,
    check_urls: bool,
) -> tuple[str, list[str]]:
    """Return ``(status, messages)`` for one resource."""
    if not path.exists():
        return "MISSING", [f"no witnesses.json at {path}"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return "FAIL", [f"unreadable JSON: {exc}"]
    try:
        jsonschema.validate(instance=payload, schema=schema)
    except jsonschema.ValidationError as exc:
        return "FAIL", [f"schema violation: {exc.message}"]

    issues: list[str] = []
    declared_rid = payload.get("related_resource_id")
    if declared_rid != resource_id:
        issues.append(
            f"related_resource_id={declared_rid!r} does not match owning resource {resource_id!r}"
        )
    for w in payload.get("witnesses", []):
        wid = w.get("witness_id", "<unnamed>")
        if w.get("related_resource_id") != resource_id:
            issues.append(
                f"witness {wid}: related_resource_id={w.get('related_resource_id')!r} != {resource_id!r}"
            )
        if w.get("verified") is True:
            if not w.get("checksum_sha256"):
                issues.append(f"witness {wid}: verified=true but checksum_sha256 is missing")
            if not w.get("captured_at_utc"):
                issues.append(f"witness {wid}: verified=true but captured_at_utc is missing")
        if check_urls and w.get("url"):
            ok = _url_reachable(w["url"])
            if not ok:
                issues.append(f"witness {wid}: url did not respond to a HEAD probe: {w['url']}")
    return ("FAIL" if issues else "PASS"), issues


def _url_reachable(url: str, *, timeout: float = 10.0) -> bool:
    """Best-effort HEAD probe. Returns True on 2xx/3xx; False on network errors or 4xx/5xx."""
    try:
        req = urllib_request.Request(url, method="HEAD")
        with urllib_request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 400
    except urllib_error.HTTPError as exc:
        return 200 <= exc.code < 400
    except (urllib_error.URLError, TimeoutError, ConnectionError):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Phase 0 witness inventories.")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root (defaults to the OCD repo containing this script).",
    )
    parser.add_argument(
        "--check-urls",
        action="store_true",
        help="Also issue a HEAD probe against each witness's url (slow; opt-in).",
    )
    parser.add_argument(
        "--allow-missing-pilot",
        action="store_true",
        help="Allow resources without a witnesses.json (treat MISSING as warning, not failure). Use only during phase-0 ramp-up.",
    )
    args = parser.parse_args(argv)

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    data_root = args.repo_root / "data"
    sources_root = args.repo_root / "sources"

    resources = _enumerate_resources(data_root)
    if not resources:
        print(f"No resources found under {data_root}", file=sys.stderr)
        return 2

    pass_count = 0
    miss_count = 0
    fail_count = 0
    fail_lines: list[str] = []
    miss_lines: list[str] = []
    for rid in sorted(resources):
        target = sources_root / rid / "witnesses.json"
        status, issues = _check_inventory(rid, target, schema, check_urls=args.check_urls)
        if status == "PASS":
            pass_count += 1
        elif status == "MISSING":
            miss_count += 1
            miss_lines.append(f"  MISSING  {rid}  -> sources/{rid}/witnesses.json")
        else:
            fail_count += 1
            fail_lines.append(f"  FAIL     {rid}")
            for issue in issues:
                fail_lines.append(f"             - {issue}")
    print(f"Resources discovered in data/: {len(resources)}")
    print(f"  PASS:    {pass_count}")
    print(f"  MISSING: {miss_count}")
    print(f"  FAIL:    {fail_count}")
    if miss_lines:
        print("")
        print("Missing inventories (run scaffold_witness_inventory.py to create empty stubs):")
        for line in miss_lines:
            print(line)
    if fail_lines:
        print("")
        print("Failing inventories:")
        for line in fail_lines:
            print(line)

    if fail_count > 0:
        return 1
    if miss_count > 0 and not args.allow_missing_pilot:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
