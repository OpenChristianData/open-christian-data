"""Exact reversible public scope for the partial 1662 prayer-book witness."""

from copy import deepcopy
from hashlib import sha256
from typing import Any

from ocd_kernel.library._common import PipelineError, canonical_bytes
from ocd_kernel.projection.native_content import readable_content
from ocd_kernel.release.public_allowlist import _scan


CONTRACT = "ocd-public-bcp1662-historical-text-v1"
ITEM = "bcp-1662--bcp-1662-retained-electronic-witness"
LICENSE = ("Public domain (United States) for identified historical prayer-book text in the partial 1662 electronic witness; "
           "the three expressly identified 1992 additions are excluded")
ACCEPTANCE_SHA256 = "ec22d88f1bd0ee089fe0ddf3481256497768699ecb0083bf7ffede4e40544954"
MASTER_SHA256 = "8541af936cdf4c5add5524b693f00e216045457ae11159abd29123d22016e017"
SCOPE_SHA256 = "1f19e3709834a14854298f9bfb31c7aa17eaebd4a66814de2bac5bbe592a9926"
PRIVATE_ROWS_SHA256 = "ef505cbe90d7ef4f6e7f46bea1e68759312e34fe71e51f324ae9c7b216c34f78"
PUBLIC_ROWS_SHA256 = "8086f0a49c45e4ffb2b8a6532dbbe319e113d05049b201f1c6a75273a21c1357"
MODERN_BLOCKS = (
    (0, 15, "7ff1b9f03ecdeac400969b0c7d3347a3ad0523ecbe422b27dbf12dff4fdfd846"),
    (1, 11, "5a2fa45ed4bd5e7161dfbc72ae62f6e5273d221ffd4973d041f63b846b628fc0"),
    (5, 7, "aa5c03bd8428d14e893dfd24c4792040af22b548193ace6a66635c2cc52a8166"),
)
EXPECTED_TITLES = ("Morning Prayer", "Evening Prayer", "Holy Communion")


