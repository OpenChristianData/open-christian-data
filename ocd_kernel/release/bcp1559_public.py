"""Exact reversible historical public scope for the partial BCP1559 witness."""

from copy import deepcopy
from hashlib import sha256
import json
import re
from typing import Any
from urllib.parse import quote, unquote

from ocd_kernel.library._common import PipelineError, canonical_bytes
from ocd_kernel.projection.native_content import readable_content
from ocd_kernel.release.public_allowlist import _scan


CONTRACT = "ocd-public-bcp1559-historical-text-v1"
ITEM = "bcp-1559--bcp-1559-retained-electronic-witness"
LICENSE = (
    "Public domain (United States) for identified pre-1931 prayer-book text, related historical "
    "prayers and proclamation; short factual source notes retained with credit, while modern "
    "Web-authored overview and comparative state-prayer presentation are excluded"
)
ACCEPTANCE_SHA256 = "48bc9707b10b7e30b2e587029df44ba504105d4a51c51e3efd9f54a61bc0bf5d"
MASTER_SHA256 = "344a64e7eac71c751205637a005b0e40890c46153f5e75a605899ab82dc8256b"
PRIVATE_ROWS_SHA256 = "89a6d01f5358eef936f47b9a8e6f72692ca188664707c2b84509509f7762063c"
PUBLIC_ROWS_SHA256 = "1de9caa8123ed3212cee2520bdf6c7a9e018c5994a28f2c05bd0437c1302079f"

# Accepted source order. Row 1 is the Web-authored Elizabethan overview.
# Row 12 retains the historical Litany, but its modern comparative State
# Prayers heading/table remain in the private exact inverse.
CORE_POSITIONS = (
    (9,), (), (9,), (9,), (1, 2, 3), (9,), (9,), (9,),
    (7,), (9,), (7,), (9, 11, 13), (9,), (9,), (9,), (9,),
)
PRIVATE_PREFIX = "urn:ocd:bcp1559:html:"
PRESENTATION_KEYS = frozenset({
    "face", "align", "width", "size", "color", "bgcolor", "valign", "border",
    "cellpadding", "cellspacing", "link", "alink", "vlink", "leftmargin",
    "topmargin", "marginwidth", "marginheight", "hspace", "vspace",
    "noshade", "background", "height", "clear",
})
IMAGE = re.compile(r"(?:\.\./images/)?[A-Za-z0-9_.-]+\.(?:gif|jpg|jpeg|png)\Z", re.I)


