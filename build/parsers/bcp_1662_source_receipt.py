"""Exact retained-source receipt shared by the two BCP 1662 data producers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Sequence

from ocd_kernel.reconstruction.contract import SourceManifest


SOURCE_MANIFEST = Path("sources/structured-text/bcp-1662/bcp-1662.source-manifest.v2.json")
SOURCE_HASH_SCOPE = (
    "ocd-source-member-set-v1 for bcp-1662-retained-partial-html "
    "(25 retained members; partial expression)"
)


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def verified_source_member_set_sha256(
    repository_root: Path,
    *,
    member_kind: str,
    logical_names: Sequence[str],
) -> str:
    """Verify one producer's exact subset and return the governed bundle digest."""

    manifest = SourceManifest.load(
        repository_root / SOURCE_MANIFEST,
        repository_root=repository_root,
    )
    members = manifest.record["source_members"]
    selected_names = tuple(
        str(member["logical_name"])
        for member in members
        if member["kind"] == member_kind
    )
    if selected_names != tuple(logical_names):
        raise ValueError(
            f"BCP {member_kind} producer members do not match the governed source subset"
        )

    primary = [
        authority
        for authority in manifest.record["authorities"]
        if authority["role"] == "primary-source"
    ]
    member_identities = {
        (member["path"], member["bytes"], member["sha256"]) for member in members
    }
    primary_identities = {
        (authority["path"], authority["bytes"], authority["sha256"])
        for authority in primary
    }
    if len(members) != 25 or member_identities != primary_identities:
        raise ValueError("BCP retained source members and primary authorities diverged")

    receipt = {
        "contract": "ocd-source-member-set-v1",
        "members": sorted(
            (
                {
                    "name": authority["name"],
                    "path": authority["path"],
                    "bytes": authority["bytes"],
                    "sha256": authority["sha256"],
                }
                for authority in primary
            ),
            key=lambda item: (str(item["path"]), str(item["name"])),
        ),
    }
    return hashlib.sha256(_canonical(receipt)).hexdigest()


__all__ = [
    "SOURCE_HASH_SCOPE",
    "verified_source_member_set_sha256",
]
