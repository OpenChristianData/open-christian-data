"""Declarative role and evidence profile for the clean-text ledger v2 contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DISPOSITIONS = ("delivered", "normalized", "structural", "dropped", "empty")
TARGET_FIELDS = ("text", "argument", "title_path", "speeches")
PROFILE_ID = "hf-clean-text-v2"
PROFILE_VERSION = "2.0.0"
DROP_DIV_TYPES = frozenset(
    {"title", "titlepage", "imprint", "halftitlepage", "colophon", "copyright-page"}
)
DROP_ELEMENTS = frozenset({"note", "pb"})
STRUCTURAL_ELEMENTS = frozenset(
    {
        "text",
        "body",
        "front",
        "back",
        "div",
        "list",
        "item",
        "table",
        "row",
        "cell",
        "lb",
    }
)
NORMALIZED_ELEMENTS = frozenset(
    {
        "ref",
        "hi",
        "emph",
        "foreign",
        "seg",
        "abbr",
        "title",
        "q",
        "bibl",
        "name",
    }
)
DELIVERED_ELEMENTS = frozenset(
    {
        "sp",
        "lg",
        "l",
        "quote",
        "label",
        "speaker",
        "p",
        "head",
        "argument",
        "trailer",
        "date",
    }
)


@dataclass(frozen=True)
class ElementRule:
    """One explicit projection-profile entry for a TEI local name."""

    role: str
    reason_code: str | None = None
    destination: str | None = None


@dataclass(frozen=True)
class TargetFieldDefinition:
    """Evidence contract for one output field."""

    field: str
    value_kind: str
    requires_item_index: bool = False


TARGET_FIELD_DEFINITIONS: dict[str, TargetFieldDefinition] = {
    "text": TargetFieldDefinition("text", "string"),
    "argument": TargetFieldDefinition("argument", "string"),
    "title_path": TargetFieldDefinition("title_path", "array-item", True),
    "speeches": TargetFieldDefinition("speeches", "structured-array-item", True),
}


ROLE_REGISTRY: dict[str, ElementRule] = {
    "text": ElementRule("structural", "structural.text"),
    "body": ElementRule("structural", "structural.body"),
    "front": ElementRule("structural", "structural.front"),
    "back": ElementRule("structural", "structural.back"),
    "div": ElementRule("structural", "structural.div"),
    "ref": ElementRule("normalized", "normalize.ref.annotation-removed"),
    "hi": ElementRule("normalized", "normalize.inline.markup-removed"),
    "emph": ElementRule("normalized", "normalize.inline.markup-removed"),
    "foreign": ElementRule("normalized", "normalize.inline.markup-removed"),
    "seg": ElementRule("normalized", "normalize.inline.markup-removed"),
    "abbr": ElementRule("normalized", "normalize.inline.markup-removed"),
    "title": ElementRule("normalized", "normalize.inline.markup-removed"),
    "q": ElementRule("normalized", "normalize.inline.markup-removed"),
    "list": ElementRule("structural", "structural.list"),
    "item": ElementRule("structural", "structural.item"),
    "table": ElementRule("structural", "structural.table"),
    "row": ElementRule("structural", "structural.row"),
    "cell": ElementRule("structural", "structural.cell"),
    "bibl": ElementRule("normalized", "normalize.inline.markup-removed"),
    "name": ElementRule("normalized", "normalize.inline.markup-removed"),
    "lb": ElementRule("structural", "structural.lb"),
    "sp": ElementRule("delivered", destination="text"),
    "lg": ElementRule("delivered", destination="text"),
    "l": ElementRule("delivered", destination="text"),
    "quote": ElementRule("delivered", destination="text"),
    "label": ElementRule("delivered", destination="text"),
    "speaker": ElementRule("delivered", destination="text"),
    "p": ElementRule("delivered", destination="text"),
    "head": ElementRule("delivered", destination="title_path"),
    "argument": ElementRule("delivered", destination="argument"),
    "trailer": ElementRule("delivered", destination="text"),
    "date": ElementRule("delivered", destination="text"),
    "note": ElementRule("dropped", "drop.element.note"),
    "pb": ElementRule("dropped", "drop.element.pb"),
}

REASON_CODES = frozenset(
    rule.reason_code
    for rule in ROLE_REGISTRY.values()
    if rule.reason_code is not None
) | frozenset({"drop.div.type", "drop.ancestor.note", "drop.ancestor.pb", "drop.ancestor.div-type", "empty.text-bearing"})


def rule_for(local_name: str) -> ElementRule | None:
    """Return the explicit rule for a local TEI element name, if admitted."""

    return ROLE_REGISTRY.get(local_name)


def _local(node: Any) -> str:
    from lxml import etree

    return etree.QName(node).localname


def dropped_ancestor(node: Any) -> Any | None:
    """Return the first dropped node in self-or-ancestors, or ``None``."""

    current = node
    while current is not None:
        local = _local(current)
        if local in DROP_ELEMENTS:
            return current
        if local == "div" and current.get("type") in DROP_DIV_TYPES:
            return current
        current = current.getparent()
    return None


def drop_reason(node: Any) -> str | None:
    dropped = dropped_ancestor(node)
    if dropped is None:
        return None
    local = _local(dropped)
    if local == "note":
        return "drop.element.note" if dropped is node else "drop.ancestor.note"
    if local == "pb":
        return "drop.element.pb" if dropped is node else "drop.ancestor.pb"
    return "drop.div.type" if dropped is node else "drop.ancestor.div-type"


def destination_for(node: Any) -> str | None:
    """Resolve the target field from the declarative rule and TEI ancestry."""

    local = _local(node)
    rule = rule_for(local)
    if rule is None:
        return None
    if local == "head":
        return "title_path"
    current = node.getparent()
    while current is not None:
        if _local(current) == "head":
            return "title_path"
        if _local(current) == "argument":
            return "argument"
        current = current.getparent()
    return rule.destination or "text"


def classify_base(node: Any) -> str | None:
    """Classify by profile identity before canonical-text emptiness is applied."""

    dropped = dropped_ancestor(node)
    if dropped is not None:
        return "dropped"
    local = _local(node)
    if local == "div" and node.get("type") in DROP_DIV_TYPES:
        return "dropped"
    rule = rule_for(local)
    return rule.role if rule is not None else None


def structural_reason(local_name: str) -> str | None:
    rule = rule_for(local_name)
    return rule.reason_code if rule is not None and rule.role == "structural" else None
