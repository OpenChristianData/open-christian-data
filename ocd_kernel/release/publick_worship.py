"""Exact public omission of website back-navigation from the 1645 Directory."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from typing import Any

from ocd_kernel.library._common import PipelineError, canonical_bytes
from ocd_kernel.projection.native_content import readable_content
from ocd_kernel.release.public_allowlist import _scan


CONTRACT = "ocd-public-directory-publick-worship-back-navigation-v1"
ITEM = "directory-for-publick-worship--directory-for-publick-worship-retained-electronic-witness"
ACCEPTANCE_SHA256 = "770fb0318d420d023bd19c557141e7085b37b8c11911219d7210dcd3aceeb521"
MASTER_SHA256 = "06588a3fa251e05322786e93f7f35d4fb0eea930756e0bde3d04271681f3ca94"
LICENSE = "Public domain (United States); identified historical text and apparatus only"
PRIVATE_ROWS_SHA256 = "67e33d31f05a6f11b3c7592b883788e522adbfd7492654ba60691964e4b9160f"
PUBLIC_ROWS_SHA256 = "bb3436697da7718d5019e0f91d9014e6f4c6f84a525ed8dcea391e8507f8a31e"
CONTENTS_TARGET = "#directory-for-publick-worship-source-000087"
NAV_INDICES = (13, 31, 53, 85, 149, 165, 207, 257, 273, 317, 355, 369, 395, 419, 431, 449)


def _digest(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _authority(acceptance_sha256: str | None, master_sha256: str | None) -> dict[str, str]:
    if (acceptance_sha256, master_sha256) != (ACCEPTANCE_SHA256, MASTER_SHA256):
        raise PipelineError("Publick Worship accepted authority differs")
    return {"acceptance_sha256": ACCEPTANCE_SHA256, "master_sha256": MASTER_SHA256}


def _parent(row: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        first = row["structure"][0]
        second = first["content"][1]
        children = second["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise PipelineError("Publick Worship accepted structure differs") from exc
    if (first.get("kind") != "division" or second.get("kind") != "division"
            or not isinstance(children, list)):
        raise PipelineError("Publick Worship accepted structure differs")
    return children


def _is_navigation(node: Any) -> bool:
    if not isinstance(node, dict) or set(node) != {"kind", "attributes", "content"}:
        return False
    if node["kind"] != "division" or node["attributes"] != {"type": "source-block-content"}:
        return False
    contents = node["content"]
    if not isinstance(contents, list) or len(contents) != 1:
        return False
    paragraph = contents[0]
    if (not isinstance(paragraph, dict) or paragraph.get("kind") != "paragraph"
            or paragraph.get("attributes") != {} or len(paragraph.get("content", [])) != 1):
        return False
    reference = paragraph["content"][0]
    return (isinstance(reference, dict) and reference.get("kind") == "source-reference"
            and reference.get("attributes") == {"type": "html-a", "source_target": CONTENTS_TARGET}
            and reference.get("content") == [{"kind": "text", "text": "Back to top."}])


def _is_reference(reference: Any) -> bool:
    return (isinstance(reference, dict)
            and reference.get("raw") == "Back to top."
            and reference.get("target") == CONTENTS_TARGET
            and reference.get("normalization_attribute") == "target"
            and reference.get("normalization_status") == "unsupported-explicit-target"
            and isinstance(reference.get("source_child_path"), list))


def public_rows(rows: list[dict[str, Any]], *, acceptance_sha256: str | None,
                master_sha256: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    authority = _authority(acceptance_sha256, master_sha256)
    if (len(rows) != 5 or any(row.get("license") != LICENSE for row in rows)
            or _digest(rows) != PRIVATE_ROWS_SHA256):
        raise PipelineError("Publick Worship selected private rows differ")
    if any("Back to top." in row.get("text", "") for row in rows[:4]):
        raise PipelineError("Publick Worship back-navigation scope differs")
    public = deepcopy(rows)
    final = public[4]
    parent = _parent(final)
    if (final.get("text", "").count("Back to top.") != 16
            or final["text"] != readable_content(final["structure"][0])
            or len(final.get("source_references", [])) != 16
            or not all(_is_reference(ref) for ref in final["source_references"])):
        raise PipelineError("Publick Worship private navigation inventory differs")
    if [i for i, node in enumerate(parent) if _is_navigation(node)] != list(NAV_INDICES):
        raise PipelineError("Publick Worship private navigation positions differ")
    removed_nodes = [deepcopy(parent[index]) for index in NAV_INDICES]
    removed_references = deepcopy(final["source_references"])
    for index in reversed(NAV_INDICES):
        del parent[index]
    final["source_references"] = []
    final["text"] = readable_content(final["structure"][0])
    if (_digest(public) != PUBLIC_ROWS_SHA256 or "Back to top." in final["text"]
            or _scan(public, "Publick Worship historical rows")):
        raise PipelineError("Publick Worship bounded public rows differ")
    return public, {
        "contract": CONTRACT, "item_id": ITEM, "authority": authority,
        "private_rows_sha256": PRIVATE_ROWS_SHA256,
        "public_rows_sha256": PUBLIC_ROWS_SHA256,
        "omitted_indices": list(NAV_INDICES),
        "omitted_nodes": removed_nodes,
        "omitted_references": removed_references,
    }


def restore_private_rows(rows: list[dict[str, Any]], artifact: dict[str, Any], *,
                         acceptance_sha256: str | None,
                         master_sha256: str | None) -> list[dict[str, Any]]:
    authority = _authority(acceptance_sha256, master_sha256)
    if (len(rows) != 5 or not isinstance(artifact, dict)
            or set(artifact) != {"contract", "item_id", "authority", "private_rows_sha256",
                                 "public_rows_sha256", "omitted_indices", "omitted_nodes",
                                 "omitted_references"}
            or artifact["contract"] != CONTRACT or artifact["item_id"] != ITEM
            or artifact["authority"] != authority
            or artifact["private_rows_sha256"] != PRIVATE_ROWS_SHA256
            or artifact["public_rows_sha256"] != PUBLIC_ROWS_SHA256
            or _digest(rows) != PUBLIC_ROWS_SHA256
            or artifact["omitted_indices"] != list(NAV_INDICES)
            or not isinstance(artifact["omitted_nodes"], list)
            or len(artifact["omitted_nodes"]) != 16
            or not all(_is_navigation(node) for node in artifact["omitted_nodes"])
            or not isinstance(artifact["omitted_references"], list)
            or len(artifact["omitted_references"]) != 16
            or not all(_is_reference(ref) for ref in artifact["omitted_references"])):
        raise PipelineError("Publick Worship private inverse receipt differs")
    restored = deepcopy(rows)
    final = restored[4]
    parent = _parent(final)
    if final.get("source_references") != [] or "Back to top." in final.get("text", ""):
        raise PipelineError("Publick Worship public navigation state differs")
    for index, node in zip(NAV_INDICES, artifact["omitted_nodes"], strict=True):
        parent.insert(index, deepcopy(node))
    final["source_references"] = deepcopy(artifact["omitted_references"])
    final["text"] = readable_content(final["structure"][0])
    if _digest(restored) != PRIVATE_ROWS_SHA256:
        raise PipelineError("Publick Worship private source inverse differs")
    replay_rows, replay_artifact = public_rows(restored, acceptance_sha256=acceptance_sha256,
                                               master_sha256=master_sha256)
    if replay_rows != rows or replay_artifact != artifact:
        raise PipelineError("Publick Worship public omission receipt is incomplete")
    return restored
