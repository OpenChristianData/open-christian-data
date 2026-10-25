"""Private, deterministic projection receipts."""

from __future__ import annotations

from typing import Any

from ocd_kernel.library._common import sha256_bytes
from ocd_kernel.projection.categories.prose import (
    ASSEMBLER_VERSION,
    MAPPING_VERSION,
    Projection,
)


RECEIPT_VERSION = "ocd-projection-receipt-provisional-v1"


def build_receipt(
    *,
    work_id: str,
    textual_form_id: str,
    edition_id: str,
    acquisition_id: str,
    master_relative_path: str,
    source_sha256: str,
    retained_sha256: str,
    source_path: str | None,
    acquisition_relative_path: str,
    public_relative_path: str,
    public_bytes: bytes,
    projection: Projection,
    independent_check: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "provisional-v1",
        "receipt_version": RECEIPT_VERSION,
        "contract": "ocd-projection-receipt-v1",
        "identity": {
            "work_id": work_id,
            "textual_form_id": textual_form_id,
            "edition_id": edition_id,
            "acquisition_id": acquisition_id,
        },
        "inputs": {
            "master_path": master_relative_path,
            "master_sha256": projection.master_sha256,
            "source_sha256": source_sha256,
            "retained_sha256": retained_sha256,
            "source_path": source_path,
            "acquisition_path": acquisition_relative_path,
        },
        "mapping": {
            "version": MAPPING_VERSION,
            "category": "prose",
            "anchors": projection.anchors,
        },
        "assembler": {"version": ASSEMBLER_VERSION},
        "outputs": {
            "public_path": public_relative_path,
            "public_sha256": sha256_bytes(public_bytes),
            "row_count": len(projection.rows),
            "text_hashes": [anchor["text_sha256"] for anchor in projection.anchors],
            "sequences": [anchor["sequence"] for anchor in projection.anchors],
        },
        "warnings": list(projection.warnings),
        "exclusions": list(projection.exclusions),
        "independent_check": independent_check
        or {"status": "pending", "errors": []},
    }


def check_receipt_shape(receipt: dict[str, Any]) -> list[str]:
    """Check the receipt's structural invariants before expensive projection."""

    errors: list[str] = []
    for key in (
        "schema_version",
        "receipt_version",
        "contract",
        "identity",
        "inputs",
        "mapping",
        "assembler",
        "outputs",
        "warnings",
        "exclusions",
        "independent_check",
    ):
        if key not in receipt:
            errors.append(f"receipt missing {key}")
    if receipt.get("contract") != "ocd-projection-receipt-v1":
        errors.append("receipt contract mismatch")
    identity = receipt.get("identity")
    if not isinstance(identity, dict):
        errors.append("receipt identity must be object")
    else:
        for key in ("work_id", "textual_form_id", "edition_id", "acquisition_id"):
            if not isinstance(identity.get(key), str) or not identity[key]:
                errors.append(f"receipt identity missing {key}")
    inputs = receipt.get("inputs")
    if not isinstance(inputs, dict):
        errors.append("receipt inputs must be object")
    else:
        for key in (
            "master_path",
            "master_sha256",
            "source_sha256",
            "retained_sha256",
            "acquisition_path",
        ):
            if not isinstance(inputs.get(key), str) or not inputs[key]:
                errors.append(f"receipt inputs missing {key}")
    mapping = receipt.get("mapping")
    if not isinstance(mapping, dict) or not isinstance(mapping.get("anchors"), list):
        errors.append("receipt mapping anchors must be list")
    outputs = receipt.get("outputs")
    if not isinstance(outputs, dict):
        errors.append("receipt outputs must be object")
    else:
        for key in ("public_path", "public_sha256", "row_count", "text_hashes", "sequences"):
            if key not in outputs:
                errors.append(f"receipt outputs missing {key}")
    check = receipt.get("independent_check")
    if not isinstance(check, dict) or check.get("status") not in {"pending", "pass", "fail"}:
        errors.append("receipt independent_check status is invalid")
    return errors


def build_correspondence_receipt(
    projection: dict[str, Any], *, identity: dict[str, str],
    authority: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind producer claims, leaving independent verification pending.

    A caller-supplied status is never proof. Store the checker result in
    separate evidence that identifies the checker and binds its inputs.
    """
    from copy import deepcopy
    from ocd_kernel.projection.envelope import canonical_row_bytes
    receipt = {key: deepcopy(projection[key]) for key in (
        "mapping_version", "master_sha256", "book_codes_sha256", "scope_id", "anchors", "inventory",
        "references", "warnings", "exclusions",
    )}
    receipt.update(schema_version="2.0", assembler_version="ocd-correspondence-assembler-provisional-v1", identity=deepcopy(identity),
                   authority=deepcopy(authority if authority is not None else projection.get("authority", {})),
                   output_sha256=sha256_bytes(canonical_row_bytes(projection["rows"])),
                   row_count=len(projection["rows"]),
                   independent_check={"status": "pending", "errors": []})
    return receipt
