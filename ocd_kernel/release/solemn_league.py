"""Bound historical words around the Solemn League's two HTML accordion headings."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from typing import Any

from ocd_kernel.library._common import PipelineError, canonical_bytes
from ocd_kernel.projection.native_content import readable_content
from ocd_kernel.release.public_allowlist import _scan


CONTRACT = "ocd-public-solemn-league-historical-text-v1"
ITEM = "solemn-league-and-covenant--solemn-league-and-covenant-retained-electronic-witness"
LICENSE = (
    "Public domain (United States) for identified historical Solemn League and Covenant text and acts; "
    "The Westminster Standard electronic witness credited"
)
ACCEPTANCE_SHA256 = "fc05580c5e4d561121309b86b9bcd0bf2745273d11549d24c523d71714d97ed2"
MASTER_SHA256 = "813a27636fb25302ac1f975143556597fe0205167751e3b3e5259a38d5673c10"
PRIVATE_ROWS_SHA256 = "245738cb50e90df920d93cc4776502b7878e92cb037c548086afb1acf2d81d8e"
PUBLIC_ROWS_SHA256 = "7d7b2384a473e89f866842b86ec870b5e2a67e002de5fce04b90f4020d1ce78e"
WRAPPER_SHA256 = (
    "9630084de468955589de1652d45c0433246ce470d0b9027f3cd89a3893d0c3bf",
    "43e34493336dd82a601f9bb5f137f3112c7ab4196bbf6c3685c0a69e5d931a41",
)
REFERENCE_SHA256 = (
    "36028cab094b56531388fcb4f1685351aab6279b80cb7d938f6f3c8556cf2ff2",
    "24594bae2b32cdabe71cdc8d8e6f92ef29c2d106f883b389a14e124025b629ee",
)
HISTORICAL_HEADINGS = (
    "Assembly at EDINBURGH, August 17, 1643. Sess. 14.",
    "CHARLES I. Parl. 3. Sess. 1. Act 5.",
)
ICON = {"kind": "segment", "attributes": {"type": "html-icon", "number": "icon-plus-sign"},
        "content": []}


def _digest(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _authority(acceptance_sha256: str | None, master_sha256: str | None) -> dict[str, str]:
    if (acceptance_sha256, master_sha256) != (ACCEPTANCE_SHA256, MASTER_SHA256):
        raise PipelineError("Solemn League accepted historical-text authority differs")
    return {"acceptance_sha256": ACCEPTANCE_SHA256, "master_sha256": MASTER_SHA256}


def _heading(row: dict[str, Any]) -> dict[str, Any]:
    try:
        heading = row["structure"][0]["content"][0]["content"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise PipelineError("Solemn League source heading structure differs") from exc
    if (heading.get("kind") != "heading" or heading.get("attributes") != {"type": "html-h3"}
            or not isinstance(heading.get("content"), list)):
        raise PipelineError("Solemn League source heading structure differs")
    return heading


def _wrapper(wrapper: Any, index: int) -> bool:
    return (isinstance(wrapper, dict) and _digest(wrapper) == WRAPPER_SHA256[index]
            and wrapper.get("kind") == "source-reference"
            and wrapper.get("attributes") == {"type": "html-a", "source_target": "#"}
            and wrapper.get("content") == [ICON, {"kind": "text", "text": HISTORICAL_HEADINGS[index]}])


def _reference(reference: Any, index: int) -> bool:
    return (isinstance(reference, dict) and _digest(reference) == REFERENCE_SHA256[index]
            and reference.get("raw") == HISTORICAL_HEADINGS[index]
            and reference.get("target") == "#"
            and reference.get("normalization_attribute") == "target"
            and reference.get("normalization_status") == "unsupported-explicit-target")


def public_rows(rows: list[dict[str, Any]], *, acceptance_sha256: str | None,
                master_sha256: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Preserve all four historical units and their words, omitting two HTML controls."""
    authority = _authority(acceptance_sha256, master_sha256)
    if (len(rows) != 4 or any(row.get("license") != LICENSE for row in rows)
            or _digest(rows) != PRIVATE_ROWS_SHA256):
        raise PipelineError("Solemn League selected private rows differ")
    public = deepcopy(rows)
    removed = []
    for index, row_index in enumerate((1, 2)):
        row = public[row_index]
        heading = _heading(row)
        if (len(heading["content"]) != 1
                or not _wrapper(heading["content"][0], index)
                or len(row.get("source_references", [])) != 1
                or not _reference(row["source_references"][0], index)):
            raise PipelineError("Solemn League accordion inventory differs")
        removed.append({"wrapper": deepcopy(heading["content"][0]),
                        "reference": deepcopy(row["source_references"][0])})
        heading["content"] = [{"kind": "text", "text": HISTORICAL_HEADINGS[index]}]
        row["source_references"] = []
    if (any(row["text"] != readable_content(row["structure"][0]) for row in public)
            or [row["text"] for row in public] != [row["text"] for row in rows]
            or _digest(public) != PUBLIC_ROWS_SHA256
            or _scan(public, "Solemn League historical public rows")):
        raise PipelineError("Solemn League historical public rows differ")
    return public, {"contract": CONTRACT, "item_id": ITEM, "authority": authority,
                    "private_rows_sha256": PRIVATE_ROWS_SHA256,
                    "public_rows_sha256": PUBLIC_ROWS_SHA256, "removed": removed}


def restore_private_rows(rows: list[dict[str, Any]], artifact: dict[str, Any], *,
                         acceptance_sha256: str | None,
                         master_sha256: str | None) -> list[dict[str, Any]]:
    authority = _authority(acceptance_sha256, master_sha256)
    if (len(rows) != 4 or not isinstance(artifact, dict)
            or set(artifact) != {"contract", "item_id", "authority", "private_rows_sha256",
                                 "public_rows_sha256", "removed"}
            or artifact["contract"] != CONTRACT or artifact["item_id"] != ITEM
            or artifact["authority"] != authority
            or artifact["private_rows_sha256"] != PRIVATE_ROWS_SHA256
            or artifact["public_rows_sha256"] != PUBLIC_ROWS_SHA256
            or _digest(rows) != PUBLIC_ROWS_SHA256
            or not isinstance(artifact["removed"], list)
            or len(artifact["removed"]) != 2):
        raise PipelineError("Solemn League electronic-wrapper receipt differs")
    restored = deepcopy(rows)
    for index, row_index in enumerate((1, 2)):
        row = restored[row_index]
        heading = _heading(row)
        entry = artifact["removed"][index]
        if (not isinstance(entry, dict) or set(entry) != {"wrapper", "reference"}
                or not _wrapper(entry["wrapper"], index)
                or not _reference(entry["reference"], index)
                or heading["content"] != [{"kind": "text", "text": HISTORICAL_HEADINGS[index]}]
                or row.get("source_references") != []):
            raise PipelineError("Solemn League electronic-wrapper receipt differs")
        heading["content"] = [deepcopy(entry["wrapper"])]
        row["source_references"] = [deepcopy(entry["reference"])]
    if (_digest(restored) != PRIVATE_ROWS_SHA256
            or [row["text"] for row in restored] != [row["text"] for row in rows]):
        raise PipelineError("Solemn League private inverse differs")
    replay_rows, replay_artifact = public_rows(
        restored, acceptance_sha256=acceptance_sha256, master_sha256=master_sha256)
    if replay_rows != rows or replay_artifact != artifact:
        raise PipelineError("Solemn League public omission receipt is incomplete")
    return restored
