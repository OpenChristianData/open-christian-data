"""Validation helpers for source-bound TEI profile extensions.

The controlled registry is deliberately small.  An extension record can add a
source or category distinction for a selected fixture, but it never changes
the common profile merely because its identifier appears in a package.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_EXTENSION_ID = re.compile(r"^ext-[a-z0-9]+(?:-[a-z0-9]+)+$")
_OWNER = re.compile(r"^(?:category|source-family):[a-z0-9]+(?:-[a-z0-9]+)*$")
_ATTRIBUTE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]*$")
_RECORD_KEYS = frozenset(
    {
        "extension_id",
        "status",
        "owner",
        "meaning",
        "not_meaning",
        "representation",
        "scope",
        "real_examples",
        "authority_refs",
        "validation_rule_ids",
        "projection",
        "independent_checks",
        "decision",
    }
)
_REPRESENTATION_KEYS = frozenset(
    {
        "path",
        "required_attributes",
        "optional_attributes",
        "required_children",
        "order",
        "controlled_values",
    }
)
_EXAMPLE_KEYS = frozenset(
    {"work", "edition", "retained_source", "fixture", "observed_structure"}
)
_RETAINED_SOURCE_KEYS = frozenset({"identity", "path", "location", "sha256"})
_FIXTURE_KEYS = frozenset({"id", "path", "sha256"})
_PROJECTION_KEYS = frozenset(
    {
        "disposition",
        "reason",
        "target",
        "row_boundary",
        "locator",
        "order",
        "loss_receipt",
        "observed_enforcement",
        "projector_readiness",
    }
)
_DECISION_KEYS = frozenset({"status", "reference", "version"})
_DISPOSITIONS = frozenset({"projected", "internal-only", "unsupported-visible"})
_SUPPORTED_ORDER_RULES = frozenset({"quote-before-scripture-reference"})


def _profile_error(message: str) -> ValueError:
    # Import lazily so profile.py can use the extension validator without an
    # import cycle while it defines ProfileError.
    from .profile import ProfileError

    return ProfileError(message)


def _fail(context: str, message: str) -> None:
    raise _profile_error(f"{context}: {message}")


def _exact_keys(value: Mapping[str, Any], expected: frozenset[str], context: str) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if extra:
            details.append(f"unrecognized {', '.join(extra)}")
        _fail(context, "; ".join(details))


def _string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(context, "must be a nonempty string")
    return value


def _unique_strings(value: Any, context: str) -> list[str]:
    if not isinstance(value, list) or not value:
        _fail(context, "must be a nonempty array")
    result = [_string(item, f"{context}[{index}]") for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        _fail(context, "contains duplicate values")
    return result


def _optional_strings(value: Any, context: str) -> list[str]:
    if not isinstance(value, list):
        _fail(context, "must be an array")
    result = [_string(item, f"{context}[{index}]") for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        _fail(context, "contains duplicate values")
    return result


def _sha256(value: Any, context: str) -> str:
    text = _string(value, context)
    if not _SHA256.fullmatch(text):
        _fail(context, "must be a lowercase SHA-256 digest")
    return text


def _logical_path(value: Any, context: str) -> str:
    text = _string(value, context)
    if "\\" in text or ":" in text or "\x00" in text:
        _fail(context, "must use a logical POSIX path")
    path = PurePosixPath(text)
    if (
        path.is_absolute()
        or path.as_posix() != text
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        _fail(context, "must be a normalized relative POSIX path")
    return text


def _validate_attributes(value: Any, context: str) -> dict[str, str]:
    if not isinstance(value, dict):
        _fail(context, "must be an object")
    result: dict[str, str] = {}
    for name, raw in value.items():
        if not isinstance(name, str) or not _ATTRIBUTE.fullmatch(name):
            _fail(f"{context}.{name}", "has an invalid attribute name")
        result[name] = _string(raw, f"{context}.{name}")
    return result


def _validate_controlled_values(value: Any, context: str) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        _fail(context, "must be an object")
    result: dict[str, list[str]] = {}
    for name, raw in value.items():
        if not isinstance(name, str) or not name.strip():
            _fail(f"{context}.{name}", "must have a nonempty context name")
        result[name] = _unique_strings(raw, f"{context}.{name}")
    return result


def _validate_real_example(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(context, "must be an object")
    _exact_keys(value, _EXAMPLE_KEYS, context)
    work = _string(value["work"], f"{context}.work")
    edition = _string(value["edition"], f"{context}.edition")
    observed = _string(value["observed_structure"], f"{context}.observed_structure")

    source = value["retained_source"]
    if not isinstance(source, dict):
        _fail(f"{context}.retained_source", "must be an object")
    _exact_keys(source, _RETAINED_SOURCE_KEYS, f"{context}.retained_source")
    retained_source = {
        "identity": _string(source["identity"], f"{context}.retained_source.identity"),
        "path": _logical_path(source["path"], f"{context}.retained_source.path"),
        "location": _string(source["location"], f"{context}.retained_source.location"),
        "sha256": _sha256(source["sha256"], f"{context}.retained_source.sha256"),
    }

    fixture = value["fixture"]
    if not isinstance(fixture, dict):
        _fail(f"{context}.fixture", "must be an object")
    _exact_keys(fixture, _FIXTURE_KEYS, f"{context}.fixture")
    bound_fixture = {
        "id": _string(fixture["id"], f"{context}.fixture.id"),
        "path": _logical_path(fixture["path"], f"{context}.fixture.path"),
        "sha256": _sha256(fixture["sha256"], f"{context}.fixture.sha256"),
    }
    return {
        "work": work,
        "edition": edition,
        "retained_source": retained_source,
        "fixture": bound_fixture,
        "observed_structure": observed,
    }


def validate_extension_record(record: Any, *, context: str = "extension") -> dict[str, Any]:
    """Validate and copy one complete provisional extension record."""

    if not isinstance(record, dict):
        _fail(context, "must be an object")
    _exact_keys(record, _RECORD_KEYS, context)

    extension_id = _string(record["extension_id"], f"{context}.extension_id")
    if not _EXTENSION_ID.fullmatch(extension_id):
        _fail(f"{context}.extension_id", "must use ext-owner-concept lower-kebab form")
    status = _string(record["status"], f"{context}.status")
    if status != "provisional":
        _fail(f"{context}.status", "only provisional records are loadable before adoption")
    owner = _string(record["owner"], f"{context}.owner")
    if not _OWNER.fullmatch(owner):
        _fail(f"{context}.owner", "must identify a durable category or source-family owner")
    meaning = _string(record["meaning"], f"{context}.meaning")
    not_meaning = _string(record["not_meaning"], f"{context}.not_meaning")
    if meaning == not_meaning:
        _fail(context, "meaning and not_meaning must define different boundaries")

    representation = record["representation"]
    if not isinstance(representation, dict):
        _fail(f"{context}.representation", "must be an object")
    required_representation = frozenset(
        {"path", "required_attributes", "optional_attributes", "required_children", "order"}
    )
    representation_keys = frozenset(representation)
    extra_representation = representation_keys - _REPRESENTATION_KEYS
    if extra_representation:
        _fail(
            f"{context}.representation",
            f"unrecognized {', '.join(sorted(extra_representation))}",
        )
    if set(representation) & required_representation != required_representation:
        _fail(f"{context}.representation", "must declare path, attributes, children, and order")
    path = _string(representation["path"], f"{context}.representation.path")
    if "\\" in path or "\x00" in path or not path.startswith("text/"):
        _fail(f"{context}.representation.path", "must be a logical TEI text-relative path")
    required_attributes = _validate_attributes(
        representation["required_attributes"], f"{context}.representation.required_attributes"
    )
    optional_attributes = _optional_strings(
        representation["optional_attributes"], f"{context}.representation.optional_attributes"
    )
    if set(required_attributes) & set(optional_attributes):
        _fail(f"{context}.representation", "an attribute cannot be required and optional")
    required_children = _optional_strings(
        representation["required_children"], f"{context}.representation.required_children"
    )
    order = _optional_strings(representation["order"], f"{context}.representation.order")
    unsupported_order = sorted(set(order) - _SUPPORTED_ORDER_RULES)
    if unsupported_order:
        _fail(
            f"{context}.representation.order",
            "unsupported order constraint(s): " + ", ".join(unsupported_order),
        )
    for child in required_children:
        # Validate selectors while loading the package so a malformed child
        # declaration cannot survive until a caller selects the extension.
        _child_selector(child)
    controlled_values = _validate_controlled_values(
        representation.get("controlled_values", {}),
        f"{context}.representation.controlled_values",
    )
    for controlled_context in controlled_values:
        if re.fullmatch(
            r"(?:[A-Za-z_][A-Za-z0-9_.-]*/)?@?[A-Za-z_][A-Za-z0-9_.:-]*",
            controlled_context,
        ) is None:
            _fail(
                f"{context}.representation.controlled_values.{controlled_context}",
                "must identify an attribute context",
            )
    normalized_representation = {
        "path": path,
        "required_attributes": required_attributes,
        "optional_attributes": optional_attributes,
        "required_children": required_children,
        "order": order,
        "controlled_values": controlled_values,
    }
    # Validate the complete text-relative selector now.  The renderer keeps
    # its ancestor chain rather than silently widening a source-bound rule to
    # every element with the same terminal name.
    parse_extension_path(
        {"extension_id": extension_id, "representation": {"path": path}}
    )

    scope = _unique_strings(record["scope"], f"{context}.scope")
    examples = record["real_examples"]
    if not isinstance(examples, list) or not examples:
        _fail(f"{context}.real_examples", "must contain a bound real example")
    real_examples = [
        _validate_real_example(item, f"{context}.real_examples[{index}]")
        for index, item in enumerate(examples)
    ]
    authority_refs = _unique_strings(record["authority_refs"], f"{context}.authority_refs")
    validation_rule_ids = _unique_strings(
        record["validation_rule_ids"], f"{context}.validation_rule_ids"
    )
    for index, rule_id in enumerate(validation_rule_ids):
        if not _IDENTIFIER.fullmatch(rule_id):
            _fail(
                f"{context}.validation_rule_ids[{index}]",
                "must use lower-kebab rule identifiers",
            )
        if rule_id.startswith("ocd-") or rule_id == f"{extension_id}-witness":
            _fail(f"{context}.validation_rule_ids[{index}]", "collides with a reserved validator rule")
    expected_rule_count = len(required_attributes) + len(required_children) + len(order) + len(controlled_values)
    if len(validation_rule_ids) != expected_rule_count:
        _fail(f"{context}.validation_rule_ids", "must name exactly the executable declared constraints")

    projection = record["projection"]
    if not isinstance(projection, dict) or not projection:
        _fail(f"{context}.projection", "must declare every affected projector")
    normalized_projection: dict[str, dict[str, str]] = {}
    for projector, raw in projection.items():
        projector_name = _string(projector, f"{context}.projection key")
        if not isinstance(raw, dict):
            _fail(f"{context}.projection.{projector_name}", "must be an object")
        if not set(raw) <= _PROJECTION_KEYS or "disposition" not in raw:
            _fail(f"{context}.projection.{projector_name}", "contains unknown fields or lacks disposition")
        disposition = _string(raw["disposition"], f"{context}.projection.{projector_name}.disposition")
        if disposition not in _DISPOSITIONS:
            _fail(f"{context}.projection.{projector_name}.disposition", "is not an allowed disposition")
        if disposition in {"internal-only", "unsupported-visible"} and not isinstance(raw.get("reason"), str):
            _fail(f"{context}.projection.{projector_name}", "requires a reason for nonprojection")
        if disposition == "projected":
            for key in ("target", "row_boundary", "locator", "order", "loss_receipt"):
                if not isinstance(raw.get(key), str) or not raw[key].strip():
                    _fail(f"{context}.projection.{projector_name}", f"projected disposition requires {key}")
        for key in ("observed_enforcement", "projector_readiness"):
            if not isinstance(raw.get(key), str) or not raw[key].strip():
                _fail(f"{context}.projection.{projector_name}", f"requires {key}")
        for key, value in raw.items():
            if not isinstance(value, str) or not value.strip():
                _fail(f"{context}.projection.{projector_name}.{key}", "must be a nonempty string")
        normalized_projection[projector_name] = {
            key: str(value) for key, value in raw.items()
        }

    decision = record["decision"]
    if not isinstance(decision, dict):
        _fail(f"{context}.decision", "must be an object")
    _exact_keys(decision, _DECISION_KEYS, f"{context}.decision")
    if _string(decision["status"], f"{context}.decision.status") != "provisional":
        _fail(f"{context}.decision.status", "must remain provisional before explicit adoption")
    normalized_decision = {
        "status": decision["status"],
        "reference": _string(decision["reference"], f"{context}.decision.reference"),
        "version": _string(decision["version"], f"{context}.decision.version"),
    }
    independent_checks = _unique_strings(
        record["independent_checks"], f"{context}.independent_checks"
    )

    return {
        "extension_id": extension_id,
        "status": status,
        "owner": owner,
        "meaning": meaning,
        "not_meaning": not_meaning,
        "representation": normalized_representation,
        "scope": scope,
        "real_examples": real_examples,
        "authority_refs": authority_refs,
        "validation_rule_ids": validation_rule_ids,
        "projection": normalized_projection,
        "independent_checks": independent_checks,
        "decision": normalized_decision,
    }


def validate_extension_records(records: Any, *, context: str = "extensions") -> list[dict[str, Any]]:
    """Validate a complete extension array and reject duplicate identifiers."""

    if not isinstance(records, list):
        _fail(context, "must be an array")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    rule_ids: set[str] = set()
    for index, record in enumerate(records):
        validated = validate_extension_record(record, context=f"{context}[{index}]")
        extension_id = validated["extension_id"]
        if extension_id in seen:
            _fail(context, f"duplicate extension_id {extension_id!r}")
        seen.add(extension_id)
        for rule_id in validated["validation_rule_ids"]:
            if rule_id in rule_ids:
                _fail(context, f"duplicate validation rule id {rule_id!r}")
            rule_ids.add(rule_id)
        result.append(validated)
    return result


def select_extensions(records: Sequence[Mapping[str, Any]], extension_ids: Iterable[str]) -> list[dict[str, Any]]:
    """Return fully validated records for an explicit, ordered selection."""

    selected_ids = list(extension_ids)
    if len(selected_ids) != len(set(selected_ids)):
        _fail("extension_ids", "contains duplicates")
    validated_records = validate_extension_records(list(records), context="profile.extensions")
    by_id = {record["extension_id"]: record for record in validated_records}
    missing = [extension_id for extension_id in selected_ids if extension_id not in by_id]
    if missing:
        _fail("extension_ids", f"unknown extension_id(s): {', '.join(missing)}")
    return [validate_extension_record(by_id[extension_id], context=f"extension {extension_id}") for extension_id in selected_ids]


@dataclass(frozen=True)
class ExtensionPath:
    """The small path subset needed to generate selected Schematron rules."""

    extension_id: str
    context: str
    element: str
    predicate: str | None
    terminal_context: str


def parse_extension_path(record: Mapping[str, Any]) -> ExtensionPath:
    """Parse a bounded text-relative selector and retain its ancestor scope."""

    path = record["representation"]["path"]
    path_context = f"extension {record['extension_id']}.representation.path"
    if not isinstance(path, str) or not path.startswith("text/"):
        _fail(path_context, "must start with text/")
    if "\\" in path or "\x00" in path:
        _fail(path_context, "contains unsupported path characters")

    parts = path.split("/")
    empty_indexes = [index for index, part in enumerate(parts) if part == ""]
    if len(empty_indexes) > 1:
        _fail(path_context, "must use at most one descendant separator")
    if empty_indexes and empty_indexes[0] == len(parts) - 1:
        _fail(path_context, "cannot end with a descendant separator")
    if any(part in {".", ".."} for part in parts):
        _fail(path_context, "must not contain dot path segments")

    element_pattern = r"(?:[A-Za-z_][A-Za-z0-9_.-]*|\*)"
    if empty_indexes:
        separator = empty_indexes[0]
        if len(parts) != separator + 2:
            _fail(path_context, "must contain one terminal selector after the descendant separator")
        ancestors = parts[1:separator]
        terminal = parts[separator + 1]
        axis = "//"
    else:
        ancestors = parts[1:-1]
        terminal = parts[-1]
        axis = "/"
    if any(re.fullmatch(element_pattern, ancestor) is None for ancestor in ancestors):
        _fail(path_context, "contains an unsupported ancestor selector")
    if not terminal:
        _fail(path_context, "must contain a terminal selector")

    match = re.fullmatch(r"([A-Za-z_*][A-Za-z0-9_.-]*)(?:\[(.+)\])?", terminal)
    if match is None:
        _fail(path_context, "has an unsupported terminal selector")
    element, predicate = match.groups()
    terminal_context = "tei:*" if element == "*" else f"tei:{element}"
    if predicate:
        # The registry stores a TEI-relative predicate. Only attribute tests
        # are admitted here; source-specific XPath remains outside this
        # common profile and must be handled by the source oracle.
        if not re.fullmatch(r"@([A-Za-z_][A-Za-z0-9_.:-]*)(?:\s*=\s*(['\"])(.*?)\2)?", predicate.strip()):
            _fail(path_context, "contains an unsupported predicate")
        predicate = predicate.strip()
        terminal_context += f"[{predicate}]"

    base = "/tei:TEI/tei:text"
    if ancestors:
        base += "/" + "/".join(f"tei:{ancestor}" for ancestor in ancestors)
    base += axis
    context = base + terminal_context
    return ExtensionPath(record["extension_id"], context, element, predicate, terminal_context)


def extension_attribute_allowances(records: Sequence[Mapping[str, Any]]) -> list[tuple[str, str, str | None]]:
    """Return selected custom attribute allowances for common-rule generation."""

    allowances: list[tuple[str, str, str | None]] = []
    for record in records:
        parsed = parse_extension_path(record)
        attributes = record["representation"]["required_attributes"]
        for name, value in attributes.items():
            concrete = value if re.fullmatch(r"[A-Za-z0-9]+(?:[-:.][A-Za-z0-9]+)*", value) else None
            allowances.append((parsed.element, name, concrete))
        for context_name, values in record["representation"]["controlled_values"].items():
            if "/@" not in context_name:
                continue
            _, attribute = context_name.rsplit("/", 1)
            for value in values:
                allowances.append((parsed.element, attribute, value))
    return allowances


def extension_rule_specs(records: Sequence[Mapping[str, Any]]) -> list[tuple[str, str, str, str]]:
    """Return ``(rule_id, context, test, message)`` assertion specifications."""

    specs: list[tuple[str, str, str, str]] = []
    for record in records:
        parsed = parse_extension_path(record)
        rule_ids = list(record["validation_rule_ids"])
        rule_index = 0
        for name, value in record["representation"]["required_attributes"].items():
            rule_id = rule_ids[rule_index] if rule_index < len(rule_ids) else f"{record['extension_id']}-attribute-{name}"
            rule_index += 1
            if re.fullmatch(r"[A-Za-z0-9]+(?:[-:.][A-Za-z0-9]+)*", value):
                test = f"@{name} = {xpath_literal(value)}"
                message = f"[{rule_id}] {record['extension_id']} requires @{name}={value!r} at its declared TEI placement."
            else:
                test = f"@{name}"
                message = (
                    f"[{rule_id}] {record['extension_id']} requires @{name} at its declared TEI placement; "
                    "the descriptive constraint is not interpreted by the common renderer."
                )
            specs.append(
                (
                    rule_id,
                    parsed.context,
                    test,
                    message,
                )
            )
        for child_index, child in enumerate(record["representation"]["required_children"], start=1):
            rule_id = rule_ids[rule_index] if rule_index < len(rule_ids) else f"{record['extension_id']}-child-{child_index}"
            rule_index += 1
            child_test = _child_selector(child)
            specs.append(
                (
                    rule_id,
                    parsed.context,
                    f"count({child_test}) >= 1",
                    f"[{rule_id}] {record['extension_id']} requires child {child}.",
                )
            )
    return specs


def extension_order_specs(records: Sequence[Mapping[str, Any]]) -> list[tuple[str, str, str, str]]:
    """Return executable order assertions for the supported order subset.

    Source-member order remains the responsibility of the bound fixture/source
    accounting layer.  This helper only emits XML-local order constraints that
    have a precise, deterministic interpretation.
    """

    specs: list[tuple[str, str, str, str]] = []
    for record in records:
        parsed = parse_extension_path(record)
        rule_ids = list(record["validation_rule_ids"])
        rule_index = len(record["representation"].get("required_attributes", {})) + len(
            record["representation"].get("required_children", [])
        )
        for order in record["representation"].get("order", []):
            if order == "quote-before-scripture-reference":
                rule_id = (
                    rule_ids[rule_index]
                    if rule_index < len(rule_ids)
                    else f"{record['extension_id']}-order-quote-before-scripture-reference"
                )
                rule_index += 1
                test = (
                    "count(.//tei:ref[@type='scripture']"
                    "/ancestor::tei:quote[1]/*"
                    "[self::tei:ref or .//tei:ref[@type='scripture']][1]"
                    "/preceding-sibling::*) > 0"
                )
                message = (
                    f"[{rule_id}] {record['extension_id']} requires quoted content before "
                    "the nested scripture reference."
                )
                specs.append((rule_id, parsed.context, test, message))
            else:
                # validate_extension_record normally catches this. Keep the
                # renderer fail-closed if a caller supplies an unvalidated
                # in-memory record.
                _fail(
                    f"extension {record['extension_id']}.representation.order",
                    f"unsupported order constraint {order!r}",
                )
    return specs


def xpath_literal(value: str) -> str:
    """Return an XPath 1.0 string literal without unsafe interpolation."""

    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    return "concat(" + ", \"'\", ".join(xpath_literal(part) for part in parts) + ")"


def _child_selector(value: str) -> str:
    match = re.fullmatch(
        r"(?:(descendant)::)?([A-Za-z_*][A-Za-z0-9_.-]*)(?:\[(.+)\])?", value
    )
    if match is None:
        _fail("extension representation.required_children", f"unsupported child selector {value!r}")
    axis, element, predicate = match.groups()
    selector = f"{axis + '::' if axis else ''}tei:{element}"
    if predicate:
        if not re.fullmatch(r"@([A-Za-z_][A-Za-z0-9_.:-]*)(?:\s*=\s*(['\"])(.*?)\2)?", predicate.strip()):
            _fail("extension representation.required_children", f"unsupported child predicate {predicate!r}")
        selector += f"[{predicate.strip()}]"
    return selector
