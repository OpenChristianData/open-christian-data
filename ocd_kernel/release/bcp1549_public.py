"""Exact reversible historical public scope for the partial BCP1549 witness."""

from copy import deepcopy
from hashlib import sha256
import json
import re
from typing import Any
from urllib.parse import quote, unquote

from ocd_kernel.library._common import PipelineError, canonical_bytes
from ocd_kernel.projection.native_content import readable_content
from ocd_kernel.release.public_allowlist import _scan


CONTRACT = "ocd-public-bcp1549-historical-text-v1"
ITEM = "bcp-1549--bcp-1549-retained-electronic-witness"
LICENSE = (
    "Public domain (United States) for identified historical 1549/1550/1552/1559 prayer-book text "
    "and the 1910 Gibson introduction; modern Web-authored overview and site presentation excluded"
)
ACCEPTANCE_SHA256 = "1b7c0850751f108f7dd892eca9d0467da385a21ffc6e5b8472197a59035f02c6"
MASTER_SHA256 = "ffedaf0ffc62fbe07f8cd4afaf62305a335d1a152da6ce1f9199841ea08c8739"
PRIVATE_ROWS_SHA256 = "6828a9e26f1a5038ba87df146955563fc9cbb782cda47bb2b0a081394f48e0ae"
PUBLIC_ROWS_SHA256 = "4d3568a1e11ce891438b0da6313684bf68df65a0a3b71a3b451026137d46be43"

# The numbered entries are positions in the unchanged accepted projection. Row 6
# is a modern site contents page. Row 0 retains its original-book contents cell.
CORE_POSITIONS = (
    (9,), (9,), (9,), (9,), (9,), (7,), (), (7,), (7,), (7,),
    (7,), (7,), (7,), (7,), (7,), (7,), (7,), (7,), (7,), (7,),
    (7,), (9,), (9,), (9,), (7,), (7,), (7,), (7,), (7,), (7,),
    (1, 5, 9), (7,), (7,), (11,),
)
PRIVATE_PREFIX = "urn:ocd:bcp1549:html:"
PRESENTATION_KEYS = frozenset({
    "face", "align", "width", "size", "color", "bgcolor", "valign", "border",
    "cellpadding", "cellspacing", "link", "alink", "vlink", "leftmargin",
    "topmargin", "marginwidth", "marginheight", "hspace", "vspace",
    "noshade", "background", "height",
})
IMAGE = re.compile(r"(?:\.\./images/)?[A-Za-z0-9_.-]+\.(?:gif|jpg|jpeg|png)\Z", re.I)