def _digest(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _authority(acceptance_sha256: str | None,
               master_sha256: str | None) -> dict[str, str]:
    if (acceptance_sha256, master_sha256) != (ACCEPTANCE_SHA256, MASTER_SHA256):
        raise PipelineError("BCP1559 accepted historical authority differs")
    return {"acceptance_sha256": ACCEPTANCE_SHA256, "master_sha256": MASTER_SHA256}


def _body(row: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        root = row["structure"][0]
        body = root["content"][1]
        content = body["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise PipelineError("BCP1559 native body differs") from exc
    if (root.get("kind") != "division" or body.get("kind") != "source-block"
            or body.get("attributes", {}).get("subtype") != "html-body"
            or not isinstance(content, list)):
        raise PipelineError("BCP1559 native body differs")
    return content


def _semantic_annotation(value: str, node: dict[str, Any]) -> str | None:
    if not value.startswith(PRIVATE_PREFIX):
        if value == "generated-unlisted-source-child":
            return value
        raise PipelineError("BCP1559 private source annotation differs")
    token, *extra = value.split(" ")
    try:
        payload = json.loads(unquote(token[len(PRIVATE_PREFIX):]))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise PipelineError("BCP1559 HTML source annotation differs") from exc
    if (not isinstance(payload, dict) or set(payload) != {"tag", "attributes"}
            or not isinstance(payload["tag"], str)
            or not isinstance(payload["attributes"], list)):
        raise PipelineError("BCP1559 HTML source annotation shape differs")
    preserved = []
    for pair in payload["attributes"]:
        if (not isinstance(pair, list) or len(pair) != 2
                or not all(isinstance(part, str) for part in pair)):
            raise PipelineError("BCP1559 HTML attribute pair differs")
        key, item = pair
        if key in PRESENTATION_KEYS:
            continue
        if key == "class":
            if item not in {"dropcap2georgia", "dropcap2smallprint", "hang", "indent35"}:
                raise PipelineError("BCP1559 unreviewed source class")
            continue
        if key == "href":
            target = node.get("attributes", {}).get("source_target")
            if node.get("kind") != "source-reference" or target != item:
                raise PipelineError("BCP1559 historical hyperlink target differs")
            continue
        if key == "name":
            if node.get("kind") != "segment" or not item:
                raise PipelineError("BCP1559 named source anchor differs")
            preserved.append("source-anchor:" + quote(item, safe=""))
            continue
        if key == "alt":
            if node.get("kind") not in {"figure", "image-reference"}:
                raise PipelineError("BCP1559 source image label differs")
            preserved.append("source-alt:" + quote(item, safe=""))
            continue
        if key in {"rowspan", "colspan"}:
            expected = "row_span" if key == "rowspan" else "columns"
            if (node.get("kind") != "table-cell"
                    or node.get("attributes", {}).get(expected) != item):
                raise PipelineError("BCP1559 historical table span differs")
            continue
        if key == "src":
            if node.get("kind") not in {"figure", "image-reference"} or not IMAGE.fullmatch(item):
                raise PipelineError("BCP1559 source image member differs")
            if node.get("kind") == "image-reference":
                if node.get("attributes", {}).get("source_target") != item:
                    raise PipelineError("BCP1559 image reference does not match its source")
            else:
                children = node.get("content", [])
                if not any(child.get("kind") == "image-reference"
                           and child.get("attributes", {}).get("source_target") == item
                           for child in children if isinstance(child, dict)):
                    raise PipelineError("BCP1559 image reference does not match its source")
            continue
        raise PipelineError(f"BCP1559 unsupported source HTML attribute: {key}")
    for marker in extra:
        if not re.fullmatch(r"source-literal-role:[A-Za-z0-9.%_-]+", marker):
            raise PipelineError("BCP1559 literal speaker role differs")
        preserved.append(marker)
    result = " ".join(preserved)
    if result and _scan(result, "BCP1559 semantic annotation"):
        raise PipelineError("BCP1559 semantic annotation is private")
    return result or None


def _public_target(value: str, node: dict[str, Any]) -> str:
    kind = node.get("kind")
    if kind == "image-reference" and IMAGE.fullmatch(value):
        return "source-image:" + value.removeprefix("../images/")
    if kind == "source-reference":
        if IMAGE.fullmatch(value):
            return "source-image:" + value.removeprefix("../images/")
        if value == "../1552/BCP_1552.htm":
            return "source-related-edition:../1552/BCP_1552.htm"
        if value.startswith(("http://", "https://")):
            return value
    raise PipelineError("BCP1559 private source target differs")


def _site_control(node: Any) -> bool:
    if not isinstance(node, dict):
        return False
    if node.get("kind") == "source-reference":
        return (readable_content(node).strip() == "see below"
                and node.get("attributes", {}).get("source_target") == "#Variations")
    if node.get("kind") == "image-reference":
        return node.get("attributes", {}).get("source_target") in {
            "../images/leaf_side.gif", "../images/Psalms_vert_title.gif"}
    if node.get("kind") == "source-block":
        content = readable_content(node).strip()
        return (
            content.startswith("These prayers were never officially part of the Book of Common Prayer,")
            or content.startswith("These prayers are also found bound up with the 1552 BCP,")
            or content.startswith("* Replaced by a prayer for the King in 1604 (see below)")
            or content.startswith("This prayer added in 1604 (see below for variations).")
        )
    return False


def _transform(rows: list[dict[str, Any]], *, acceptance_sha256: str | None,
               master_sha256: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    authority = _authority(acceptance_sha256, master_sha256)
    if (len(rows) != 16 or _digest(rows) != PRIVATE_ROWS_SHA256
            or any(row.get("license") != LICENSE for row in rows)):
        raise PipelineError("BCP1559 accepted private row scope differs")
    public = deepcopy(rows)
    removed_row = public.pop(1)
    omitted = []
    site_omitted = []
    field_changes = []
    for original_index, selected in enumerate(rows):
        if original_index == 1:
            continue
        public_index = original_index if original_index < 1 else original_index - 1
        row = public[public_index]
        content = _body(row)
        positions = CORE_POSITIONS[original_index]
        if (not positions or max(positions) >= len(content)
                or any(len(readable_content(content[position])) < 100
                       for position in positions)):
            raise PipelineError("BCP1559 historical body block inventory differs")
        omitted.append({"public_index": public_index, "original_index": original_index,
                        "original_content_length": len(content),
                        "kept_positions": list(positions),
                        "nodes": [{"position": position, "node": deepcopy(node)}
                                  for position, node in enumerate(content)
                                  if position not in positions]})
        content[:] = [content[position] for position in positions]
        def strip_site(value: Any, path: list[str | int]) -> None:
            if isinstance(value, list):
                for index in range(len(value) - 1, -1, -1):
                    if _site_control(value[index]):
                        site_omitted.append({"row_index": public_index, "path": path,
                                             "position": index,
                                             "node": deepcopy(value.pop(index))})
                    else:
                        strip_site(value[index], path + [index])
            elif isinstance(value, dict):
                for key, child in value.items():
                    strip_site(child, path + [key])

        strip_site(row["structure"], ["structure"])

        provenance = row.get("provenance")
        if isinstance(provenance, dict) and "source_location" in provenance:
            before = provenance.pop("source_location")
            field_changes.append({"row_index": public_index,
                                  "path": ["provenance", "source_location"],
                                  "private": before, "public": None})

        def visit(value: Any, path: list[str | int]) -> None:
            if isinstance(value, list):
                for index, child in enumerate(value):
                    visit(child, path + [index])
            elif isinstance(value, dict):
                attributes = value.get("attributes")
                if "kind" in value and isinstance(attributes, dict):
                    for key in ("source_annotations", "source_target"):
                        if key not in attributes:
                            continue
                        before = attributes[key]
                        if not isinstance(before, str):
                            raise PipelineError("BCP1559 source field is not a string")
                        after = (_semantic_annotation(before, value) if key == "source_annotations"
                                 else _public_target(before, value))
                        if before != after:
                            if after is None:
                                del attributes[key]
                            else:
                                attributes[key] = after
                            field_changes.append({"row_index": public_index,
                                                  "path": path + ["attributes", key],
                                                  "private": before, "public": after})
                for key, child in value.items():
                    if key != "attributes":
                        visit(child, path + [key])

        visit(row, [])
        row["text"] = readable_content(row["structure"][0])
    if (len(public) != 15 or len(omitted) != 15
            or not site_omitted
            or any(not row.get("text") for row in public)
            or _scan(public, "BCP1559 historical public rows")):
        raise PipelineError("BCP1559 public historical scope differs")
    artifact = {"contract": CONTRACT, "item_id": ITEM, "authority": authority,
                "private_rows_sha256": PRIVATE_ROWS_SHA256,
                "public_rows_sha256": _digest(public),
                "removed_row": {"position": 1, "row": removed_row},
                "omitted_body": omitted, "site_omitted": site_omitted,
                "fields": field_changes}
    return public, artifact


def public_rows(rows: list[dict[str, Any]], *, acceptance_sha256: str | None,
                master_sha256: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    public, artifact = _transform(
        rows, acceptance_sha256=acceptance_sha256, master_sha256=master_sha256)
    if artifact["public_rows_sha256"] != PUBLIC_ROWS_SHA256:
        raise PipelineError("BCP1559 historical public row digest differs")
    return public, artifact


def restore_private_rows(rows: list[dict[str, Any]], artifact: dict[str, Any], *,
                         acceptance_sha256: str | None,
                         master_sha256: str | None) -> list[dict[str, Any]]:
    authority = _authority(acceptance_sha256, master_sha256)
    if (len(rows) != 15 or not isinstance(artifact, dict)
            or set(artifact) != {"contract", "item_id", "authority", "private_rows_sha256",
                                 "public_rows_sha256", "removed_row", "omitted_body",
                                 "site_omitted", "fields"}
            or artifact["contract"] != CONTRACT or artifact["item_id"] != ITEM
            or artifact["authority"] != authority
            or artifact["private_rows_sha256"] != PRIVATE_ROWS_SHA256
            or artifact["public_rows_sha256"] != PUBLIC_ROWS_SHA256
            or _digest(rows) != PUBLIC_ROWS_SHA256):
        raise PipelineError("BCP1559 private omission receipt differs")
    restored = deepcopy(rows)
    fields = artifact["fields"]
    if not isinstance(fields, list) or not fields:
        raise PipelineError("BCP1559 omitted field inventory differs")
    for field in reversed(fields):
        if (not isinstance(field, dict)
                or set(field) != {"row_index", "path", "private", "public"}
                or type(field["row_index"]) is not int
                or not 0 <= field["row_index"] < len(restored)
                or not isinstance(field["path"], list) or not field["path"]):
            raise PipelineError("BCP1559 private field receipt differs")
        holder: Any = restored[field["row_index"]]
        try:
            for part in field["path"][:-1]:
                holder = holder[part]
        except (KeyError, IndexError, TypeError) as exc:
            raise PipelineError("BCP1559 private field path differs") from exc
        key = field["path"][-1]
        if (not isinstance(holder, dict) or not isinstance(key, str)
                or (field["public"] is None and key in holder)
                or (field["public"] is not None and holder.get(key) != field["public"])):
            raise PipelineError("BCP1559 public field receipt target differs")
        holder[key] = field["private"]

    sites = artifact["site_omitted"]
    if not isinstance(sites, list) or not sites:
        raise PipelineError("BCP1559 source-site control receipt differs")
    for entry in reversed(sites):
        if (not isinstance(entry, dict)
                or set(entry) != {"row_index", "path", "position", "node"}
                or type(entry["row_index"]) is not int
                or not 0 <= entry["row_index"] < len(restored)
                or not isinstance(entry["path"], list)
                or type(entry["position"]) is not int
                or not _site_control(entry["node"])):
            raise PipelineError("BCP1559 source-site control entry differs")
        holder: Any = restored[entry["row_index"]]
        try:
            for part in entry["path"]:
                holder = holder[part]
        except (KeyError, IndexError, TypeError) as exc:
            raise PipelineError("BCP1559 source-site control path differs") from exc
        if not isinstance(holder, list) or not 0 <= entry["position"] <= len(holder):
            raise PipelineError("BCP1559 source-site control target differs")
        holder.insert(entry["position"], deepcopy(entry["node"]))

    def insert_nodes(content: list, entries: list, expected_length: int) -> None:
        if not isinstance(entries, list):
            raise PipelineError("BCP1559 omitted node inventory differs")
        for entry in entries:
            if (not isinstance(entry, dict) or set(entry) != {"position", "node"}
                    or type(entry["position"]) is not int
                    or not 0 <= entry["position"] <= len(content)):
                raise PipelineError("BCP1559 omitted node position differs")
            content.insert(entry["position"], deepcopy(entry["node"]))
        if len(content) != expected_length:
            raise PipelineError("BCP1559 restored native block inventory differs")

    omitted = artifact["omitted_body"]
    if not isinstance(omitted, list) or len(omitted) != 15:
        raise PipelineError("BCP1559 omitted body inventory differs")
    for public_index, entry in enumerate(omitted):
        original_index = public_index if public_index < 1 else public_index + 1
        if (not isinstance(entry, dict)
                or set(entry) != {"public_index", "original_index", "original_content_length",
                                 "kept_positions", "nodes"}
                or entry["public_index"] != public_index
                or entry["original_index"] != original_index
                or entry["kept_positions"] != list(CORE_POSITIONS[original_index])
                or type(entry["original_content_length"]) is not int):
            raise PipelineError("BCP1559 historical body receipt differs")
        insert_nodes(_body(restored[public_index]), entry["nodes"],
                     entry["original_content_length"])
        restored[public_index]["text"] = readable_content(restored[public_index]["structure"][0])
    removed = artifact["removed_row"]
    if (not isinstance(removed, dict) or set(removed) != {"position", "row"}
            or removed["position"] != 1 or not isinstance(removed["row"], dict)):
        raise PipelineError("BCP1559 modern contents row receipt differs")
    restored.insert(1, deepcopy(removed["row"]))
    if _digest(restored) != PRIVATE_ROWS_SHA256:
        raise PipelineError("BCP1559 accepted private inverse differs")
    expected_rows, expected_artifact = _transform(
        restored, acceptance_sha256=acceptance_sha256, master_sha256=master_sha256)
    if expected_rows != rows or expected_artifact != artifact:
        raise PipelineError("BCP1559 public omission receipt is incomplete")
    return restored
