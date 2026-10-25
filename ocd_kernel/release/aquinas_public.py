"""Source-bound omission of four modern electronic-edition notes.

The accepted TEI retains each note. Public rows retain the historical
translation, source dedication, contents, prologues, questions, articles, and
the separate Part III editorial diagram. This module changes no source master.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from typing import Any

from ocd_kernel.library._common import PipelineError, canonical_bytes


ITEM = "aquinas-summa-theologica-four-parts--aquinas-summa-theologica-four-parts-gutenberg-electronic"
ACCEPTANCE_SHA256 = "97ce00f5fd1cf68871b85b7f82ba7e51a294ec31624c09535c52aacd35710a9f"
MASTER_SHA256 = "8afc726956294b98055dd5dbd154df84e61a75597d9ffe77629ef891b226104b"
SCOPE_SHA256 = "f8fa5851dd6ef1ca7b2659964f7d927e58da6e002027e57692411348040ab816"
PRIVATE_ROWS_SHA256 = "269d84b56301ada04b37135f2b2561ee5c05860732a479b8328aaadb73b2a031"
PUBLIC_ROWS_SHA256 = "bf18f1939557cb321e859ccba43d6e1e69475671304c63be1b6a1c0de5ead6a0"
LICENSE = ("Public domain (United States): retained four-part historical English Dominican Aquinas text; "
           "Project Gutenberg source terms and credits retained; modern authored electronic-edition notes omitted")
CONTRACT = "ocd-public-aquinas-four-modern-electronic-note-v1"
HEADING = "NOTE TO THIS ELECTRONIC EDITION"
MEMBERS = ("17611", "17897", "18755", "19950")
NOTE_STARTS = (19, 17, 17, 17)
NOTE_ENDS = (49, 47, 47, 47)


def _digest(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _node_text(value: Any) -> str:
    if isinstance(value, dict):
        text = value.get("text", "")
        content = value.get("content", [])
        if not isinstance(text, str) or not isinstance(content, list):
            raise PipelineError("Aquinas electronic note node differs")
        return text + "".join(_node_text(child) for child in content)
    return ""


def _front(row: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        component = row["structure"][0]
        front = component["content"][1]
        if (component["kind"] != "division"
                or component["attributes"]["type"] != "component"
                or front["kind"] != "division"
                or front["attributes"] != {"type": "front-matter"}
                or not isinstance(front["content"], list)):
            raise PipelineError("Aquinas front-matter structure differs")
        return front["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise PipelineError("Aquinas front-matter structure differs") from exc


def _transform(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    public = deepcopy(rows)
    omissions = []
    for index, (private, row) in enumerate(zip(rows, public, strict=True)):
        front = _front(row)
        start, end = NOTE_STARTS[index], NOTE_ENDS[index]
        if len(front) <= end or not isinstance(front[start], dict) or not isinstance(front[end], dict):
            raise PipelineError(f"Aquinas PG {MEMBERS[index]} electronic note boundary differs")
        final_seam = (front[end].get("kind") == "division"
                      and front[end].get("attributes") == {"type": "contents"}
                      if index == 3 else
                      front[end].get("kind") == "paragraph"
                      and _node_text(front[end]).startswith("________________"))
        if (front[start].get("kind") != "paragraph"
                or _node_text(front[start]) != HEADING or not final_seam):
            raise PipelineError(f"Aquinas PG {MEMBERS[index]} electronic note boundary differs")
        nodes = deepcopy(front[start:end])
        if (sum(node.get("kind") == "paragraph" for node in nodes) < 10
                or not any("David McClamrock" in _node_text(node) for node in nodes)):
            raise PipelineError("Aquinas first-person editorial note inventory differs")
        private_text = row["text"]
        if private_text.count(HEADING) != 1:
            raise PipelineError("Aquinas electronic note heading differs in readable text")
        text_start = private_text.index(HEADING)
        delimiter = "CONTENTS" if index == 3 else "________________"
        text_end = private_text.index(delimiter, text_start)
        omitted_text = private_text[text_start:text_end]
        if (not omitted_text.startswith(HEADING + "\n\n")
                or "David McClamrock" not in omitted_text
                or "Anything else in this electronic edition" not in omitted_text
                or len(omitted_text) < 2500 or len(omitted_text) > 4000):
            raise PipelineError("Aquinas modern note readable span differs")
        del front[start:end]
        row["text"] = private_text[:text_start] + private_text[text_end:]
        if HEADING in row["text"] or "Anything else in this electronic edition" in row["text"]:
            raise PipelineError("Aquinas modern note remains in public text")
        omissions.append({"row_index": index, "member": MEMBERS[index],
                          "record_id": private["record_id"], "front_start": start,
                          "front_end": end, "private_nodes": nodes,
                          "text_start": text_start, "private_text": omitted_text,
                          "private_row_sha256": _digest(private),
                          "public_row_sha256": _digest(row)})
    return public, omissions


def public_rows(rows: list[dict[str, Any]], *, acceptance_sha256: str | None,
                master_sha256: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if (acceptance_sha256, master_sha256) != (ACCEPTANCE_SHA256, MASTER_SHA256):
        raise PipelineError("Aquinas four-part acceptance authority differs")
    if (len(rows) != 4 or _digest(rows) != PRIVATE_ROWS_SHA256
            or any(row.get("license") != LICENSE for row in rows)):
        raise PipelineError("Aquinas accepted four-part private scope differs")
    public, omissions = _transform(rows)
    if _digest(public) != PUBLIC_ROWS_SHA256:
        raise PipelineError("Aquinas four-part public historical scope differs")
    artifact = {"contract": CONTRACT, "item_id": ITEM,
                "authority": {"acceptance_sha256": ACCEPTANCE_SHA256,
                              "master_sha256": MASTER_SHA256,
                              "scope_sha256": SCOPE_SHA256},
                "row_count": 4, "omissions": omissions}
    return public, artifact


def restore_private_rows(rows: list[dict[str, Any]], artifact: dict[str, Any], *,
                         acceptance_sha256: str | None,
                         master_sha256: str | None) -> list[dict[str, Any]]:
    if (acceptance_sha256, master_sha256) != (ACCEPTANCE_SHA256, MASTER_SHA256):
        raise PipelineError("Aquinas four-part acceptance authority differs")
    if (not isinstance(artifact, dict)
            or set(artifact) != {"contract", "item_id", "authority", "row_count", "omissions"}
            or artifact["contract"] != CONTRACT or artifact["item_id"] != ITEM
            or artifact["authority"] != {"acceptance_sha256": ACCEPTANCE_SHA256,
                                         "master_sha256": MASTER_SHA256,
                                         "scope_sha256": SCOPE_SHA256}
            or type(artifact["row_count"]) is not int or artifact["row_count"] != 4
            or len(rows) != 4
            or not isinstance(artifact["omissions"], list)
            or len(artifact["omissions"]) != 4):
        raise PipelineError("Aquinas four-part private omission receipt differs")
    restored = deepcopy(rows)
    for index, (row, omission) in enumerate(zip(restored, artifact["omissions"], strict=True)):
        if (not isinstance(omission, dict)
                or set(omission) != {"row_index", "member", "record_id", "front_start",
                                     "front_end", "private_nodes", "text_start", "private_text",
                                     "private_row_sha256", "public_row_sha256"}
                or type(omission["row_index"]) is not int
                or omission["row_index"] != index or omission["member"] != MEMBERS[index]
                or omission["record_id"] != row.get("record_id")
                or type(omission["front_start"]) is not int
                or omission["front_start"] != NOTE_STARTS[index]
                or type(omission["front_end"]) is not int
                or omission["front_end"] != NOTE_ENDS[index]
                or omission["public_row_sha256"] != _digest(row)
                or not isinstance(omission["private_nodes"], list)
                or len(omission["private_nodes"]) != NOTE_ENDS[index] - NOTE_STARTS[index]
                or not isinstance(omission["private_text"], str)
                or type(omission["text_start"]) is not int):
            raise PipelineError("Aquinas four-part private omission entry differs")
        front = _front(row)
        start = omission["front_start"]
        if len(front) <= start or not isinstance(front[start], dict):
            raise PipelineError("Aquinas public front-matter seam differs")
        valid_seam = (front[start].get("kind") == "division"
                      and front[start].get("attributes") == {"type": "contents"}
                      if index == 3 else
                      front[start].get("kind") == "paragraph"
                      and _node_text(front[start]).startswith("________________"))
        if not valid_seam:
            raise PipelineError("Aquinas public front-matter seam differs")
        text_start = omission["text_start"]
        delimiter = "CONTENTS" if index == 3 else "________________"
        if text_start < 0 or not row["text"][text_start:].startswith(delimiter):
            raise PipelineError("Aquinas public readable-text seam differs")
        front[start:start] = deepcopy(omission["private_nodes"])
        row["text"] = row["text"][:text_start] + omission["private_text"] + row["text"][text_start:]
        if _digest(row) != omission["private_row_sha256"]:
            raise PipelineError("Aquinas restored private row differs")
    if _digest(restored) != PRIVATE_ROWS_SHA256:
        raise PipelineError("Aquinas restored four-part source differs")
    expected_public, expected_omissions = _transform(restored)
    if expected_public != rows or expected_omissions != artifact["omissions"]:
        raise PipelineError("Aquinas modern note receipt omits or misplaces source material")
    return restored