def _digest(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _authority(acceptance_sha256: str | None,
               master_sha256: str | None) -> dict[str, str]:
    if (acceptance_sha256, master_sha256) != (ACCEPTANCE_SHA256, MASTER_SHA256):
        raise PipelineError("BCP1662 accepted historical authority differs")
    return {"acceptance_sha256": ACCEPTANCE_SHA256,
            "master_sha256": MASTER_SHA256, "scope_sha256": SCOPE_SHA256}


def _content(row: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        root = row["structure"][0]
        content = root["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise PipelineError("BCP1662 native member structure differs") from exc
    if (root.get("kind") != "division" or not isinstance(content, list)
            or not isinstance(root.get("attributes"), dict)):
        raise PipelineError("BCP1662 native member structure differs")
    return content


def _center_paths(value: Any, path: tuple[Any, ...] = ()) -> list[list[Any]]:
    result: list[list[Any]] = []
    if isinstance(value, list):
        for index, child in enumerate(value):
            result.extend(_center_paths(child, path + (index,)))
    elif isinstance(value, dict):
        attributes = value.get("attributes")
        if isinstance(attributes, dict) and "style" in attributes:
            if value.get("kind") != "source-block" or attributes["style"] != "center":
                raise PipelineError("BCP1662 source presentation inventory differs")
            result.append(list(path + ("attributes", "style")))
        for key, child in value.items():
            if key != "attributes":
                result.extend(_center_paths(child, path + (key,)))
    return result


def _at(value: Any, path: list[Any]) -> Any:
    try:
        for part in path:
            value = value[part]
    except (KeyError, IndexError, TypeError) as exc:
        raise PipelineError("BCP1662 style receipt path differs") from exc
    return value


def public_rows(rows: list[dict[str, Any]], *, acceptance_sha256: str | None,
                master_sha256: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Omit three explicitly modern passages and source centering only."""
    authority = _authority(acceptance_sha256, master_sha256)
    if (len(rows) != 25 or _digest(rows) != PRIVATE_ROWS_SHA256
            or any(row.get("license") != LICENSE for row in rows)):
        raise PipelineError("BCP1662 accepted private row scope differs")
    public = deepcopy(rows)
    removed = []
    for (index, position, expected_sha), title in zip(MODERN_BLOCKS, EXPECTED_TITLES, strict=True):
        row = public[index]
        content = _content(row)
        if (row.get("member_title") != title or len(content) <= position
                or _digest(content[position]) != expected_sha):
            raise PipelineError("BCP1662 expressly later passage differs")
        removed.append({"row_index": index, "position": position,
                        "node": deepcopy(content.pop(position))})
        row["text"] = readable_content(row["structure"][0])
    styles = []
    for row_index, row in enumerate(public):
        for path in _center_paths(row["structure"], ("structure",)):
            attributes = _at(row, path[:-1])
            assert attributes[path[-1]] == "center"
            styles.append({"row_index": row_index, "path": path})
            del attributes[path[-1]]
    if (len(styles) != 473
            or any(row["text"] != readable_content(row["structure"][0]) for row in public)
            or [public[i]["text"] for i in range(25) if i not in {0, 1, 5}]
            != [rows[i]["text"] for i in range(25) if i not in {0, 1, 5}]
            or _scan(public, "BCP1662 historical public rows")):
        raise PipelineError("BCP1662 historical public rows differ")
    public_sha = _digest(public)
    if public_sha != PUBLIC_ROWS_SHA256:
        raise PipelineError("BCP1662 public row hash differs")
    return public, {"contract": CONTRACT, "item_id": ITEM, "authority": authority,
                    "private_rows_sha256": PRIVATE_ROWS_SHA256,
                    "public_rows_sha256": public_sha, "removed": removed, "styles": styles}


def restore_private_rows(rows: list[dict[str, Any]], artifact: dict[str, Any], *,
                         acceptance_sha256: str | None,
                         master_sha256: str | None) -> list[dict[str, Any]]:
    authority = _authority(acceptance_sha256, master_sha256)
    if (len(rows) != 25 or not isinstance(artifact, dict)
            or set(artifact) != {"contract", "item_id", "authority", "private_rows_sha256",
                                 "public_rows_sha256", "removed", "styles"}
            or artifact["contract"] != CONTRACT or artifact["item_id"] != ITEM
            or artifact["authority"] != authority
            or artifact["private_rows_sha256"] != PRIVATE_ROWS_SHA256
            or artifact["public_rows_sha256"] != _digest(rows)
            or artifact["public_rows_sha256"] != PUBLIC_ROWS_SHA256
            or not isinstance(artifact["removed"], list)
            or not isinstance(artifact["styles"], list)
            or len(artifact["removed"]) != 3 or len(artifact["styles"]) != 473):
        raise PipelineError("BCP1662 private omission receipt differs")
    restored = deepcopy(rows)
    for entry in artifact["styles"]:
        if (not isinstance(entry, dict) or set(entry) != {"row_index", "path"}
                or type(entry["row_index"]) is not int
                or not isinstance(entry["path"], list)
                or entry["path"][-2:] != ["attributes", "style"]):
            raise PipelineError("BCP1662 style omission receipt differs")
        attributes = _at(restored[entry["row_index"]], entry["path"][:-1])
        if not isinstance(attributes, dict) or "style" in attributes:
            raise PipelineError("BCP1662 public style receipt target differs")
        attributes["style"] = "center"
    for entry, (index, position, expected_sha) in zip(
            artifact["removed"], MODERN_BLOCKS, strict=True):
        if (not isinstance(entry, dict) or set(entry) != {"row_index", "position", "node"}
                or entry["row_index"] != index or entry["position"] != position
                or _digest(entry["node"]) != expected_sha):
            raise PipelineError("BCP1662 later passage receipt differs")
        content = _content(restored[index])
        if len(content) <= position:
            raise PipelineError("BCP1662 public member position differs")
        content.insert(position, deepcopy(entry["node"]))
        restored[index]["text"] = readable_content(restored[index]["structure"][0])
    if _digest(restored) != PRIVATE_ROWS_SHA256:
        raise PipelineError("BCP1662 private accepted inverse differs")
    expected_rows, expected_artifact = public_rows(
        restored, acceptance_sha256=acceptance_sha256, master_sha256=master_sha256)
    if expected_rows != rows or expected_artifact != artifact:
        raise PipelineError("BCP1662 public omission receipt is incomplete")
    return restored
