"""Preserve Watson's ten textual units while removing CCEL source style tokens.

The source-generated Scripture index remains visible as mechanical book and
reference data. Its source class names become plain semantic node types; all
words, links, targets, and original source classes remain in the private
inverse. This does not modify the accepted TEI or assert a print index.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from hashlib import sha256
from typing import Any

from ocd_kernel.library._common import PipelineError, canonical_bytes


ITEM = "watson-body-of-divinity--watson-body-of-divinity-retained-thml-route"
ACCEPTANCE_SHA256 = "a0ac4a85f4788bbd822b5c1a9c651f79ac2e76a055a6757caa2db2750f23626c"
MASTER_SHA256 = "4c436a9c889137d7e8b6e87aa2140e6a71e32c2d57f567d1a3352d6b15970a7d"
SCOPE_SHA256 = "1c761f8c993507cbfdb22f09c2a72d6e5f40e8c1b626a1c1194fe557b0881444"
PRIVATE_ROWS_SHA256 = "eb26edc5a21dce47fda2dbcccd30b8dbf41a2f10146cf8933bacc28e83b064c5"
PUBLIC_ROWS_SHA256 = "176a5de8303493c9aee38f20f2a8c9aa0c2b000cf096ae940508971b2095eab7"
LICENSE = ("Public domain (United States): retained historical Thomas Watson text and "
           "C. H. Spurgeon memoir; source-generated factual Scripture index; "
           "CCEL file and formatting restrictions apply")
CONTRACT = "ocd-public-watson-body-source-style-inverse-v1"
STYLES = {
    ("paragraph", "Body"): None,
    ("division", "Index"): "source-scripture-index",
    ("paragraph", "bbook"): "scripture-index-book-heading",
    ("paragraph", "bref"): "scripture-index-reference-list",
    ("source-reference", "TOC"): "scripture-index-link",
}
COUNTS = {
    ("paragraph", "Body"): 1536,
    ("division", "Index"): 1,
    ("paragraph", "bbook"): 61,
    ("paragraph", "bref"): 61,
    ("source-reference", "TOC"): 2070,
}


def _digest(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _authority(acceptance_sha256: str | None, master_sha256: str | None) -> dict[str, str]:
    if (acceptance_sha256, master_sha256) != (ACCEPTANCE_SHA256, MASTER_SHA256):
        raise PipelineError("Watson Body accepted authority differs")
    return {"acceptance_sha256": ACCEPTANCE_SHA256,
            "master_sha256": MASTER_SHA256, "scope_sha256": SCOPE_SHA256}


def _transform(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    public = deepcopy(rows)
    inventory: Counter[tuple[str, str]] = Counter()
    entries = []
    for index, row in enumerate(public):
        fields = []
        pending: list[tuple[Any, list[str | int]]] = [(row, [])]
        while pending:
            node, path = pending.pop()
            if isinstance(node, list):
                pending.extend((child, path + [position]) for position, child in enumerate(node))
            elif isinstance(node, dict):
                attributes = node.get("attributes")
                if isinstance(attributes, dict) and "style" in attributes:
                    kind, style = node.get("kind"), attributes["style"]
                    if (not isinstance(kind, str) or not isinstance(style, str)
                            or (kind, style) not in STYLES or "type" in attributes):
                        raise PipelineError("Watson Body source-style carrier differs")
                    inventory[kind, style] += 1
                    public_type = STYLES[kind, style]
                    del attributes["style"]
                    if public_type is not None:
                        attributes["type"] = public_type
                    fields.append({"path": path + ["attributes"], "kind": kind,
                                   "private_style": style, "public_type": public_type})
                pending.extend((child, path + [key]) for key, child in node.items()
                               if key != "attributes")
        entries.append({"row_index": index, "record_id": rows[index].get("record_id"),
                        "private_row_sha256": _digest(rows[index]),
                        "public_row_sha256": _digest(row), "fields": fields})
    if inventory != COUNTS:
        raise PipelineError(f"Watson Body source style inventory differs: {dict(inventory)}")
    return public, entries


def public_rows(rows: list[dict[str, Any]], *, acceptance_sha256: str | None,
                master_sha256: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    authority = _authority(acceptance_sha256, master_sha256)
    if (len(rows) != 10 or _digest(rows) != PRIVATE_ROWS_SHA256
            or any(row.get("license") != LICENSE for row in rows)):
        raise PipelineError("Watson Body ten-unit accepted private scope differs")
    public, entries = _transform(rows)
    if _digest(public) != PUBLIC_ROWS_SHA256:
        raise PipelineError("Watson Body public text/index scope differs")
    return public, {"contract": CONTRACT, "item_id": ITEM, "authority": authority,
                    "row_count": 10, "entries": entries}


def restore_private_rows(rows: list[dict[str, Any]], artifact: dict[str, Any], *,
                         acceptance_sha256: str | None,
                         master_sha256: str | None) -> list[dict[str, Any]]:
    authority = _authority(acceptance_sha256, master_sha256)
    if (not isinstance(artifact, dict)
            or set(artifact) != {"contract", "item_id", "authority", "row_count", "entries"}
            or artifact["contract"] != CONTRACT or artifact["item_id"] != ITEM
            or artifact["authority"] != authority
            or type(artifact["row_count"]) is not int or artifact["row_count"] != 10
            or len(rows) != 10 or _digest(rows) != PUBLIC_ROWS_SHA256
            or not isinstance(artifact["entries"], list) or len(artifact["entries"]) != 10):
        raise PipelineError("Watson Body private source-style receipt differs")
    restored = deepcopy(rows)
    inventory: Counter[tuple[str, str]] = Counter()
    for index, (row, entry) in enumerate(zip(restored, artifact["entries"], strict=True)):
        if (not isinstance(entry, dict)
                or set(entry) != {"row_index", "record_id", "private_row_sha256",
                                      "public_row_sha256", "fields"}
                or type(entry["row_index"]) is not int or entry["row_index"] != index
                or entry["record_id"] != row.get("record_id")
                or entry["public_row_sha256"] != _digest(rows[index])
                or not isinstance(entry["fields"], list)):
            raise PipelineError("Watson Body private row receipt differs")
        used = set()
        for field in entry["fields"]:
            if (not isinstance(field, dict)
                    or set(field) != {"path", "kind", "private_style", "public_type"}
                    or not isinstance(field["path"], list)
                    or len(field["path"]) < 2 or field["path"][-1] != "attributes"
                    or any(type(part) not in {str, int} for part in field["path"])
                    or not isinstance(field["kind"], str)
                    or not isinstance(field["private_style"], str)
                    or (field["kind"], field["private_style"]) not in STYLES
                    or field["public_type"] != STYLES[field["kind"], field["private_style"]]):
                raise PipelineError("Watson Body source-style receipt field differs")
            key = tuple(field["path"])
            if key in used:
                raise PipelineError("Watson Body duplicate source-style receipt field")
            used.add(key)
            node: Any = row
            try:
                for part in field["path"][:-1]:
                    node = node[part]
            except (IndexError, KeyError, TypeError) as exc:
                raise PipelineError("Watson Body source-style receipt path differs") from exc
            attributes = node.get("attributes") if isinstance(node, dict) else None
            if (not isinstance(attributes, dict) or node.get("kind") != field["kind"]
                    or "style" in attributes or attributes.get("type") != field["public_type"]
                    or (field["public_type"] is None and "type" in attributes)):
                raise PipelineError("Watson Body public semantic index carrier differs")
            if field["public_type"] is not None:
                del attributes["type"]
            attributes["style"] = field["private_style"]
            inventory[field["kind"], field["private_style"]] += 1
        if _digest(row) != entry["private_row_sha256"]:
            raise PipelineError("Watson Body restored private row differs")
    if inventory != COUNTS or _digest(restored) != PRIVATE_ROWS_SHA256:
        raise PipelineError("Watson Body restored style/text inventory differs")
    expected_public, expected_entries = _transform(restored)
    if expected_public != rows or expected_entries != artifact["entries"]:
        raise PipelineError("Watson Body source-style receipt omits or misplaces fields")
    return restored
