"""Typed, code-native artifact renderers for the Corpus Review Viewer."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable


class RendererError(ValueError):
    """Raised when verified artifact bytes cannot be rendered safely."""


MAX_STRUCTURE_LOCATION_SCALARS = 512
MAX_STRUCTURE_LABEL_SCALARS = 512
MAX_STRUCTURE_CONTEXT_SCALARS = 20_000
MAX_PAGE_SCALARS = 50_000
# A renderer page is nested inside stage/Compare envelopes that carry the
# selected context and other review metadata. Keep the visible node array well
# below the endpoint's 512 KiB response bound so a table-heavy page still has
# room for that envelope.
MAX_PAGE_SERIALIZED_BYTES = 180_000
MAX_TABLE_COLSPAN = 1_000
MAX_TABLE_ROWSPAN = 65_534
_TABLE_ASCII_WHITESPACE = " \t\n\r\f"
_TABLE_ASCII_DIGITS = re.compile(r"[0-9]+")
ECMASCRIPT_TRIM_CODEPOINTS = frozenset(
    "\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff"
)


COLLAPSIBLE_WHITESPACE = re.compile("[\t\n\f\r ]+")
UNICODE_SURROGATES = re.compile(r"[\uD800-\uDFFF]")


def project_visible_text(value: str) -> str:
    """Apply the one whitespace projection a browser applies to ordinary rendered text.

    Every non-preformatted node, structure label, and structure context text uses this
    projection so backend text, DOM text, and persisted note text are the same string.
    Only the characters CSS collapses in ``white-space: normal`` are collapsed; every
    other Unicode space stays exact because the browser renders it verbatim.
    """
    return COLLAPSIBLE_WHITESPACE.sub(" ", value).strip(" ")


def is_route_valid_scalar_text(value: object, maximum: int | None = None) -> bool:
    """Match ECMAScript trim() nonemptiness while rejecting invalid Unicode scalars."""
    return (
        isinstance(value, str)
        and any(character not in ECMASCRIPT_TRIM_CODEPOINTS for character in value)
        and _is_unicode_scalar_text(value)
        and (maximum is None or len(value) <= maximum)
    )


class _StructureLocations:
    """Allocate stable route-safe locations without trusting native uniqueness."""

    def __init__(self) -> None:
        self._used = {"start"}

    def allocate(self, candidate: str | None, ordinal: int) -> str:
        if (
            is_route_valid_scalar_text(candidate, MAX_STRUCTURE_LOCATION_SCALARS)
            and candidate != "start"
            and candidate not in self._used
        ):
            location = candidate
        else:
            seed = "fallback" if candidate is None else candidate
            digest = hashlib.sha256(
                seed.encode("utf-8", errors="surrogatepass")
            ).hexdigest()[:16]
            location = f"section-{ordinal}-{digest}"
            suffix = 1
            while location in self._used:
                suffix += 1
                location = f"section-{ordinal}-{digest}-{suffix}"
        self._used.add(location)
        return location


def _node(node_type: str, text: str, **extra: object) -> dict[str, Any]:
    return {"type": node_type, "text": text, **extra}


def _parse_table_span(value: object, attribute: str, maximum: int) -> int | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RendererError(f"table {attribute} span must be ASCII decimal text")
    normalized = value.strip(_TABLE_ASCII_WHITESPACE)
    if not normalized or _TABLE_ASCII_DIGITS.fullmatch(normalized) is None:
        raise RendererError(f"table {attribute} span is invalid")
    significant = normalized.lstrip("0")
    maximum_text = str(maximum)
    if (
        not significant
        or len(significant) > len(maximum_text)
        or (len(significant) == len(maximum_text) and significant > maximum_text)
    ):
        raise RendererError(f"table {attribute} span must be between 1 and {maximum}")
    parsed = int(significant, 10)
    return None if parsed == 1 else parsed


def _html_table_span(
    attrs: list[tuple[str, str | None]], attribute: str, maximum: int
) -> int | None:
    values = [value for name, value in attrs if name.lower() == attribute]
    if len(values) > 1:
        raise RendererError(f"table {attribute} span attribute is duplicated")
    if values and values[0] is None:
        raise RendererError(f"table {attribute} span is invalid")
    return _parse_table_span(values[0], attribute, maximum) if values else None


def _serialized_json_bytes(value: object) -> int:
    """Return the UTF-8 size of the JSON form emitted by the review service."""
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def _node_text(node: dict[str, Any], cache: dict[int, str] | None = None) -> str:
    cache_key = id(node)
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    if not isinstance(node, dict):
        raise RendererError("renderer produced a node that is not an object")
    children = node.get("children", [])
    node_type = node.get("type")
    if not isinstance(node_type, str):
        raise RendererError("renderer produced a node without a string type")
    own_text = (
        str(node.get("key", ""))
        if node_type == "json-property"
        else ""
        if node_type in {"table", "table-row"}
        else str(node.get("text", ""))
    )
    text = (
        own_text
        if node_type == "preformatted" and not children
        else " ".join(
            part
            for part in [own_text, *(_node_text(child, cache) for child in children)]
            if part
        ).strip(" ")
    )
    if cache is not None:
        cache[cache_key] = text
    return text


def _nodes_text(
    nodes: list[dict[str, Any]], cache: dict[int, str] | None = None
) -> str:
    if len(nodes) == 1 and nodes[0].get("type") == "preformatted":
        return _node_text(nodes[0], cache)
    return " ".join(text for node in nodes if (text := _node_text(node, cache))).strip(
        " "
    )


def _is_unicode_scalar_text(value: str) -> bool:
    return UNICODE_SURROGATES.search(value) is None


def _bounded_visible_text(value: str, maximum: int, description: str) -> str:
    if not _is_unicode_scalar_text(value):
        raise RendererError(f"{description} must contain only Unicode scalar values")
    if len(value) <= maximum:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    marker = f"\n[{description} shortened to {maximum} Unicode scalars; full SHA-256 {digest}]"
    return value[: maximum - len(marker)] + marker


def bounded_visible_text(value: str, maximum: int, description: str) -> str:
    """Public serve-time visible projection with an honest SHA-marked truncation."""
    return _bounded_visible_text(value, maximum, description)


_DOCUMENT_NODE_TYPES = frozenset(
    {
        "heading",
        "paragraph",
        "preformatted",
        "blockquote",
        "details",
        "list-item",
        "list",
        "table",
        "table-row",
        "table-header",
        "table-cell",
        "json-object",
        "json-array",
        "json-property",
        "json-value",
        "image",
    }
)
PRESENTATION_KINDS = frozenset(
    {
        "sanitized-html",
        "xml-reader",
        "tei-reader",
        "json-tree",
        "exact-text",
        "image-facsimile",
        "pdf-native",
        "epub-reader",
        "sword-zld-reader",
        "barnes-zcom-reader",
        "sword-members-reader",
    }
)
# Ticket 06b: binary declared kinds receive raw sha256-verified bytes; text
# kinds keep the decoded UTF-8 path unchanged.
BINARY_PRESENTATION_KINDS = frozenset(
    {"image-facsimile", "pdf-native", "epub-reader", "unsupported-binary"}
)
CONTEXT_PRESENTATION_KINDS = frozenset(
    {"sword-zld-reader", "barnes-zcom-reader", "sword-members-reader"}
)
_DOCUMENT_NODE_FIELDS = frozenset(
    {
        "type",
        "text",
        "level",
        "location",
        "key",
        "value_kind",
        "children",
        "scope",
        "colspan",
        "rowspan",
        "inline",
        "align",
        "ordered",
        "start",
    }
)
_ROOT_NODE_TYPES = frozenset(
    {
        "heading",
        "paragraph",
        "preformatted",
        "blockquote",
        "details",
        "list-item",
        "list",
        "table",
        "json-object",
        "json-array",
        "json-value",
        "image",
    }
)
_CONTEXT_ROOT_NODE_TYPES = _ROOT_NODE_TYPES
_CHILD_NODE_TYPES = {
    "details": _ROOT_NODE_TYPES,
    "blockquote": _ROOT_NODE_TYPES,
    "list": frozenset({"list-item"}),
    "list-item": _ROOT_NODE_TYPES,
    "table": frozenset({"table-row"}),
    "table-row": frozenset({"table-header", "table-cell"}),
    "json-object": frozenset({"json-property"}),
    "json-array": frozenset({"json-property"}),
    "json-property": frozenset({"json-object", "json-array", "json-value"}),
}


def _validate_document_nodes(
    value: object,
    label: str,
    *,
    allowed_types: frozenset[str] = _ROOT_NODE_TYPES,
    validated_nodes: set[int] | None = None,
    active_nodes: set[int] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise RendererError(f"renderer produced {label} that is not an array")
    for index, item in enumerate(value):
        if not isinstance(item, dict) or set(item) - _DOCUMENT_NODE_FIELDS:
            raise RendererError(f"renderer produced an invalid {label} node")
        node_type = item.get("type")
        if (
            not isinstance(node_type, str)
            or node_type not in _DOCUMENT_NODE_TYPES
            or node_type not in allowed_types
            or not isinstance(item.get("text"), str)
        ):
            raise RendererError(f"renderer produced an invalid {label} node")
        node_identity = id(item)
        if "align" in item and (node_type != "paragraph" or item["align"] != "center"):
            raise RendererError(f"renderer produced an invalid {label} paragraph alignment")
        if active_nodes is not None and node_identity in active_nodes:
            raise RendererError("renderer produced a cyclic document node graph")
        if validated_nodes is not None and node_identity in validated_nodes:
            continue
        if not _is_unicode_scalar_text(item["text"]):
            raise RendererError(f"renderer produced an invalid {label} node")
        if node_type != "preformatted" and item["text"] != project_visible_text(
            item["text"]
        ):
            raise RendererError(
                f"renderer produced {label} text that is not the canonical whitespace projection"
            )
        if "level" in item and (
            not isinstance(item["level"], int)
            or isinstance(item["level"], bool)
            or not 1 <= item["level"] <= 6
        ):
            raise RendererError(f"renderer produced an invalid {label} node level")
        if "location" in item and not is_route_valid_scalar_text(
            item["location"], MAX_STRUCTURE_LOCATION_SCALARS
        ):
            raise RendererError(f"renderer produced an invalid {label} node location")
        if "key" in item and (
            not isinstance(item["key"], str) or not _is_unicode_scalar_text(item["key"])
        ):
            raise RendererError(f"renderer produced an invalid {label} node key")
        if "level" in item and node_type != "heading":
            raise RendererError(f"renderer produced an invalid {label} node level")
        if "location" in item and node_type not in {
            "heading",
            "paragraph",
            "preformatted",
            "json-property",
        }:
            raise RendererError(f"renderer produced an invalid {label} node location")
        if "key" in item and node_type != "json-property":
            raise RendererError(f"renderer produced an invalid {label} node key")
        if "value_kind" in item and (
            node_type != "json-value"
            or not isinstance(item["value_kind"], str)
            or item["value_kind"] not in {"string", "number", "boolean", "null"}
        ):
            raise RendererError(f"renderer produced an invalid {label} node value kind")
        if node_type == "table-header":
            if not isinstance(item.get("scope"), str) or item["scope"] not in {
                "row",
                "col",
            }:
                raise RendererError(
                    "renderer produced a table header without a governed row or column scope"
                )
        elif "scope" in item:
            raise RendererError(f"renderer produced an invalid {label} node scope")
        for field, maximum in (
            ("colspan", MAX_TABLE_COLSPAN),
            ("rowspan", MAX_TABLE_ROWSPAN),
        ):
            if field not in item:
                continue
            if node_type not in {"table-header", "table-cell"}:
                raise RendererError(
                    f"renderer produced table {field} span on a non-cell node"
                )
            value = item[field]
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 2 <= value <= maximum
            ):
                raise RendererError(f"renderer produced invalid table {field} span")
        if node_type == "json-property":
            if "key" not in item or "location" not in item:
                raise RendererError(
                    f"renderer produced an invalid {label} JSON property"
                )
            if item["text"] != item["key"]:
                raise RendererError(
                    "renderer JSON property text does not match its visible key"
                )
        elif node_type == "json-value" and "value_kind" not in item:
            raise RendererError(f"renderer produced an invalid {label} JSON value")
        if node_type == "table" and item["text"]:
            raise RendererError(
                "renderer table text must be empty because the browser ignores it"
            )
        if node_type == "table-row" and item["text"]:
            raise RendererError(
                "renderer table row text must be empty because the browser ignores it"
            )
        if "start" in item and (
            node_type != "list"
            or not isinstance(item["start"], int)
            or isinstance(item["start"], bool)
            or abs(item["start"]) > 999999
        ):
            raise RendererError("invalid ordered list start")
        if "ordered" in item and (
            node_type != "list" or not isinstance(item["ordered"], bool)
        ):
            raise RendererError("invalid list ordering")
        if "inline" in item:
            runs = item["inline"]
            if node_type not in {
                "paragraph",
                "heading",
                "blockquote",
                "list-item",
                "table-cell",
                "table-header",
            } or not isinstance(runs, list):
                raise RendererError("invalid inline runs")
            for run in runs:
                if (
                    not isinstance(run, dict)
                    or set(run) != {"text", "marks"}
                    or not isinstance(run["text"], str)
                    or not _is_unicode_scalar_text(run["text"])
                ):
                    raise RendererError("invalid inline run")
                if not isinstance(run["marks"], list) or any(
                    mark
                    not in {
                        "italic",
                        "bold",
                        "superscript",
                        "subscript",
                        "underline",
                        "small-caps",
                    }
                    for mark in run["marks"]
                ):
                    raise RendererError("invalid inline marks")
            if "".join(run["text"] for run in runs) != item["text"]:
                raise RendererError("inline runs differ from readable text")
        child_types = _CHILD_NODE_TYPES.get(node_type)
        if node_type in {"blockquote", "list-item"} and "children" not in item:
            child_types = None
        if active_nodes is not None:
            active_nodes.add(node_identity)
        try:
            if child_types is None:
                if "children" in item:
                    raise RendererError(f"renderer produced invalid nesting in {label}")
            else:
                children = item.get("children")
                if not isinstance(children, list):
                    raise RendererError(f"renderer produced invalid nesting in {label}")
                if node_type == "json-property" and len(children) != 1:
                    raise RendererError(f"renderer produced invalid nesting in {label}")
                _validate_document_nodes(
                    children,
                    f"{label}[{index}].children",
                    allowed_types=child_types,
                    validated_nodes=validated_nodes,
                    active_nodes=active_nodes,
                )
        finally:
            if active_nodes is not None:
                active_nodes.discard(node_identity)
        if validated_nodes is not None:
            validated_nodes.add(node_identity)
    return value


def _validate_renderer_output(
    value: object, *,
    _on_page_split: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
    _on_list_page: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
    _on_json_page: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
    _on_context_replacement: Callable[[list[dict[str, Any]], dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    base_fields = {"kind", "nodes", "outline", "contexts"}
    finalized_fields = base_fields | {"segments", "_pages"}
    hinted_fields = finalized_fields | {"_hard_break_before"}
    if not isinstance(value, dict) or frozenset(set(value) - {"limitations"}) not in {
        frozenset(base_fields),
        frozenset(finalized_fields),
        frozenset(hinted_fields),
    }:
        raise RendererError(
            "renderer produced output fields that do not match the public contract"
        )
    kind = value["kind"]
    if not isinstance(kind, str) or kind not in PRESENTATION_KINDS:
        raise RendererError("renderer produced an invalid presentation kind")
    validated_nodes: set[int] = set()
    active_nodes: set[int] = set()
    nodes = _validate_document_nodes(
        value["nodes"],
        "document",
        validated_nodes=validated_nodes,
        active_nodes=active_nodes,
    )
    outline = value["outline"]
    contexts = value["contexts"]
    if not isinstance(outline, list):
        raise RendererError("renderer produced an outline that is not an array")
    for item in outline:
        if not isinstance(item, dict) or set(item) != {"location", "label", "level"}:
            raise RendererError("renderer produced an invalid outline item")
        if not is_route_valid_scalar_text(
            item["location"], MAX_STRUCTURE_LOCATION_SCALARS
        ):
            raise RendererError("renderer produced an invalid structure location")
        if not is_route_valid_scalar_text(item["label"], MAX_STRUCTURE_LABEL_SCALARS):
            raise RendererError("renderer produced an invalid structure label")
        if item["label"] != project_visible_text(item["label"]):
            raise RendererError(
                "renderer produced a structure label that is not the canonical whitespace projection"
            )
        if (
            not isinstance(item["level"], int)
            or isinstance(item["level"], bool)
            or item["level"] < 1
        ):
            raise RendererError("renderer produced an invalid structure level")
    if not isinstance(contexts, dict) or any(
        not isinstance(key, str) for key in contexts
    ):
        raise RendererError("renderer produced contexts that are not an object")
    for context in contexts.values():
        if not isinstance(context, dict) or set(context) != {
            "location",
            "label",
            "nodes",
            "text",
        }:
            raise RendererError("renderer produced an invalid structure context")
        if (
            not isinstance(context["location"], str)
            or not isinstance(context["label"], str)
            or not isinstance(context["text"], str)
        ):
            raise RendererError("renderer produced an invalid structure context")
        if context["label"] != project_visible_text(context["label"]):
            raise RendererError(
                "renderer produced a structure context label that is not the canonical whitespace projection"
            )
        _validate_document_nodes(
            context["nodes"],
            "context",
            allowed_types=_CONTEXT_ROOT_NODE_TYPES,
            validated_nodes=validated_nodes,
            active_nodes=active_nodes,
        )
    raw_breaks = value.get("_hard_break_before", [])
    if (
        not isinstance(raw_breaks, list)
        or any(
            not isinstance(item, int) or isinstance(item, bool) for item in raw_breaks
        )
        or raw_breaks != sorted(set(raw_breaks))
        or any(item <= 0 or item >= len(nodes) for item in raw_breaks)
        or (raw_breaks and kind not in {"tei-reader", "pdf-native"})
    ):
        raise RendererError("renderer produced invalid TEI corpus work boundaries")
    finalized = _finalize_structure(
        kind,
        nodes,
        outline,
        contexts,
        hard_break_before=set(raw_breaks),
        _on_page_split=_on_page_split,
        _on_list_page=_on_list_page,
        _on_json_page=_on_json_page,
        _on_context_replacement=_on_context_replacement,
    )
    if "segments" in value and (
        value["segments"] != finalized["segments"]
        or value["_pages"] != finalized["_pages"]
    ):
        raise RendererError(
            "renderer internal pages do not match canonical segmentation"
        )
    if "limitations" in value:
        limits = value["limitations"]
        if (
            not isinstance(limits, list)
            or len(limits) > 33
            or any(not isinstance(item, str) or len(item) > 1000 for item in limits)
        ):
            raise RendererError("invalid presentation limitations")
        finalized["limitations"] = limits
    return finalized


def _finalize_structure(
    kind: str,
    nodes: list[dict[str, Any]],
    outline: list[dict[str, Any]],
    contexts: dict[str, dict[str, Any]],
    *,
    hard_break_before: set[int] | None = None,
    _on_page_split: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
    _on_list_page: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
    _on_json_page: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
    _on_context_replacement: Callable[[list[dict[str, Any]], dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Publish either one coherent selectable structure or an honest no-outline view."""
    locations = [item.get("location") for item in outline]
    if any(
        not is_route_valid_scalar_text(location, MAX_STRUCTURE_LOCATION_SCALARS)
        or location == "start"
        for location in locations
    ):
        raise RendererError("renderer produced an invalid structure location")
    if len(locations) != len(set(locations)):
        raise RendererError("renderer produced duplicate structure locations")
    expected_contexts = {"start", *locations}
    if set(contexts) != expected_contexts:
        raise RendererError("renderer outline and contexts are not one-to-one")

    raw_labels = {item["location"]: item["label"] for item in outline}
    labels = {
        location: project_visible_text(
            _bounded_visible_text(label, MAX_STRUCTURE_LABEL_SCALARS, "Label")
        )
        for location, label in raw_labels.items()
    }
    finalized_outline = [
        {**item, "label": labels[item["location"]]} for item in outline
    ]
    finalized_contexts: dict[str, dict[str, Any]] = {}
    readable_text_cache: dict[int, str] = {}
    for location, context in contexts.items():
        if context.get("location") != location:
            raise RendererError("renderer context location does not match its key")
        label = labels.get(
            location,
            project_visible_text(
                _bounded_visible_text(
                    str(context.get("label", "Start")),
                    MAX_STRUCTURE_LABEL_SCALARS,
                    "Label",
                )
            ),
        )
        if location != "start" and context.get("label") != raw_labels[location]:
            raise RendererError(
                "renderer context label does not match its outline item"
            )
        full_text = context["text"]
        if location != "start" and not is_route_valid_scalar_text(full_text):
            raise RendererError(
                "renderer produced a structure context without readable text"
            )
        context_nodes = context.get("nodes")
        if not isinstance(context_nodes, list):
            raise RendererError("renderer context nodes must be an array")
        if location != "start" and not any(
            _node_contains_location(node, location) for node in context_nodes
        ):
            raise RendererError(
                "renderer context does not contain its advertised location"
            )
        readable_text = _nodes_text(context_nodes, readable_text_cache)
        if readable_text != full_text:
            raise RendererError(
                "renderer context text does not match its readable nodes"
            )
        bounded_text = _bounded_visible_text(
            full_text, MAX_STRUCTURE_CONTEXT_SCALARS, "Context"
        )
        if bounded_text != full_text:
            replacement = _node(
                "preformatted",
                bounded_text,
                **({"location": location} if location != "start" else {}),
            )
            if _on_context_replacement is not None:
                _on_context_replacement(context_nodes, replacement)
            context_nodes = [replacement]
        finalized_contexts[location] = {
            "location": location,
            "label": label,
            "nodes": context_nodes,
            "text": bounded_text,
        }
    # Context validation is complete; page construction has its own bounded text work.
    del readable_text_cache
    return {
        "kind": kind,
        "nodes": nodes,
        "outline": finalized_outline,
        "contexts": finalized_contexts,
        **_build_segments_and_pages(
            nodes,
            finalized_outline,
            hard_break_before=hard_break_before,
            _on_page_split=_on_page_split,
            _on_list_page=_on_list_page,
            _on_json_page=_on_json_page,
        ),
    }


