"""Bound four electronic contents links in the accepted Sum of Saving Knowledge."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from typing import Any

from ocd_kernel.library._common import PipelineError, canonical_bytes
from ocd_kernel.projection.native_content import readable_content
from ocd_kernel.release.public_allowlist import _scan


CONTRACT = "ocd-public-sum-saving-knowledge-historical-text-v1"
ITEM = "sum-of-saving-knowledge--sum-of-saving-knowledge-retained-electronic-witness"
LICENSE = (
    "Public domain (United States) for identified Dickson-Durham historical text and 1871 preface; "
    "The Westminster Standard electronic witness credited"
)
ACCEPTANCE_SHA256 = "48503fe82647e441a944164fad443d7273803fac0017a757279db84d81b09726"
MASTER_SHA256 = "9203d0bcfc831796800cf8f8047fd26eec29f5f1f52da523f42a1d9696ff2ada"
PRIVATE_ROWS_SHA256 = "c55abdfcb78ace72a2b434f3f8d8f4a97234a8c0eb49b72ce145322e5211a0bb"
PUBLIC_ROWS_SHA256 = "476d03daaa88cc1854f994f40a76185679fb06e791f986264404f74db4c17c03"
WRAPPER_SHA256 = (
    "f1cd865ba465e6816797fbf36e310f6732e5b584370fa6520fb499ea942162c3",
    "498670f675153696e6667b37b813e2b590ec164e3db94cfdb5aab9bd576b3523",
    "73855d3631a80ef1d5a4830354c922251135c29654579ee9ab9218e81fdb6e74",
    "f776e7ecb178dcb089625b62c844815a59be9ecdc7bf44041eb42ca3e9906a80",
)
REFERENCE_SHA256 = (
    "f5878a31f8c1b07ed61084fc283ec942c1d602964611658103ced2a4c8cf624c",
    "51ff3542d0555c837a2362abb01f1227d539bf7c00579053f136aa75b657a86f",
    "d37c40304cd0d54ed47ff502fabcf052e5bc9ce1c50a6310d6c7849d3167bd80",
    "5cb8687d2e4bf77372f40cddc25ed2e359976fc23d0c1cfc97547103fb492817",
)
HISTORICAL_HEADINGS = (
    "THE SUM OF SAVING KNOWLEDGE",
    "THE PRACTICAL USE OF SAVING KNOWLEDGE",
    "WARRANTS AND MOTIVES TO BELIEVE",
    "EVIDENCES OF TRUE FAITH",
)
POSITIONS = (3, 5, 7, 9)


def _digest(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _authority(acceptance_sha256: str | None, master_sha256: str | None) -> dict[str, str]:
    if (acceptance_sha256, master_sha256) != (ACCEPTANCE_SHA256, MASTER_SHA256):
        raise PipelineError("Sum of Saving Knowledge accepted authority differs")
    return {"acceptance_sha256": ACCEPTANCE_SHA256, "master_sha256": MASTER_SHA256}


def _slot(row: dict[str, Any], position: int) -> list[dict[str, Any]]:
    try:
        result = row["structure"][0]["content"][1]["content"][position]["content"][0]["content"][0]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise PipelineError("Sum of Saving Knowledge contents structure differs") from exc
    if not isinstance(result, list) or len(result) != 1:
        raise PipelineError("Sum of Saving Knowledge contents structure differs")
    return result


def _wrapper(value: Any, index: int) -> bool:
    return (isinstance(value, dict) and _digest(value) == WRAPPER_SHA256[index]
            and value.get("kind") == "source-reference"
            and value.get("attributes") == {"type": "html-a", "source_target": f"#{index+1}"}
            and value.get("content") == [{"kind": "text", "text": HISTORICAL_HEADINGS[index]}])


def _reference(value: Any, index: int) -> bool:
    return (isinstance(value, dict) and _digest(value) == REFERENCE_SHA256[index]
            and value.get("raw") == HISTORICAL_HEADINGS[index]
            and value.get("target") == f"#{index+1}"
            and value.get("normalization_attribute") == "target"
            and value.get("normalization_status") == "unsupported-explicit-target")


def public_rows(rows: list[dict[str, Any]], *, acceptance_sha256: str | None,
                master_sha256: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Keep six historical source units, including the signed 1871 preface."""
    authority = _authority(acceptance_sha256, master_sha256)
    if (len(rows) != 6 or any(row.get("license") != LICENSE for row in rows)
            or _digest(rows) != PRIVATE_ROWS_SHA256):
        raise PipelineError("Sum of Saving Knowledge selected private rows differ")
    public = deepcopy(rows)
    contents = public[0]
    references = contents.get("source_references")
    if not isinstance(references, list) or len(references) != 4:
        raise PipelineError("Sum of Saving Knowledge contents references differ")
    removed = []
    for index, position in enumerate(POSITIONS):
        slot = _slot(contents, position)
        if not _wrapper(slot[0], index) or not _reference(references[index], index):
            raise PipelineError("Sum of Saving Knowledge electronic link inventory differs")
        removed.append({"wrapper": deepcopy(slot[0]),
                        "reference": deepcopy(references[index])})
        slot[0] = {"kind": "text", "text": HISTORICAL_HEADINGS[index]}
    contents["source_references"] = []
    if (any(row["text"] != readable_content(row["structure"][0]) for row in public)
            or [row["text"] for row in public] != [row["text"] for row in rows]
            or _digest(public) != PUBLIC_ROWS_SHA256
            or _scan(public, "Sum of Saving Knowledge historical public rows")):
        raise PipelineError("Sum of Saving Knowledge historical public rows differ")
    return public, {"contract": CONTRACT, "item_id": ITEM, "authority": authority,
                    "private_rows_sha256": PRIVATE_ROWS_SHA256,
                    "public_rows_sha256": PUBLIC_ROWS_SHA256, "removed": removed}


