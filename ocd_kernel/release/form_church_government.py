"""Bound public omission of modern HTML navigation around the historical Form."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from typing import Any

from ocd_kernel.library._common import PipelineError, canonical_bytes
from ocd_kernel.projection.native_content import readable_content
from ocd_kernel.release.public_allowlist import _scan


CONTRACT = "ocd-public-form-church-government-historical-text-v1"
ITEM = "form-of-church-government--form-of-church-government-retained-electronic-witness"
LICENSE = "Public domain (United States) for identified 1645/1647 Westminster Assembly text; The Westminster Standard electronic witness credited"
ACCEPTANCE_SHA256 = "541f5d173b06052b99b8f9d1d3aa5a62b2e5a0b19d3fec1d254de310d3fecca1"
MASTER_SHA256 = "7c0c2263ea1d5c1efce120c95ec65e2733854400d70f7adfc8574791e87c49fe"
PRIVATE_ROWS_SHA256 = "436f1eb6cbb6dcc8557f5476e130919e251909969ebc37782803439d78c35f62"
PUBLIC_ROWS_SHA256 = "9abedebd3669fb8a925a12361c5a7b4c090f14ad2d7c7d943280193ec0d2d86b"
CONTENTS_SHA256 = "0ffe5fef5e55d9dbff348050d0cb2641826a3280c4c8b2411b63dc6b3dc4735e"
PREFATORY_HEADING_SHA256 = "7e6917f6dd3bca7f17885634d219ed0b61c3f649ff93c8b99c937947c4fb142e"
HTML_COMMENT_SHA256 = "223e15da62bdb1638a4441c70682f4d5868645da1d59b1557fab245bd8a2a2b7"
BACK_LINK_SHA256 = "b3de89d3900d6181d5326bbbd641c007c9201714a6ca5a76bd723a33ad2fb815"
FINAL_BACK_LINK_SHA256 = "a48b5a52fff02344a421014a2138b6c3cb7794ab844f3bd2b279fc9590354f85"
BACK_LINK_TARGET = "#form-of-church-government-source-000007"
NAV_INDICES = (5, 15, 23, 65, 71, 79, 95, 111, 117, 127, 137, 167, 215,
               227, 233, 253, 269, 297, 363)


def _digest(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _authority(acceptance_sha256: str | None, master_sha256: str | None) -> dict[str, str]:
    if (acceptance_sha256, master_sha256) != (ACCEPTANCE_SHA256, MASTER_SHA256):
        raise PipelineError("Form accepted historical-text authority differs")
    return {"acceptance_sha256": ACCEPTANCE_SHA256, "master_sha256": MASTER_SHA256}


def _comment_parent(row: dict[str, Any], *, prefatory: bool) -> list[dict[str, Any]]:
    try:
        root = row["structure"][0]
        if prefatory:
            parent = root["content"][1]["content"][1]["content"][1]["content"]
        else:
            parent = root["content"][1]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise PipelineError("Form accepted HTML structure differs") from exc
    if not isinstance(parent, list):
        raise PipelineError("Form accepted HTML structure differs")
    return parent


def _navigation(node: Any, *, final: bool = False) -> bool:
    expected_hash = FINAL_BACK_LINK_SHA256 if final else BACK_LINK_SHA256
    if not isinstance(node, dict) or _digest(node) != expected_hash:
        return False
    try:
        paragraph = node["content"][0]
        reference = paragraph["content"][0]
        return (node["kind"] == "division"
                and node["attributes"] == {"type": "source-block-content"}
                and paragraph["kind"] == "paragraph"
                and reference["kind"] == "source-reference"
                and reference["attributes"] == {"type": "html-a", "source_target": BACK_LINK_TARGET}
                and reference["content"] == [{"kind": "text", "text": "Back to top" if final else "Back to top."}]
                and (paragraph["content"][1:] == [{"kind": "text", "text": "."}]
                     if final else len(paragraph["content"]) == 1))
    except (KeyError, IndexError, TypeError):
        return False


def public_rows(rows: list[dict[str, Any]], *, acceptance_sha256: str | None,
                master_sha256: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Keep the complete historical act and Form including its internal Directory."""
    authority = _authority(acceptance_sha256, master_sha256)
    if (len(rows) != 3 or any(row.get("license") != LICENSE for row in rows)
            or _digest(rows) != PRIVATE_ROWS_SHA256
            or _digest(rows[0]) != CONTENTS_SHA256):
        raise PipelineError("Form selected private rows differ")
    public = deepcopy(rows[1:])
    prefatory, body = public
    prefatory_root = prefatory["structure"][0]
    prefatory_parent = _comment_parent(prefatory, prefatory=True)
    body_parent = _comment_parent(body, prefatory=False)
    if (len(prefatory_parent) != 7 or len(body_parent) != 367
            or _digest(prefatory_parent[5]) != HTML_COMMENT_SHA256
            or _digest(body_parent[365]) != HTML_COMMENT_SHA256
            or _digest(prefatory_root["content"][0]) != PREFATORY_HEADING_SHA256
            or len(prefatory.get("source_references", [])) != 1
            or len(body.get("source_references", [])) != 19
            or [index for index, node in enumerate(body_parent)
                if _navigation(node) or _navigation(node, final=True)] != list(NAV_INDICES)
            or any(not _navigation(body_parent[index], final=index == NAV_INDICES[-1])
                   for index in NAV_INDICES)):
        raise PipelineError("Form website-shell inventory differs")
    removed = {
        "contents_row": deepcopy(rows[0]),
        "prefatory_heading": deepcopy(prefatory_root["content"][0]),
        "prefatory_comment": deepcopy(prefatory_parent[5]),
        "body_comment": deepcopy(body_parent[365]),
        "navigation": [deepcopy(body_parent[index]) for index in NAV_INDICES],
        "prefatory_references": deepcopy(prefatory["source_references"]),
        "body_references": deepcopy(body["source_references"]),
    }
    del prefatory_parent[5]
    del prefatory_root["content"][0]
    del body_parent[365]
    for index in reversed(NAV_INDICES):
        del body_parent[index]
    prefatory["source_references"] = []
    body["source_references"] = []
    for row in public:
        row["text"] = readable_content(row["structure"][0])
    if (_digest(public) != PUBLIC_ROWS_SHA256
            or any("Back to top" in row["text"] for row in public)
            or _scan(public, "Form historical public rows")):
        raise PipelineError("Form historical public rows differ")
    return public, {"contract": CONTRACT, "item_id": ITEM, "authority": authority,
                    "private_rows_sha256": PRIVATE_ROWS_SHA256,
                    "public_rows_sha256": PUBLIC_ROWS_SHA256,
                    "omitted_indices": list(NAV_INDICES), **removed}


