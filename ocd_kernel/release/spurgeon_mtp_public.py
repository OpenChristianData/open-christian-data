"""Exact reversible public exclusion of two MTP Modernized Edition witnesses."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256

from ocd_kernel.library._common import PipelineError, canonical_bytes


CONTRACT = "ocd-spurgeon-mtp-historical-sermon-selection-v1"
ITEM = "spurgeon-mtp--spurgeon-mtp-retained-electronic"
ACCEPTANCE_SHA256 = "ccd6e97e6503d03103f44c71eb5456cb5974eabba699e670057e170ce03decf8"
MASTER_SHA256 = "e1db04c2728cddacd9ce6fa675ebb329fe931e4c79659d754b6de6df7be2addc"
LICENSE = ("Public domain (United States) for selected historical Spurgeon sermon text only; "
           "Kingdom Collective and Spurgeon Archive electronic witnesses credited; "
           "Modernized Edition sermons 708 and 3032 excluded")
OMITTED = (
    {"index": 694, "number": "708",
     "record_id": "spurgeon-mtp-retained-electronic:native:179d3c2d7e283e2403f1",
     "source_only_sha256": "dc826f4725dfefe5678304b4fb3b154e810bd5c5f79b07fa547709e12b1b4751"},
    {"index": 3018, "number": "3032",
     "record_id": "spurgeon-mtp-retained-electronic:native:41a76a29d8c2aec99b8f",
     "source_only_sha256": "c18c50a69ada87b2f90336b20024ca25cfd4e859ab7489b76564ef6671ecda34"},
)


def _digest(value: object) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _row_stream_digest(rows: list[dict]) -> str:
    digest = sha256()
    for row in rows:
        digest.update(canonical_bytes(row))
    return digest.hexdigest()


def _authority(acceptance_sha256: str | None, master_sha256: str | None) -> dict[str, str]:
    if (acceptance_sha256, master_sha256) != (ACCEPTANCE_SHA256, MASTER_SHA256):
        raise PipelineError("MTP public selection requires its exact accepted authority")
    return {"acceptance_sha256": ACCEPTANCE_SHA256, "master_sha256": MASTER_SHA256}


def _number(row: dict) -> tuple[str | None, str | None]:
    structure = row.get("structure")
    if (not isinstance(structure, list) or len(structure) != 1
            or not isinstance(structure[0], dict)
            or structure[0].get("kind") != "division"):
        raise PipelineError("MTP source sermon unit structure differs")
    attributes = structure[0].get("attributes")
    if not isinstance(attributes, dict) or attributes.get("type") != "sermon":
        raise PipelineError("MTP source sermon division differs")
    return attributes.get("number"), attributes.get("subtype")


def _validate_private(rows: list[dict]) -> None:
    if len(rows) != 3550:
        raise PipelineError("MTP retained source row count differs")
    numbers = set()
    subtypes = {"primary-article": 0, "supplemental-aig-sermon-content": 0,
                "supplemental-spurgeon-archive-sermon-content": 0}
    for index, row in enumerate(rows):
        number, subtype = _number(row)
        if (not isinstance(number, str) or not number.isdecimal()
                or number in numbers or subtype not in subtypes
                or row.get("work_id") != "spurgeon-mtp"
                or row.get("edition_id") != "spurgeon-mtp-retained-electronic"
                or row.get("sequence") != index + 1 or row.get("license") != LICENSE):
            raise PipelineError(f"MTP retained row identity differs at {index}")
        numbers.add(number)
        subtypes[subtype] += 1
    if subtypes != {"primary-article": 3547, "supplemental-aig-sermon-content": 2,
                    "supplemental-spurgeon-archive-sermon-content": 1}:
        raise PipelineError("MTP retained source subtype inventory differs")
    for expected in OMITTED:
        row = rows[expected["index"]]
        number, subtype = _number(row)
        source_only = {key: value for key, value in row.items() if key != "license"}
        if (number != expected["number"] or subtype != "supplemental-aig-sermon-content"
                or row.get("record_id") != expected["record_id"]
                or _digest(source_only) != expected["source_only_sha256"]):
            raise PipelineError(f"MTP Modernized Edition row {expected['number']} differs")


def public_rows(rows: list[dict], *, acceptance_sha256: str | None,
                master_sha256: str | None) -> tuple[list[dict], dict]:
    authority = _authority(acceptance_sha256, master_sha256)
    _validate_private(rows)
    omitted = [{"index": expected["index"], "number": expected["number"],
                "source_only_sha256": expected["source_only_sha256"],
                "row": deepcopy(rows[expected["index"]])} for expected in OMITTED]
    hidden = {entry["index"] for entry in OMITTED}
    public = [deepcopy(row) for index, row in enumerate(rows) if index not in hidden]
    if len(public) != 3548:
        raise PipelineError("MTP public historical scope differs")
    return public, {"contract": CONTRACT, "item_id": ITEM, "authority": authority,
                    "private_row_count": 3550, "public_row_count": 3548,
                    "public_rows_sha256": _row_stream_digest(public),
                    "omitted_rows": omitted}


def restore_private_rows(rows: list[dict], artifact: dict, *,
                         acceptance_sha256: str | None,
                         master_sha256: str | None) -> list[dict]:
    authority = _authority(acceptance_sha256, master_sha256)
    if (len(rows) != 3548 or not isinstance(artifact, dict)
            or set(artifact) != {"contract", "item_id", "authority",
                                 "private_row_count", "public_row_count", "public_rows_sha256",
                                 "omitted_rows"}
            or artifact["contract"] != CONTRACT or artifact["item_id"] != ITEM
            or artifact["authority"] != authority
            or artifact["private_row_count"] != 3550
            or artifact["public_row_count"] != 3548
            or artifact["public_rows_sha256"] != _row_stream_digest(rows)
            or not isinstance(artifact["omitted_rows"], list)
            or len(artifact["omitted_rows"]) != 2):
        raise PipelineError("MTP public historical omission receipt differs")
    restored = deepcopy(rows)
    for expected, entry in zip(OMITTED, artifact["omitted_rows"], strict=True):
        if (not isinstance(entry, dict)
                or set(entry) != {"index", "number", "source_only_sha256", "row"}
                or any(entry[key] != expected[key]
                       for key in ("index", "number", "source_only_sha256"))
                or not isinstance(entry["row"], dict)):
            raise PipelineError("MTP omitted source row binding differs")
        restored.insert(expected["index"], deepcopy(entry["row"]))
    expected_public, expected_artifact = public_rows(
        restored, acceptance_sha256=acceptance_sha256, master_sha256=master_sha256)
    if expected_public != rows or expected_artifact != artifact:
        raise PipelineError("MTP public historical omissions are incomplete")
    return restored
