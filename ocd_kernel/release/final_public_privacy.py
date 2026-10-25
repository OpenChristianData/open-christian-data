"""Bounded, reversible public transform for accepted private carriers."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import re
from typing import Any

from ocd_kernel.library._common import PipelineError, canonical_bytes

CONTRACT = "ocd-final-public-private-carriers-v1"
BIBLES = {
    "isaac-leeser-tanakh--ebible-englee-leeser-1853":
        "source-native:englee-member-set:ebde4b25545bd97f9970916f685ac83fab37a9f6e2fbf35d2c9927948f251fb6",
    "tyndale-new-testament-1534--engtnt-ebible-electronic-1534":
        "source-native:engtnt-archive:12b1fb09831fdd259e45faba6fb29df95780a637596af83eb87ef19028d4e453",
}
BARNES = "barnes-nt-notes--crosswire-sword-v1.1"
PRAYERS = "private-devotions-several-occasions--private-devotions-several-occasions-tcp-electronic"
IGNATIUS = "pg77576-ignatius-ephesians--pg77576-ignatius-ephesians-pg77576-edition"
HARPER = "robertson-harmony-of-the-gospels--robertson-harmony-1922-harper-pg36264"
HARPER_ACCEPTANCE_SHA256 = "fd294ab79a6a1660b950a8d9d6c606aa3922f10516a4eddf4e334a5b25099f5e"
HARPER_MASTER_SHA256 = "cb77c03f4456e0e96a2b50f3d78e4a93913977450b228e237a8e94cabba44932"
HARPER_PRIVATE_ROWS_SHA256 = "abfe8aa9cbe9657c2ec5de6f46ade26e89f40c0c8e60cc20174fa899fb69304a"
HARPER_RECORD_ID = "robertson-harmony-1922-harper-pg36264:native:df13288550fb06f3eda9"
HARPER_ANNOTATION_PREFIX = "urn:ocd:pg36264:html:"
IGNATIUS_PRIVATE_TARGET = "raw/gutenberg/77576/html/pg77576-images.html#Page_141"
IGNATIUS_PUBLIC_TARGET = "#Page_141"
AJOPS = {f"ajops-v1-2024-a{number}--ajops-v1-2024-a{number}-publisher-jats"
         for number in (2, 4, 5, 11, 13, 14, 18, 21, 22, 23, 25, 28)}
OWEN = {
    "john-owen-mortification--john-owen-mortification-ccel-thml-electronic",
    "john-owen-sacramental-discourses--john-owen-sacramental-discourses-ccel-thml-electronic",
    "john-owen-schism--john-owen-schism-ccel-thml-electronic",
    "john-owen-sermons--john-owen-sermons-ccel-thml-electronic",
    "john-owen-two-catechisms--john-owen-two-catechisms-ccel-thml-electronic",
    "john-owen-vindiciae-evangelicae--john-owen-vindiciae-evangelicae-ccel-thml-electronic",
    "john-owen-worship--john-owen-worship-ccel-thml-witness",
}
ITEMS = frozenset(BIBLES) | {BARNES, PRAYERS, IGNATIUS, HARPER} | AJOPS | OWEN
EXPECTED_FIELDS = {
    "isaac-leeser-tanakh--ebible-englee-leeser-1853": 46286,
    "tyndale-new-testament-1534--engtnt-ebible-electronic-1534": 15908,
    BARNES: 166,
    PRAYERS: 7,
    IGNATIUS: 2,
    HARPER: 44176,
    "ajops-v1-2024-a2--ajops-v1-2024-a2-publisher-jats": 65,
    "ajops-v1-2024-a4--ajops-v1-2024-a4-publisher-jats": 818,
    "ajops-v1-2024-a5--ajops-v1-2024-a5-publisher-jats": 557,
    "ajops-v1-2024-a11--ajops-v1-2024-a11-publisher-jats": 1231,
    "ajops-v1-2024-a13--ajops-v1-2024-a13-publisher-jats": 646,
    "ajops-v1-2024-a14--ajops-v1-2024-a14-publisher-jats": 891,
    "ajops-v1-2024-a18--ajops-v1-2024-a18-publisher-jats": 1393,
    "ajops-v1-2024-a21--ajops-v1-2024-a21-publisher-jats": 774,
    "ajops-v1-2024-a22--ajops-v1-2024-a22-publisher-jats": 740,
    "ajops-v1-2024-a23--ajops-v1-2024-a23-publisher-jats": 904,
    "ajops-v1-2024-a25--ajops-v1-2024-a25-publisher-jats": 1104,
    "ajops-v1-2024-a28--ajops-v1-2024-a28-publisher-jats": 469,
    "john-owen-mortification--john-owen-mortification-ccel-thml-electronic": 1574,
    "john-owen-sacramental-discourses--john-owen-sacramental-discourses-ccel-thml-electronic": 2178,
    "john-owen-schism--john-owen-schism-ccel-thml-electronic": 3978,
    "john-owen-sermons--john-owen-sermons-ccel-thml-electronic": 22695,
    "john-owen-two-catechisms--john-owen-two-catechisms-ccel-thml-electronic": 2689,
    "john-owen-vindiciae-evangelicae--john-owen-vindiciae-evangelicae-ccel-thml-electronic": 23068,
    "john-owen-worship--john-owen-worship-ccel-thml-witness": 6893,
}
assert set(EXPECTED_FIELDS) == ITEMS
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def _digest(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _authority(acceptance_sha256: str | None, master_sha256: str | None) -> dict[str, str]:
    if (not isinstance(acceptance_sha256, str) or not _HEX64.fullmatch(acceptance_sha256)
            or not isinstance(master_sha256, str) or not _HEX64.fullmatch(master_sha256)):
        raise PipelineError("private carrier transform requires exact accepted authority hashes")
    return {"acceptance_sha256": acceptance_sha256, "master_sha256": master_sha256}


def public_rows(rows: list[dict], *, item_id: str, acceptance_sha256: str | None,
                master_sha256: str | None) -> tuple[list[dict], dict]:
    """Omit only the audited private carriers and bind each complete row preimage."""
    if item_id not in ITEMS or not rows:
        raise PipelineError("unapproved private carrier item or empty rows")
    authority = _authority(acceptance_sha256, master_sha256)
    if item_id == HARPER and (
        authority != {"acceptance_sha256": HARPER_ACCEPTANCE_SHA256,
                      "master_sha256": HARPER_MASTER_SHA256}
        or len(rows) != 1 or rows[0].get("record_id") != HARPER_RECORD_ID
        or _digest(rows) != HARPER_PRIVATE_ROWS_SHA256
    ):
        raise PipelineError("Harper public transform accepted authority or row identity differs")
    if any(isinstance(row.get("provenance"), dict)
           and "source_location" in row["provenance"] for row in rows):
        raise PipelineError(
            "reviewed carrier item has source_location; generic inverse composition required")
    public = deepcopy(rows)
    rewrites = []
    for index, row in enumerate(public):
        fields = []

        def change(holder: dict, key: str, path: list[str | int], after: str | None) -> None:
            before = holder[key]
            if not isinstance(before, str):
                raise PipelineError("private carrier must be a string")
            fields.append({"path": path + [key], "private": before, "public": after})
            if after is None:
                del holder[key]
            else:
                holder[key] = after

        if item_id in BIBLES:
            private = BIBLES[item_id]
            locator = row.get("locator")
            if (not isinstance(locator, dict) or locator.get("versification") != private
                    or row.get("versification") != private):
                raise PipelineError("source-native Bible versification preimage differs")
            public_label = private.rsplit(":", 1)[0]
            change(locator, "versification", ["locator"], public_label)
            change(row, "versification", [], public_label)

        def visit(value: Any, path: list[str | int]) -> None:
            if isinstance(value, list):
                for position, child in enumerate(value):
                    visit(child, path + [position])
            elif isinstance(value, dict):
                attributes = value.get("attributes")
                if ("kind" in value and isinstance(value.get("content"), list)
                        and isinstance(attributes, dict)):
                    if item_id == BARNES and isinstance(attributes.get("number"), str) and _HEX64.fullmatch(attributes["number"]):
                        change(attributes, "number", path + ["attributes"], None)
                    if item_id in AJOPS | OWEN | {PRAYERS} and isinstance(attributes.get("source_annotations"), str) and attributes["source_annotations"].lower().startswith("urn:ocd:"):
                        change(attributes, "source_annotations", path + ["attributes"], None)
                    if item_id == HARPER and isinstance(attributes.get("source_annotations"), str) and attributes["source_annotations"].startswith(HARPER_ANNOTATION_PREFIX):
                        change(attributes, "source_annotations", path + ["attributes"], None)
                    if item_id == IGNATIUS and attributes.get("source_target") == IGNATIUS_PRIVATE_TARGET:
                        change(attributes, "source_target", path + ["attributes"], IGNATIUS_PUBLIC_TARGET)
                if (item_id == IGNATIUS and len(path) >= 2
                        and path[-2] == "source_references"
                        and value.get("target") == IGNATIUS_PRIVATE_TARGET):
                    change(value, "target", path, IGNATIUS_PUBLIC_TARGET)
                for key, child in value.items():
                    if key != "attributes":
                        visit(child, path + [key])

        visit(row, [])
        if fields:
            fields.sort(key=lambda field: canonical_bytes(field["path"]))
            rewrites.append({"row_index": index, "record_id": row.get("record_id"),
                             "private_row_sha256": _digest(rows[index]),
                             "public_row_sha256": _digest(row), "fields": fields})
    if sum(len(entry["fields"]) for entry in rewrites) != EXPECTED_FIELDS[item_id]:
        raise PipelineError("selected private carrier omission count differs")
    return public, {"contract": CONTRACT, "item_id": item_id, "authority": authority,
                    "row_count": len(rows), "rewrites": rewrites}


def restore(rows: list[dict], artifact: dict, *, item_id: str,
            acceptance_sha256: str | None, master_sha256: str | None) -> list[dict]:
    """Restore exact private rows, then replay the deterministic public transform."""
    if (item_id not in ITEMS or not isinstance(artifact, dict)
            or set(artifact) != {"contract", "item_id", "authority", "row_count", "rewrites"}
            or artifact["contract"] != CONTRACT or artifact["item_id"] != item_id
            or artifact["authority"] != _authority(acceptance_sha256, master_sha256)
            or artifact["row_count"] != len(rows)
            or not isinstance(artifact["rewrites"], list) or not artifact["rewrites"]):
        raise PipelineError("private carrier receipt contract differs")
    private = deepcopy(rows)
    previous = -1
    for entry in artifact["rewrites"]:
        if (not isinstance(entry, dict)
                or set(entry) != {"row_index", "record_id", "private_row_sha256",
                                  "public_row_sha256", "fields"}
                or type(entry["row_index"]) is not int
                or not previous < entry["row_index"] < len(rows)
                or entry["record_id"] != rows[entry["row_index"]].get("record_id")
                or entry["public_row_sha256"] != _digest(rows[entry["row_index"]])
                or not isinstance(entry["fields"], list) or not entry["fields"]):
            raise PipelineError("private carrier row binding differs")
        previous = entry["row_index"]
        row = private[previous]
        paths = set()
        for field in entry["fields"]:
            if (not isinstance(field, dict) or set(field) != {"path", "private", "public"}
                    or not isinstance(field["path"], list) or not field["path"]
                    or any(type(part) not in {str, int} for part in field["path"])
                    or not isinstance(field["private"], str)):
                raise PipelineError("private carrier field shape differs")
            path = tuple(field["path"])
            if path in paths:
                raise PipelineError("duplicate private carrier field")
            paths.add(path)
            holder: Any = row
            try:
                for part in path[:-1]:
                    holder = holder[part]
            except (KeyError, IndexError, TypeError) as exc:
                raise PipelineError("private carrier field path differs") from exc
            key = path[-1]
            if not isinstance(holder, dict) or not isinstance(key, str):
                raise PipelineError("private carrier field target differs")
            public_value = field["public"]
            if ((public_value is None and key in holder)
                    or (public_value is not None and holder.get(key) != public_value)):
                raise PipelineError("private carrier public field differs")
            holder[key] = field["private"]
        if entry["private_row_sha256"] != _digest(row):
            raise PipelineError("private carrier private row differs")
    expected_rows, expected_artifact = public_rows(
        private, item_id=item_id, acceptance_sha256=acceptance_sha256,
        master_sha256=master_sha256)
    # Field paths are independent; old receipts used dictionary traversal order.
    ordered = {**artifact, "rewrites": [
        {**entry, "fields": sorted(entry["fields"],
                                  key=lambda field: canonical_bytes(field["path"]))}
        for entry in artifact["rewrites"]]}
    if expected_rows != rows or expected_artifact != ordered:
        raise PipelineError("private carrier omissions are incomplete")
    return private