def restore_private_rows(rows: list[dict[str, Any]], artifact: dict[str, Any], *,
                         acceptance_sha256: str | None,
                         master_sha256: str | None) -> list[dict[str, Any]]:
    authority = _authority(acceptance_sha256, master_sha256)
    fields = {"contract", "item_id", "authority", "private_rows_sha256", "public_rows_sha256",
              "omitted_indices", "contents_row", "prefatory_heading", "prefatory_comment",
              "body_comment", "navigation", "prefatory_references", "body_references"}
    if (len(rows) != 2 or not isinstance(artifact, dict) or set(artifact) != fields
            or artifact["contract"] != CONTRACT or artifact["item_id"] != ITEM
            or artifact["authority"] != authority
            or artifact["private_rows_sha256"] != PRIVATE_ROWS_SHA256
            or artifact["public_rows_sha256"] != PUBLIC_ROWS_SHA256
            or artifact["omitted_indices"] != list(NAV_INDICES)
            or _digest(rows) != PUBLIC_ROWS_SHA256
            or _digest(artifact["contents_row"]) != CONTENTS_SHA256
            or _digest(artifact["prefatory_heading"]) != PREFATORY_HEADING_SHA256
            or _digest(artifact["prefatory_comment"]) != HTML_COMMENT_SHA256
            or _digest(artifact["body_comment"]) != HTML_COMMENT_SHA256
            or not isinstance(artifact["navigation"], list)
            or len(artifact["navigation"]) != len(NAV_INDICES)
            or any(not _navigation(node, final=index == NAV_INDICES[-1])
                   for index, node in zip(NAV_INDICES, artifact["navigation"], strict=True))
            or not isinstance(artifact["prefatory_references"], list)
            or len(artifact["prefatory_references"]) != 1
            or not isinstance(artifact["body_references"], list)
            or len(artifact["body_references"]) != 19):
        raise PipelineError("Form website-shell omission receipt differs")
    restored = deepcopy(rows)
    prefatory, body = restored
    if prefatory.get("source_references") != [] or body.get("source_references") != []:
        raise PipelineError("Form public reference state differs")
    prefatory_root = prefatory["structure"][0]
    prefatory_parent = prefatory_root["content"][0]["content"][1]["content"][1]["content"]
    body_parent = _comment_parent(body, prefatory=False)
    if len(prefatory_parent) != 6 or len(body_parent) != 347:
        raise PipelineError("Form public HTML-unit inventory differs")
    prefatory_parent.insert(5, deepcopy(artifact["prefatory_comment"]))
    prefatory_root["content"].insert(0, deepcopy(artifact["prefatory_heading"]))
    for index, node in zip(NAV_INDICES, artifact["navigation"], strict=True):
        body_parent.insert(index, deepcopy(node))
    body_parent.insert(365, deepcopy(artifact["body_comment"]))
    prefatory["source_references"] = deepcopy(artifact["prefatory_references"])
    body["source_references"] = deepcopy(artifact["body_references"])
    for row in restored:
        row["text"] = readable_content(row["structure"][0])
    restored.insert(0, deepcopy(artifact["contents_row"]))
    if _digest(restored) != PRIVATE_ROWS_SHA256:
        raise PipelineError("Form restored private rows differ")
    expected_rows, expected_artifact = public_rows(
        restored, acceptance_sha256=acceptance_sha256, master_sha256=master_sha256)
    if expected_rows != rows or expected_artifact != artifact:
        raise PipelineError("Form public website-shell omission is incomplete")
    return restored
