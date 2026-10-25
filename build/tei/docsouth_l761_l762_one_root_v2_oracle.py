"""Independent one-root DocSouth oracle extended for retained image bytes."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Mapping

from build.tei.docsouth_l761_l762_one_root_oracle import _oracle as _one_root_oracle
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-docsouth-l761-l762-one-root-retained-assets-oracle"
ORACLE_VERSION = "2"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _oracle(manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    """Recheck retained asset authority, inventory, and candidate accounting."""
    result = dict(_one_root_oracle(manifest, candidate))
    findings = list(result["findings"])
    profile = json.loads(manifest.authority_path("profile").read_bytes())
    receipt = json.loads(manifest.authority_path("acquisition-receipt").read_bytes())
    account = json.loads(candidate.member_bytes("source-accountability.json"))

    expected_assets = profile.get("retained_support_members")
    receipt_assets = [
        {
            "entity": item["entity"],
            "path": item["path"],
            "sha256": item["sha256"],
            "source_url": item["source_url"],
            "bytes": item["bytes"],
        }
        for item in receipt.get("image_members", [])
    ]
    if expected_assets != receipt_assets:
        findings.append("retained image profile differs from acquisition receipt")

    authorities = {
        item["entity"]: item
        for item in manifest.record["authorities"]
        if item.get("role") == "supporting-source-asset"
    }
    expected_by_entity = {item["entity"]: item for item in expected_assets or []}
    if set(authorities) != set(expected_by_entity):
        findings.append("source manifest retained-image authority set differs")
    for entity, expected in expected_by_entity.items():
        authority = authorities.get(entity)
        if authority is None:
            continue
        raw = manifest.authority_path(authority["name"]).read_bytes()
        if (
            authority.get("path") != expected["path"]
            or authority.get("bytes") != expected["bytes"]
            or authority.get("sha256") != expected["sha256"]
            or len(raw) != expected["bytes"]
            or _sha(raw) != expected["sha256"]
        ):
            findings.append(f"retained image authority differs: {entity}")

    inventory_bytes = manifest.authority_path("member-inventory").read_bytes()
    if _sha(inventory_bytes) != receipt["verification"]["member_inventory_sha256"]:
        findings.append("retained member inventory differs from acquisition receipt")
    inventory_rows = list(
        csv.DictReader(inventory_bytes.decode("utf-8").splitlines(), delimiter="\t")
    )
    expected_inventory = {
        receipt["member"]["path"].rsplit("/", 1)[-1]: (
            receipt["member"]["bytes"],
            receipt["member"]["sha256"],
        )
    }
    expected_inventory.update(
        {
            item["path"].rsplit("/", 1)[-1]: (item["bytes"], item["sha256"])
            for item in expected_assets or []
        }
    )
    observed_inventory = {
        row["path"]: (int(row["bytes"]), row["sha256"]) for row in inventory_rows
    }
    if observed_inventory != expected_inventory:
        findings.append("retained member inventory rows differ from exact source members")

    if account.get("retained_support_members") != expected_assets:
        findings.append("candidate source accounting omits or changes retained image bytes")
    if account.get("acquisition_receipt_sha256") != _sha(
        manifest.authority_path("acquisition-receipt").read_bytes()
    ):
        findings.append("candidate source accounting does not bind current acquisition receipt")
    if account.get("member_inventory_sha256") != _sha(inventory_bytes):
        findings.append("candidate source accounting does not bind current complete member inventory")

    result["status"] = "pass" if not findings else "fail"
    result["oracle_id"] = ORACLE_ID
    result["oracle_version"] = ORACLE_VERSION
    result["implementation_sha256"] = _sha(Path(__file__).read_bytes())
    result["import_closure_sha256"] = _sha(
        Path(__file__).read_bytes()
        + Path(_one_root_oracle.__code__.co_filename).read_bytes()
    )
    result["findings"] = findings
    result.pop("result_sha256", None)
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