def restore_private_rows(rows: list[dict[str, Any]], artifact: dict[str, Any], *,
                         acceptance_sha256: str | None,
                         master_sha256: str | None) -> list[dict[str, Any]]:
    authority = _authority(acceptance_sha256, master_sha256)
    if (len(rows) != 6 or not isinstance(artifact, dict)
            or set(artifact) != {"contract", "item_id", "authority", "private_rows_sha256",
                                 "public_rows_sha256", "removed"}
            or artifact["contract"] != CONTRACT or artifact["item_id"] != ITEM
            or artifact["authority"] != authority
            or artifact["private_rows_sha256"] != PRIVATE_ROWS_SHA256
            or artifact["public_rows_sha256"] != PUBLIC_ROWS_SHA256
            or _digest(rows) != PUBLIC_ROWS_SHA256
            or not isinstance(artifact["removed"], list)
            or len(artifact["removed"]) != 4):
        raise PipelineError("Sum of Saving Knowledge omission receipt differs")
    restored = deepcopy(rows)
    contents = restored[0]
    if contents.get("source_references") != []:
        raise PipelineError("Sum of Saving Knowledge public references differ")
    references = []
    for index, position in enumerate(POSITIONS):
        entry = artifact["removed"][index]
        slot = _slot(contents, position)
        if (not isinstance(entry, dict) or set(entry) != {"wrapper", "reference"}
                or not _wrapper(entry["wrapper"], index)
                or not _reference(entry["reference"], index)
                or slot[0] != {"kind": "text", "text": HISTORICAL_HEADINGS[index]}):
            raise PipelineError("Sum of Saving Knowledge omission receipt differs")
        slot[0] = deepcopy(entry["wrapper"])
        references.append(deepcopy(entry["reference"]))
    contents["source_references"] = references
    if (_digest(restored) != PRIVATE_ROWS_SHA256
            or [row["text"] for row in restored] != [row["text"] for row in rows]):
        raise PipelineError("Sum of Saving Knowledge private inverse differs")
    replay_rows, replay_artifact = public_rows(
        restored, acceptance_sha256=acceptance_sha256, master_sha256=master_sha256)
    if replay_rows != rows or replay_artifact != artifact:
        raise PipelineError("Sum of Saving Knowledge public omission receipt is incomplete")
    return restored