def _node_contains_location(node: dict[str, Any], location: str) -> bool:
    return node.get("location") == location or any(
        _node_contains_location(child, location) for child in node.get("children", [])
    )


_SPLITTABLE_ROOT_TYPES = frozenset({"json-object", "json-array", "list"})
_SPLITTABLE_VISIBLE_LEAF_TYPES = frozenset(
    {"blockquote", "list-item", "list", "paragraph"}
)


def _split_visible_leaf_node(node: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Losslessly page a long ordinary-text leaf at browser-visible spaces.

    Ordinary nodes use ``white-space: normal`` and are already projected to one
    canonical ASCII space between words. Splitting only at one of those spaces
    lets the public pages reconstruct the exact visible row by joining the
    chunks with the same single-space rule. A location-bearing or otherwise
    structured node remains atomic so segmentation cannot duplicate an anchor
    or silently invent a structural relationship.
    """
    text = _node_text(node)
    if (
        len(text) <= MAX_PAGE_SCALARS
        or node.get("type") not in _SPLITTABLE_VISIBLE_LEAF_TYPES
        or node.get("children")
        or node.get("inline")
        or "location" in node
        or text != project_visible_text(text)
    ):
        return None

    chunks: list[str] = []
    remaining = text
    while len(remaining) > MAX_PAGE_SCALARS:
        boundary = remaining.rfind(" ", 0, MAX_PAGE_SCALARS + 1)
        if boundary <= 0:
            return None
        chunks.append(remaining[:boundary])
        remaining = remaining[boundary + 1 :]
    if remaining:
        chunks.append(remaining)
    if len(chunks) < 2 or " ".join(chunks) != text:
        raise RendererError("renderer visible-leaf split lost readable text")
    return [{**node, "text": chunk} for chunk in chunks]


def _segment_locations(units: list[dict[str, Any]]) -> list[str]:
    """Collect the outline locations contained in these units in ONE traversal."""
    found: list[str] = []
    seen: set[str] = set()

    def walk(node: dict[str, Any]) -> None:
        location = node.get("location")
        if isinstance(location, str) and location not in seen:
            seen.add(location)
            found.append(location)
        for child in node.get("children", []):
            if isinstance(child, dict):
                walk(child)

    for unit in units:
        walk(unit)
    return found


def _build_segments_and_pages(
    nodes: list[dict[str, Any]],
    outline: list[dict[str, Any]],
    *,
    hard_break_before: set[int] | None = None,
    _on_page_split: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
    _on_list_page: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
    _on_json_page: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Partition rendered nodes into bounded segments at construction time.

    Splittable JSON roots split at property boundaries (each page wrapped in a
    synthetic container exactly as contexts already are). Canonical ordinary
    text leaves split losslessly at a browser-visible space. Pages also stop
    before their serialized node array exceeds the renderer page budget, which
    keeps table-heavy pages within the service response bound without changing
    table row/cell topology. Genuinely atomic oversize blocks stay single
    segments flagged ``oversize``; their serve-time visible text is SHA-mark
    truncated and flagged ``truncated``.
    """
    outline_locations = [item["location"] for item in outline]
    units: list[dict[str, Any]] = []
    ownership: list[int] = []  # unit index -> top-level node index
    for node_index, node in enumerate(nodes):
        node_text = _node_text(node)
        split_leaf = _split_visible_leaf_node(node)
        if (
            node.get("type") in _SPLITTABLE_ROOT_TYPES
            and (
                len(node_text) > MAX_PAGE_SCALARS
                or _serialized_json_bytes(node) > MAX_PAGE_SERIALIZED_BYTES
            )
            and node.get("children")
        ):
            units.extend(node["children"])
            ownership.extend([node_index] * len(node["children"]))
        elif split_leaf is not None:
            # Report the actual original and fresh fragment at construction,
            # never infer ownership from an equal node or output position.
            if _on_page_split is not None:
                for fragment in split_leaf:
                    _on_page_split(node, fragment)
            units.extend(split_leaf)
            ownership.extend([node_index] * len(split_leaf))
        else:
            units.append(node)
            ownership.append(node_index)
    hard_break_nodes = set(hard_break_before or set())
    for index, node in enumerate(nodes):
        if node.get("type") == "list":
            list_start = (
                index - 1
                if index and nodes[index - 1].get("type") == "heading"
                else index
            )
            # Native division markers precede the visible heading. Keep them
            # on its list page so selecting the division cannot land on prior
            # text or on a page containing only an invisible marker.
            while (
                list_start
                and nodes[list_start - 1].get("type") == "heading"
                and not nodes[list_start - 1].get("text")
                and nodes[list_start - 1].get("location")
            ):
                list_start -= 1
            hard_break_nodes.add(list_start)
            if index + 1 < len(nodes):
                hard_break_nodes.add(index + 1)
    hard_break_units = {
        unit_index
        for unit_index, owner in enumerate(ownership)
        if owner in hard_break_nodes
        and (unit_index == 0 or ownership[unit_index - 1] != owner)
    }
    segments: list[dict[str, Any]] = []
    pages: list[list[dict[str, Any]]] = []
    current_units: list[dict[str, Any]] = []
    current_total = 0
    current_serialized = 0

    def flush() -> None:
        nonlocal current_units, current_total, current_serialized
        if not current_units:
            return
        # Every request serves at most one segment. Count only that segment's
        # visible projection; there is no served separator between pages.
        scalar_count = len(" ".join(_node_text(unit) for unit in current_units))
        entry: dict[str, Any] = {
            "index": len(segments),
            "scalar_count": scalar_count,
            "locations": _segment_locations(current_units),
        }
        if len(" ".join(_node_text(unit) for unit in current_units)) > MAX_PAGE_SCALARS:
            entry["oversize"] = True
            entry["truncated"] = True
        segments.append(entry)
        pages.append(list(current_units))
        current_units = []
        current_total = 0
        current_serialized = 0

    for unit_index, unit in enumerate(units):
        if unit_index in hard_break_units:
            flush()
        unit_size = len(_node_text(unit))
        if unit_size > MAX_PAGE_SCALARS:
            flush()
            current_units = [unit]
            flush()
            continue

        projected_total = current_total + unit_size + (1 if current_units else 0)
        # json.dumps uses a two-character list wrapper and `, ` between items;
        # once a page has an item, adding one more item therefore adds its JSON
        # size plus two bytes. Track this directly instead of repeatedly
        # serializing the growing page while retaining the service's exact UTF-8
        # sizing rules.
        unit_serialized = _serialized_json_bytes(unit)
        projected_serialized = current_serialized + unit_serialized + 2
        if current_units and (
            projected_total > MAX_PAGE_SCALARS
            or projected_serialized > MAX_PAGE_SERIALIZED_BYTES
        ):
            # The joining single space between segments belongs to the partition
            # total, so the boundary check must count it against the running size.
            flush()
            current_units = [unit]
            current_total = unit_size
            current_serialized = unit_serialized + 2
        else:
            current_units.append(unit)
            current_total = projected_total
            current_serialized = projected_serialized
    flush()
    total_scalars = sum(segment["scalar_count"] for segment in segments)
    served_total = sum(
        len(" ".join(_node_text(unit) for unit in page)) for page in pages
    )
    if total_scalars != served_total:
        raise RendererError("renderer segment counts do not match the served pages")
    covered = {location for segment in segments for location in segment["locations"]}
    if not covered <= set(outline_locations):
        raise RendererError("renderer segment locations escape the published outline")
    return {"segments": segments, "_pages": _wrapped_pages(
        pages, nodes, _on_list_page=_on_list_page, _on_json_page=_on_json_page)}


def _wrapped_pages(
    pages: list[list[dict[str, Any]]],
    nodes: list[dict[str, Any]],
    *,
    _on_list_page: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
    _on_json_page: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
) -> list[list[dict[str, Any]]]:
    """Wrap split property pages in a synthetic container root like render_json contexts."""
    wrapped: list[list[dict[str, Any]]] = []
    list_owners = {
        id(child): (parent, offset)
        for parent in nodes
        if parent.get("type") == "list"
        for offset, child in enumerate(parent.get("children", []))
    }
    for page in pages:
        if any(id(unit) in list_owners for unit in page):
            result = []
            constructed_groups = []
            active_parent = None
            for unit in page:
                owner = list_owners.get(id(unit))
                if owner is None:
                    result.append(unit)
                    active_parent = None
                    continue
                parent, offset = owner
                if active_parent is not parent:
                    group = {**parent, "children": []}
                    if parent.get("ordered"):
                        group["start"] = parent.get("start", 1) + offset
                    result.append(group)
                    if _on_list_page is not None:
                        constructed_groups.append((parent, group))
                    active_parent = parent
                result[-1]["children"].append(unit)
            # Observe each completed wrapper, after its last child is added.
            # Keep the actual construction parent; never recover it by value.
            if _on_list_page is not None:
                for parent, group in constructed_groups:
                    _on_list_page(parent, group)
            wrapped.append(result)
            continue
        if page and all(unit.get("type") == "json-property" for unit in page):
            kind_node = "json-object"
            summary = (
                f"Object with {len(page)} fields"
                if len(page) != 1
                else "Object with 1 field"
            )
            first = page[0]
            parent = next(
                (
                    n
                    for n in nodes
                    if any(child is first for child in n.get("children", []))
                ),
                None,
            )
            if parent is not None and parent.get("type") == "json-array":
                kind_node = "json-array"
                summary = (
                    f"Array with {len(page)} items"
                    if len(page) != 1
                    else "Array with 1 item"
                )
            wrapper = _node(kind_node, summary, children=list(page))
            if _on_json_page is not None:
                # A synthetic page must have one actual construction parent.
                # Default rendering stays unchanged for unsupported ownership.
                for unit in page:
                    owners = [n for n in nodes if any(
                        child is unit for child in n.get("children", []))]
                    if (len(owners) != 1 or owners[0] is not parent
                            or parent.get("type") not in {"json-object", "json-array"}):
                        raise RendererError("JSON page lacks unique construction parent")
                _on_json_page(parent, wrapper)
            wrapped.append([wrapper])
        else:
            wrapped.append(list(page))
    return wrapped


def _heading_contexts(
    nodes: list[dict[str, Any]],
    outline: list[dict[str, Any]],
    *,
    include_nested: bool = False,
) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {
        "start": {
            "location": "start",
            "label": "Start",
            "nodes": nodes,
            "text": _nodes_text(nodes),
        }
    }
    first_location_index: dict[str, int] = {}
    outline_locations = {item["location"] for item in outline}
    for index, node in enumerate(nodes):
        stack = [node]
        while stack:
            current = stack.pop()
            location = current.get("location")
            if isinstance(location, str) and location not in first_location_index:
                first_location_index[location] = index
            if include_nested:
                stack.extend(reversed(current.get("children", [])))
    for item in outline:
        try:
            start = first_location_index[item["location"]]
        except KeyError:
            raise StopIteration from None
        paragraph_anchor = nodes[start].get("type") == "paragraph"
        structural_anchor = nodes[start].get("type") == "heading" and not nodes[
            start
        ].get("text")
        end = len(nodes)
        for index in range(start + 1, len(nodes)):
            node = nodes[index]
            if (
                paragraph_anchor
                and node.get("type") != "heading"
                and node.get("location") in outline_locations
            ):
                end = index
                break
            if node.get("type") != "heading":
                continue
            if not node.get("text"):
                boundary = int(node.get("level", 1)) <= int(item["level"])
            else:
                boundary = not structural_anchor and int(node.get("level", 1)) <= int(
                    item["level"]
                )
            if boundary:
                end = index
                break
        selected = nodes[start:end]
        contexts[item["location"]] = {
            "location": item["location"],
            "label": item["label"],
            "nodes": selected,
            "text": _nodes_text(selected),
        }
    return contexts


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


_TEI_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_ENTITY_DECLARATION = re.compile(r"<!ENTITY", re.IGNORECASE)
_INTERNAL_DTD_SUBSET = re.compile(r"<!DOCTYPE[^>]*\[", re.IGNORECASE | re.DOTALL)
_TEI_SUPPRESSED = frozenset({"teiHeader"})
_TEI_TEXT_BLOCKS = frozenset(
    {
        "p",
        "ab",
        "l",
        "item",
        "speaker",
        "stage",
        "note",
        "quote",
        "cit",
        "label",
        "figDesc",
    }
)
_TEI_DICTIONARY_ENTRY_TYPES = frozenset({"entry", "entryFree"})
_TEI_LEAF_HANDLED = frozenset(
    {*_TEI_DICTIONARY_ENTRY_TYPES, "head", "table", *_TEI_TEXT_BLOCKS}
)