def _digest(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _authority(acceptance_sha256: str | None,
               master_sha256: str | None) -> dict[str, str]:
    if (acceptance_sha256, master_sha256) != (ACCEPTANCE_SHA256, MASTER_SHA256):
        raise PipelineError("BCP1549 accepted historical authority differs")
    return {"acceptance_sha256": ACCEPTANCE_SHA256, "master_sha256": MASTER_SHA256}


def _body(row: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        root = row["structure"][0]
        body = root["content"][1]
        content = body["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise PipelineError("BCP1549 native body differs") from exc
    if (root.get("kind") != "division" or body.get("kind") != "source-block"
            or body.get("attributes", {}).get("subtype") != "html-body"
            or not isinstance(content, list)):
        raise PipelineError("BCP1549 native body differs")
    return content


def _semantic_annotation(value: str, node: dict[str, Any]) -> str | None:
    if not value.startswith(PRIVATE_PREFIX):
        if value == "generated-unlisted-source-child":
            return value
        raise PipelineError("BCP1549 private source annotation differs")
    token, *extra = value.split(" ")
    try:
        payload = json.loads(unquote(token[len(PRIVATE_PREFIX):]))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise PipelineError("BCP1549 HTML source annotation differs") from exc
    if (not isinstance(payload, dict) or set(payload) != {"tag", "attributes"}
            or not isinstance(payload["tag"], str)
            or not isinstance(payload["attributes"], list)):
        raise PipelineError("BCP1549 HTML source annotation shape differs")
    preserved = []
    for pair in payload["attributes"]:
        if (not isinstance(pair, list) or len(pair) != 2
                or not all(isinstance(part, str) for part in pair)):
            raise PipelineError("BCP1549 HTML attribute pair differs")
        key, item = pair
        if key in PRESENTATION_KEYS:
            continue
        if key == "class":
            if "small-grey" in item.split():
                preserved.append("source-note-role:variant")
            continue
        if key == "href":
            target = node.get("attributes", {}).get("source_target")
            if (node.get("kind") != "source-reference" or not isinstance(target, str)
                    or not target.startswith(("http://", "https://", "mailto:"))):
                raise PipelineError("BCP1549 historical hyperlink target differs")
            continue
        if key == "name":
            if node.get("kind") != "segment" or not item:
                raise PipelineError("BCP1549 named source anchor differs")
            preserved.append("source-anchor:" + quote(item, safe=""))
            continue
        if key == "alt":
            if node.get("kind") != "figure":
                raise PipelineError("BCP1549 source image label differs")
            preserved.append("source-alt:" + quote(item, safe=""))
            continue
        if key in {"rowspan", "colspan"}:
            expected = "row_span" if key == "rowspan" else "columns"
            if (node.get("kind") != "table-cell"
                    or node.get("attributes", {}).get(expected) != item):
                raise PipelineError("BCP1549 historical table span differs")
            continue
        if key == "src":
            if node.get("kind") != "figure" or not IMAGE.fullmatch(item):
                raise PipelineError("BCP1549 source image member differs")
            children = node.get("content", [])
            if not any(child.get("kind") == "image-reference"
                       and child.get("attributes", {}).get("source_target") == item
                       for child in children if isinstance(child, dict)):
                raise PipelineError("BCP1549 image reference does not match its source")
            continue
        raise PipelineError(f"BCP1549 unsupported source HTML attribute: {key}")
    for marker in extra:
        if not re.fullmatch(r"source-literal-role:[A-Za-z0-9.%_-]+", marker):
            raise PipelineError("BCP1549 literal speaker role differs")
        preserved.append(marker)
    result = " ".join(preserved)
    if result and _scan(result, "BCP1549 semantic annotation"):
        raise PipelineError("BCP1549 semantic annotation is private")
    return result or None


def _public_target(value: str, node: dict[str, Any]) -> str:
    if value.startswith(("http://", "https://", "mailto:")):
        return value
    if node.get("kind") != "image-reference" or not IMAGE.fullmatch(value):
        raise PipelineError("BCP1549 private image target differs")
    return "source-image:" + value.removeprefix("../images/")


def _site_control(node: Any) -> bool:
    if not isinstance(node, dict):
        return False
    if node.get("kind") == "segment":
        return readable_content(node) in {
            "This is the last page of the Preface above, as originally printed in 1549. "
            "Click on the image to get a larger, readable image (125K in size).",
            "Above is the first page of the original 1549 service of Holy Communion. "
            "Clicking on the image will bring up a larger (87K), readable image of this page.",
            "Corresponding pages from this section of the the 1549 and 1552 Ordinals are shown above. "
            "Click on the images to see larger (100K) readable versions of these images.",
            "Corresponding pages from this section of the the 1549 and 1552 Ordinals are shown above. "
            "Click on the images to see larger (110K) readable versions of these images.",
            "Corresponding pages from this section of the the 1550 and 1552 Ordinals are shown at left. "
            "Click on the images to see larger (100K) readable versions of these images.",
            "Corresponding pages from this section of the the 1550 and 1552 Ordinals are shown at left. "
            "Click on the images to see larger (110K) readable versions of these images.",
        }
    if node.get("kind") == "source-reference":
        return (readable_content(node).strip() in {"Next Readings", "Previous Readings"}
                and node.get("attributes", {}).get("source_target", "").startswith(
                    "http://justus.anglican.org/resources/bcp/1549/Reading"))
    if node.get("kind") == "figure":
        children = node.get("content", [])
        return any(child.get("kind") == "image-reference"
                   and child.get("attributes", {}).get("source_target") in {
                       "dot_clear.gif", "leaf_side.gif", "../images/leaf_side.gif"}
                   for child in children if isinstance(child, dict))
    return False


def _transform(rows: list[dict[str, Any]], *, acceptance_sha256: str | None,
               master_sha256: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    authority = _authority(acceptance_sha256, master_sha256)
    if (len(rows) != 34 or _digest(rows) != PRIVATE_ROWS_SHA256
            or any(row.get("license") != LICENSE for row in rows)):
        raise PipelineError("BCP1549 accepted private row scope differs")
    public = deepcopy(rows)
    removed_row = public.pop(6)
    omitted = []
    table_omitted = []
    cell_omitted = []
    site_omitted = []
    field_changes = []
    for original_index, selected in enumerate(rows):
        if original_index == 6:
            continue
        public_index = original_index if original_index < 6 else original_index - 1
        row = public[public_index]
        content = _body(row)
        positions = CORE_POSITIONS[original_index]
        if (not positions or max(positions) >= len(content)
                or any(len(readable_content(content[position])) < 100
                       for position in positions)):
            raise PipelineError("BCP1549 historical body block inventory differs")
        omitted.append({"public_index": public_index, "original_index": original_index,
                        "original_content_length": len(content),
                        "kept_positions": list(positions),
                        "nodes": [{"position": position, "node": deepcopy(node)}
                                  for position, node in enumerate(content)
                                  if position not in positions]})
        content[:] = [content[position] for position in positions]
        if original_index == 0:
            table = content[0]
            children = table.get("content")
            if table.get("kind") != "table" or not isinstance(children, list) or len(children) != 7:
                raise PipelineError("BCP1549 historical contents table differs")
            table_omitted = [{"position": i, "node": deepcopy(node)}
                             for i, node in enumerate(children) if i != 5]
            children[:] = [children[5]]
            item = children[0]
            cells = item.get("content")
            if item.get("kind") != "table-row" or not isinstance(cells, list) or len(cells) != 5:
                raise PipelineError("BCP1549 original-book contents row differs")
            cell_omitted = [{"position": i, "node": deepcopy(node)}
                            for i, node in enumerate(cells) if i != 1]
            cells[:] = [cells[1]]

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
                            raise PipelineError("BCP1549 source field is not a string")
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
    if (len(public) != 33 or len(omitted) != 33
            or not table_omitted or not cell_omitted
            or sum(entry["node"]["kind"] == "source-reference"
                   for entry in site_omitted) != 23
            or sum(entry["node"]["kind"] == "segment"
                   for entry in site_omitted) != 6
            or any(not row.get("text") for row in public)
            or _scan(public, "BCP1549 historical public rows")):
        raise PipelineError("BCP1549 public historical scope differs")
    artifact = {"contract": CONTRACT, "item_id": ITEM, "authority": authority,
                "private_rows_sha256": PRIVATE_ROWS_SHA256,
                "public_rows_sha256": _digest(public),
                "removed_row": {"position": 6, "row": removed_row},
                "omitted_body": omitted, "toc_table_omitted": table_omitted,
                "toc_cell_omitted": cell_omitted, "site_omitted": site_omitted,
                "fields": field_changes}
    return public, artifact


def public_rows(rows: list[dict[str, Any]], *, acceptance_sha256: str | None,
                master_sha256: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    public, artifact = _transform(
        rows, acceptance_sha256=acceptance_sha256, master_sha256=master_sha256)
    if artifact["public_rows_sha256"] != PUBLIC_ROWS_SHA256:
        raise PipelineError("BCP1549 historical public row digest differs")
    return public, artifact


def restore_private_rows(rows: list[dict[str, Any]], artifact: dict[str, Any], *,
                         acceptance_sha256: str | None,
                         master_sha256: str | None) -> list[dict[str, Any]]:
    authority = _authority(acceptance_sha256, master_sha256)
    if (len(rows) != 33 or not isinstance(artifact, dict)
            or set(artifact) != {"contract", "item_id", "authority", "private_rows_sha256",
                                 "public_rows_sha256", "removed_row", "omitted_body",
                                 "toc_table_omitted", "toc_cell_omitted", "site_omitted",
                                 "fields"}
            or artifact["contract"] != CONTRACT or artifact["item_id"] != ITEM
            or artifact["authority"] != authority
            or artifact["private_rows_sha256"] != PRIVATE_ROWS_SHA256
            or artifact["public_rows_sha256"] != PUBLIC_ROWS_SHA256
            or _digest(rows) != PUBLIC_ROWS_SHA256):
        raise PipelineError("BCP1549 private omission receipt differs")
    restored = deepcopy(rows)
    fields = artifact["fields"]
    if not isinstance(fields, list) or not fields:
        raise PipelineError("BCP1549 omitted field inventory differs")
    for field in reversed(fields):
        if (not isinstance(field, dict)
                or set(field) != {"row_index", "path", "private", "public"}
                or type(field["row_index"]) is not int
                or not 0 <= field["row_index"] < len(restored)
                or not isinstance(field["path"], list) or not field["path"]):
            raise PipelineError("BCP1549 private field receipt differs")
        holder: Any = restored[field["row_index"]]
        try:
            for part in field["path"][:-1]:
                holder = holder[part]
        except (KeyError, IndexError, TypeError) as exc:
            raise PipelineError("BCP1549 private field path differs") from exc
        key = field["path"][-1]
        if (not isinstance(holder, dict) or not isinstance(key, str)
                or (field["public"] is None and key in holder)
                or (field["public"] is not None and holder.get(key) != field["public"])):
            raise PipelineError("BCP1549 public field receipt target differs")
        holder[key] = field["private"]

    sites = artifact["site_omitted"]
    if not isinstance(sites, list) or not sites:
        raise PipelineError("BCP1549 source-site control receipt differs")
    for entry in reversed(sites):
        if (not isinstance(entry, dict)
                or set(entry) != {"row_index", "path", "position", "node"}
                or type(entry["row_index"]) is not int
                or not 0 <= entry["row_index"] < len(restored)
                or not isinstance(entry["path"], list)
                or type(entry["position"]) is not int
                or not _site_control(entry["node"])):
            raise PipelineError("BCP1549 source-site control entry differs")
        holder: Any = restored[entry["row_index"]]
        try:
            for part in entry["path"]:
                holder = holder[part]
        except (KeyError, IndexError, TypeError) as exc:
            raise PipelineError("BCP1549 source-site control path differs") from exc
        if not isinstance(holder, list) or not 0 <= entry["position"] <= len(holder):
            raise PipelineError("BCP1549 source-site control target differs")
        holder.insert(entry["position"], deepcopy(entry["node"]))

    def insert_nodes(content: list, entries: list, expected_length: int) -> None:
        if not isinstance(entries, list):
            raise PipelineError("BCP1549 omitted node inventory differs")
        for entry in entries:
            if (not isinstance(entry, dict) or set(entry) != {"position", "node"}
                    or type(entry["position"]) is not int
                    or not 0 <= entry["position"] <= len(content)):
                raise PipelineError("BCP1549 omitted node position differs")
            content.insert(entry["position"], deepcopy(entry["node"]))
        if len(content) != expected_length:
            raise PipelineError("BCP1549 restored native block inventory differs")

    toc = _body(restored[0])[0]
    table_children = toc["content"]
    if len(table_children) != 1:
        raise PipelineError("BCP1549 selected historical contents table differs")
    insert_nodes(table_children[0]["content"], artifact["toc_cell_omitted"], 5)
    insert_nodes(table_children, artifact["toc_table_omitted"], 7)
    omitted = artifact["omitted_body"]
    if not isinstance(omitted, list) or len(omitted) != 33:
        raise PipelineError("BCP1549 omitted body inventory differs")
    for public_index, entry in enumerate(omitted):
        original_index = public_index if public_index < 6 else public_index + 1
        if (not isinstance(entry, dict)
                or set(entry) != {"public_index", "original_index", "original_content_length",
                                 "kept_positions", "nodes"}
                or entry["public_index"] != public_index
                or entry["original_index"] != original_index
                or entry["kept_positions"] != list(CORE_POSITIONS[original_index])
                or type(entry["original_content_length"]) is not int):
            raise PipelineError("BCP1549 historical body receipt differs")
        insert_nodes(_body(restored[public_index]), entry["nodes"],
                     entry["original_content_length"])
        restored[public_index]["text"] = readable_content(restored[public_index]["structure"][0])
    removed = artifact["removed_row"]
    if (not isinstance(removed, dict) or set(removed) != {"position", "row"}
            or removed["position"] != 6 or not isinstance(removed["row"], dict)):
        raise PipelineError("BCP1549 modern contents row receipt differs")
    restored.insert(6, deepcopy(removed["row"]))
    if _digest(restored) != PRIVATE_ROWS_SHA256:
        raise PipelineError("BCP1549 accepted private inverse differs")
    expected_rows, expected_artifact = _transform(
        restored, acceptance_sha256=acceptance_sha256, master_sha256=master_sha256)
    if expected_rows != rows or expected_artifact != artifact:
        raise PipelineError("BCP1549 public omission receipt is incomplete")
    return restored
