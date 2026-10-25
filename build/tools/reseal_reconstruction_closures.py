"""Reseal live reconstruction-closure declarations without reformatting JSON.

The default mode is a dry run.  ``--apply`` performs only exact digest/value
substitutions and fails if any input changes between census and write.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from ocd_kernel.reconstruction.closure_verification import (
    check_validator_manifest_closure,
    check_producer_closures,
    check_validator_closures,
)
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import io_path


ROOT = Path(__file__).resolve().parents[2]
EXCLUDED_MANIFESTS = (
    "sources/devotionals/spurgeons-morning-evening/lib030.source-manifest.json",
    "sources/spurgeon-mtp/spurgeon-mtp.source-manifest.json",
    "sources/structured-text/lib052-john-owen/john-owen-lib052.source-manifest.json",
    "sources/structured-text/lib071-gutenberg-evangelical/work-bindings/drummond-greatest-thing/37c-135-source-underscore-emphasis-v1.source-manifest.json",
    "sources/structured-text/lib072-gutenberg-evangelical/work-bindings/wilberforce-practical-view/37c-322.source-manifest.json",
    "sources/structured-text/chrysostom-npnf113-lib041/npnf113-lib041.source-manifest.json",
)
LIB028_CLOSURE = "sources/structured-text/eusebius-ecclesiastical-history/lib028-tei-xsd-closure.json"


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _replace_once(content: bytes, old: str, new: str, *, context: str) -> bytes:
    old_bytes = old.encode("ascii")
    count = content.count(old_bytes)
    if count != 1:
        raise ValueError(f"expected one {context} occurrence, found {count}")
    return content.replace(old_bytes, new.encode("ascii"), 1)


def _flat_object(content: bytes, logical_path: str) -> tuple[int, int, dict[str, Any]]:
    marker = json.dumps(logical_path, ensure_ascii=False).encode("utf-8")
    position = content.find(marker)
    if position < 0:
        raise ValueError(f"binding path not found: {logical_path}")
    start = content.rfind(b"{", 0, position)
    end = content.find(b"}", position)
    if start < 0 or end < 0:
        raise ValueError(f"binding object is incomplete: {logical_path}")
    value = json.loads(content[start : end + 1])
    if not isinstance(value, dict) or value.get("path") != logical_path:
        raise ValueError(f"binding object is not flat or is ambiguous: {logical_path}")
    return start, end + 1, value


def _replace_binding(
    content: bytes,
    logical_path: str,
    *,
    new_bytes: int,
    new_sha256: str,
) -> bytes:
    start, end, binding = _flat_object(content, logical_path)
    old_bytes = binding.get("bytes")
    old_sha = binding.get("sha256")
    if not isinstance(old_bytes, int) or not isinstance(old_sha, str):
        raise ValueError(f"binding lacks byte/hash identity: {logical_path}")
    segment = content[start:end]
    segment = _replace_once(
        segment, str(old_bytes), str(new_bytes), context=f"byte identity for {logical_path}"
    )
    segment = _replace_once(
        segment, old_sha, new_sha256, context=f"digest identity for {logical_path}"
    )
    return content[:start] + segment + content[end:]


def _refresh_pinned_authority(
    manifest_content: bytes,
    *,
    authority_name: str,
    expected_sha256: str,
) -> tuple[bytes, dict[str, object]]:
    record = json.loads(manifest_content)
    authorities = record.get("authorities")
    if not isinstance(authorities, list):
        raise ValueError("source manifest authorities are invalid")
    matches = [
        item for item in authorities
        if isinstance(item, dict) and item.get("name") == authority_name
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one authority named {authority_name!r}, found {len(matches)}")
    authority = matches[0]
    logical = authority.get("path")
    if not isinstance(logical, str) or not logical:
        raise ValueError(f"authority {authority_name!r} has no repository-relative path")
    if authority.get("sha256") != expected_sha256:
        raise ValueError(
            f"authority {authority_name!r} prior digest differs from the explicitly supplied digest"
        )
    authority_file = io_path(resolve_repo_path(ROOT, logical))
    authority_bytes = authority_file.read_bytes()
    actual_sha = _sha(authority_bytes)
    refreshed = _replace_binding(
        manifest_content,
        logical,
        new_bytes=len(authority_bytes),
        new_sha256=actual_sha,
    )
    return refreshed, {
        "kind": "authority-binding",
        "authority_name": authority_name,
        "authority_path": logical,
        "before_bytes": authority["bytes"],
        "before_sha256": expected_sha256,
        "after_bytes": len(authority_bytes),
        "after_sha256": actual_sha,
    }


def _lib028_updates(content: bytes) -> tuple[bytes, str]:
    record = json.loads(content)
    producer = record["producer_runtime"]
    members = producer["members"]
    live = []
    updated = content
    for member in members:
        logical = str(member["path"])
        body = (ROOT / logical).resolve(strict=True).read_bytes()
        live.append({"path": logical, "bytes": len(body), "sha256": _sha(body)})
        if member["bytes"] != len(body) or member["sha256"] != _sha(body):
            updated = _replace_binding(
                updated,
                logical,
                new_bytes=len(body),
                new_sha256=_sha(body),
            )
    digest = _sha(_canonical(live))
    if producer["sha256"] != digest:
        updated = _replace_once(
            updated,
            str(producer["sha256"]),
            digest,
            context="LIB-028 producer runtime closure digest",
        )
    return updated, digest


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--validator-manifest",
        action="append",
        default=[],
        metavar="REPO_RELATIVE_PATH",
        help=(
            "reseal only the validator closure for this source manifest; repeat to "
            "select multiple manifests. Producer and shared-authority closures are not touched."
        ),
    )
    parser.add_argument(
        "--refresh-authority-binding",
        action="append",
        default=[],
        metavar="MANIFEST::AUTHORITY::EXPECTED_OLD_SHA256",
        help=(
            "refresh one explicitly named authority in a selected validator manifest to its "
            "current retained bytes; requires --validator-manifest and the exact prior digest"
        ),
    )
    args = parser.parse_args()

    selected_manifests = [Path(item).as_posix() for item in args.validator_manifest]
    if len(selected_manifests) != len(set(selected_manifests)):
        raise ValueError("validator manifest scope contains duplicate paths")
    if any(path in EXCLUDED_MANIFESTS for path in selected_manifests):
        raise ValueError("validator manifest scope includes a route excluded from resealing")
    requested_authorities: list[tuple[str, str, str]] = []
    for value in args.refresh_authority_binding:
        fields = value.split("::")
        if len(fields) != 3 or not fields[2]:
            raise ValueError("authority binding must use MANIFEST::AUTHORITY::EXPECTED_OLD_SHA256")
        manifest_path, authority_name, expected_sha256 = fields
        manifest_path = Path(manifest_path).as_posix()
        if manifest_path not in selected_manifests:
            raise ValueError("authority binding manifest must also be selected with --validator-manifest")
        if len(expected_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in expected_sha256):
            raise ValueError("expected authority digest must be a lowercase SHA-256")
        requested_authorities.append((manifest_path, authority_name, expected_sha256))

    original: dict[Path, bytes] = {}
    updated: dict[Path, bytes] = {}
    semantic_changes: list[dict[str, object]] = []

    def content(path: Path) -> bytes:
        resolved = path.resolve(strict=True)
        if resolved not in original:
            original[resolved] = resolved.read_bytes()
            updated[resolved] = original[resolved]
        return updated[resolved]

    def set_content(path: Path, value: bytes) -> None:
        resolved = path.resolve(strict=True)
        content(resolved)
        updated[resolved] = value

    if selected_manifests:
        checks = [
            check_validator_manifest_closure(ROOT, relative_path)
            for relative_path in selected_manifests
        ]
    else:
        lib028 = (ROOT / LIB028_CLOSURE).resolve(strict=True)
        lib028_updated, lib028_digest = _lib028_updates(content(lib028))
        set_content(lib028, lib028_updated)
        checks = [
            *check_validator_closures(ROOT, excluded_manifest_paths=EXCLUDED_MANIFESTS),
            *check_producer_closures(ROOT, excluded_manifest_paths=EXCLUDED_MANIFESTS),
        ]

    for check in checks:
        if check.matches:
            continue
        path = (ROOT / check.manifest_path).resolve(strict=True)
        set_content(
            path,
            _replace_once(
                content(path),
                check.declared_sha256,
                check.live_sha256,
                context=f"{check.kind} closure in {check.manifest_path}",
            ),
        )
        semantic_changes.append(
            {
                "path": check.manifest_path,
                "kind": check.kind,
                "implementation_path": check.implementation_path,
                "strategy": check.strategy,
                "before": check.declared_sha256,
                "after": check.live_sha256,
            }
        )

    for manifest_path, authority_name, expected_sha256 in requested_authorities:
        path = (ROOT / manifest_path).resolve(strict=True)
        updated_content, change = _refresh_pinned_authority(
            content(path),
            authority_name=authority_name,
            expected_sha256=expected_sha256,
        )
        set_content(path, updated_content)
        if change["before_sha256"] != change["after_sha256"] or change["before_bytes"] != change["after_bytes"]:
            change["path"] = manifest_path
            semantic_changes.append(change)

    if selected_manifests:
        authority_targets = {}
    else:
        lib028_profile = ROOT / "sources/structured-text/eusebius-ecclesiastical-history/lib028.reconstruction-profile.json"
        lib028_profile_record = json.loads(content(lib028_profile))
        if lib028_profile_record.get("producer_import_closure_sha256") != lib028_digest:
            raise ValueError("LIB-028 profile did not converge on the live governed closure")

        authority_targets = {
            path.relative_to(ROOT).as_posix(): value
            for path, value in updated.items()
            if value != original[path]
            and path.relative_to(ROOT).as_posix().endswith(
                (".reconstruction-profile.json", "lib028-tei-xsd-closure.json")
            )
        }
        for manifest in (ROOT / "sources").rglob("*source-manifest.json"):
            manifest = manifest.resolve(strict=True)
            if manifest.relative_to(ROOT).as_posix() in EXCLUDED_MANIFESTS:
                continue
            manifest_content = content(manifest)
            for logical, authority_content in authority_targets.items():
                if json.dumps(logical).encode("utf-8") not in manifest_content:
                    continue
                manifest_content = _replace_binding(
                    manifest_content,
                    logical,
                    new_bytes=len(authority_content),
                    new_sha256=_sha(authority_content),
                )
                semantic_changes.append(
                    {
                        "path": manifest.relative_to(ROOT).as_posix(),
                        "kind": "authority-binding",
                        "authority_path": logical,
                        "after_bytes": len(authority_content),
                        "after_sha256": _sha(authority_content),
                    }
                )
            set_content(manifest, manifest_content)

    writes = []
    for path, value in updated.items():
        if value == original[path]:
            continue
        logical = path.relative_to(ROOT).as_posix()
        if any(token in logical for token in ("lib030", "spurgeon-mtp", "lib052")):
            raise ValueError(f"excluded lane write attempted: {logical}")
        writes.append(
            {
                "path": logical,
                "before_bytes": len(original[path]),
                "before_sha256": _sha(original[path]),
                "after_bytes": len(value),
                "after_sha256": _sha(value),
            }
        )

    if args.apply:
        for path in updated:
            if path.read_bytes() != original[path]:
                raise RuntimeError(f"concurrent modification detected before write: {path}")
        for path, value in updated.items():
            if value != original[path]:
                path.write_bytes(value)

    report = {
        "contract": "ocd-reconstruction-closure-reacceptance-census-v1",
        "mode": "apply" if args.apply else "dry-run",
        "scope": {
            "validator_manifests_only": selected_manifests,
            "producer_and_shared_authorities_touched": False,
        } if selected_manifests else {"validator_manifests_only": None},
        "excluded_manifest_paths": list(EXCLUDED_MANIFESTS),
        "validator_checks": sum(check.kind == "validator" for check in checks),
        "producer_checks": sum(check.kind == "producer" for check in checks),
        "semantic_changes": semantic_changes,
        "writes": writes,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
