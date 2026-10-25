"""Strict loading and deterministic rendering for the provisional TEI profile.

The profile package is the authority for common controlled values.  Its JSON
members are deliberately closed and hash-bound; a Schematron file that is
hand-edited or generated from a different package is not loadable.  Provisional
extensions are similarly inert unless a caller selects a complete,
source-bound record explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterable, Mapping
import xml.etree.ElementTree as ET

from .extensions import (
    extension_order_specs,
    extension_rule_specs,
    parse_extension_path,
    select_extensions,
    validate_extension_records,
)


TEI_NS = "http://www.tei-c.org/ns/1.0"
SCH_NS = "http://purl.oclc.org/dsdl/schematron"
XML_NS = "http://www.w3.org/XML/1998/namespace"

_LEGACY_REGISTRY_SCHEMA = "ocd-tei-profile-registry-package-provisional-0.1"
_LEGACY_CONTROLLED_SCHEMA = "ocd-tei-controlled-values-provisional-0.1"
_LEGACY_EXTENSIONS_SCHEMA = "ocd-tei-extension-records-provisional-0.1"
_V02_REGISTRY_SCHEMA = "ocd-tei-profile-registry-package-provisional-0.2"
_V02_CONTROLLED_SCHEMA = "ocd-tei-controlled-values-provisional-0.2"
_V02_EXTENSIONS_SCHEMA = "ocd-tei-extension-records-provisional-0.2"
_REGISTRY_SCHEMA = "ocd-tei-profile-registry-package-provisional-0.3"
_CONTROLLED_SCHEMA = "ocd-tei-controlled-values-provisional-0.3"
_EXTENSIONS_SCHEMA = "ocd-tei-extension-records-provisional-0.3"
_PACKAGE_ID = "ocd-tei-profile-registry-provisional"
_MANIFEST_NAME = "profile-registry.json"
_MEMBER_NAMES = frozenset(
    {"profile-registry.json", "controlled-values.json", "extensions.json", "common-rules.sch"}
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LOWER_KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_LEGACY_CONTEXT_ORDER = (
    "div/@type",
    "note/@place",
    "ref/@type",
    "list/@type",
    "hi/@rend",
    "idno/@type",
)
_CONTEXT_ORDER = _LEGACY_CONTEXT_ORDER + ("head/@type",)
_CONTEXT_RULES = {
    "div/@type": ("tei:div[@type]", "type", "division type"),
    "note/@place": ("tei:note[@place]", "place", "note place"),
    "ref/@type": ("tei:ref[@type]", "type", "reference type"),
    "list/@type": ("tei:list[@type]", "type", "list type"),
    "hi/@rend": ("tei:hi[@rend]", "rend", "highlight rendition"),
    "idno/@type": ("tei:idno[@type]", "type", "identifier type"),
    "head/@type": ("tei:head[@type]", "type", "heading type"),
}


@dataclass(frozen=True)
class _ProfileSpec:
    registry_schema: str
    controlled_schema: str
    extensions_schema: str
    context_order: tuple[str, ...]
    dictionary_entry_rules: bool
    undeclared_attribute_cases: tuple[tuple[str, str, str, str], ...] = ()


_PROFILE_SPECS = {
    _LEGACY_REGISTRY_SCHEMA: _ProfileSpec(
        registry_schema=_LEGACY_REGISTRY_SCHEMA,
        controlled_schema=_LEGACY_CONTROLLED_SCHEMA,
        extensions_schema=_LEGACY_EXTENSIONS_SCHEMA,
        context_order=_LEGACY_CONTEXT_ORDER,
        dictionary_entry_rules=False,
    ),
    _V02_REGISTRY_SCHEMA: _ProfileSpec(
        registry_schema=_V02_REGISTRY_SCHEMA,
        controlled_schema=_V02_CONTROLLED_SCHEMA,
        extensions_schema=_V02_EXTENSIONS_SCHEMA,
        context_order=_CONTEXT_ORDER,
        dictionary_entry_rules=True,
    ),
    _REGISTRY_SCHEMA: _ProfileSpec(
        registry_schema=_REGISTRY_SCHEMA,
        controlled_schema=_CONTROLLED_SCHEMA,
        extensions_schema=_EXTENSIONS_SCHEMA,
        context_order=_CONTEXT_ORDER,
        dictionary_entry_rules=True,
        undeclared_attribute_cases=(
            ("*", "subtype", "element subtype", "ocd-undeclared-subtype"),
            ("*", "style", "style declaration", "ocd-undeclared-style"),
            ("*", "rendition", "rendition pointer", "ocd-undeclared-rendition"),
        ),
    ),
}
_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "package_id",
        "status",
        "complete_file_set",
        "authority_boundary",
        "members",
        "generation",
        "adoption_requirement",
    }
)
_GENERATION_KEYS = frozenset({"schematron_closed_values", "documentation", "freshness"})
_MEMBER_KEYS = frozenset({"role", "path", "sha256"})
_CONTROLLED_KEYS = frozenset(
    {"schema_version", "status", "adoption_requirement", "lexical_rule", "contexts"}
)
_CONTEXT_KEYS = frozenset({"context", "values"})
_EXTENSIONS_KEYS = frozenset({"schema_version", "status", "extensions"})


class ProfileError(ValueError):
    """The profile package is malformed, stale, or outside its authority."""


@dataclass(frozen=True)
class Profile:
    """A validated, hash-bound profile package."""

    root: Path
    manifest: dict[str, Any]
    controlled_values: dict[str, list[str]]
    extensions: list[dict[str, Any]]
    manifest_sha256: str
    member_sha256: dict[str, str]

    @property
    def schema_version(self) -> str:
        """Return the package schema version selected by the manifest."""

        return str(self.manifest["schema_version"])

    @property
    def version(self) -> str:
        """Return the short provisional profile version (for example ``0.3``)."""

        return self.schema_version.rsplit("-", 1)[-1]


def _fail(context: str, message: str) -> None:
    raise ProfileError(f"{context}: {message}")


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


def _duplicate_key(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProfileError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(path: Path, context: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ProfileError(f"{context}: cannot read package member") from exc
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicate_key)
    except ProfileError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProfileError(f"{context}: invalid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        _fail(context, "top level must be an object")
    return value


def _string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(context, "must be a nonempty string")
    return value


def _digest(value: Any, context: str) -> str:
    text = _string(value, context)
    if _SHA256.fullmatch(text) is None:
        _fail(context, "must be a lowercase SHA-256 digest")
    return text


def _relative(value: Any, context: str) -> str:
    text = _string(value, context)
    if "\\" in text or ":" in text or "\x00" in text:
        _fail(context, "must be a normalized relative POSIX path")
    path = PurePosixPath(text)
    if path.is_absolute() or path.as_posix() != text or not path.parts:
        _fail(context, "must be a normalized relative POSIX path")
    if any(part in {"", ".", ".."} for part in path.parts):
        _fail(context, "must be a normalized relative POSIX path")
    return text


def _sha256_file(path: Path, context: str) -> str:
    try:
        return sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ProfileError(f"{context}: cannot read member") from exc


def _member_path(root: Path, relative: str, context: str) -> Path:
    _relative(relative, context)
    root_resolved = root.resolve()
    path = root / PurePosixPath(relative)
    try:
        resolved = path.resolve()
    except OSError as exc:
        raise ProfileError(f"{context}: cannot resolve member") from exc
    if not resolved.is_relative_to(root_resolved):
        _fail(context, "member escapes package root")
    current = root_resolved
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            _fail(context, "symlink or junction members are not permitted")
    if not path.is_file():
        _fail(context, "member is missing or not a regular file")
    return path


def _package_root(path: Path | None) -> Path:
    if path is None:
        return Path(__file__).resolve().parents[2] / "schemas" / "v2" / "tei"
    candidate = Path(path)
    if candidate.is_file() or candidate.name == _MANIFEST_NAME:
        candidate = candidate.parent
    return candidate


def _profile_spec(schema_version: Any, context: str) -> _ProfileSpec:
    if not isinstance(schema_version, str) or schema_version not in _PROFILE_SPECS:
        expected = ", ".join(sorted(_PROFILE_SPECS))
        _fail(f"{context}.schema_version", f"expected one of {expected}")
    return _PROFILE_SPECS[schema_version]


def _validate_manifest(
    value: dict[str, Any], context: str, spec: _ProfileSpec
) -> list[dict[str, str]]:
    _exact_keys(value, _MANIFEST_KEYS, context)
    if value["schema_version"] != spec.registry_schema:
        _fail(f"{context}.schema_version", f"expected {spec.registry_schema!r}")
    if value["package_id"] != _PACKAGE_ID:
        _fail(f"{context}.package_id", f"expected {_PACKAGE_ID!r}")
    if value["status"] != "provisional":
        _fail(f"{context}.status", "must remain provisional")
    if value["complete_file_set"] is not True:
        _fail(f"{context}.complete_file_set", "must be true")
    _string(value["authority_boundary"], f"{context}.authority_boundary")
    _string(value["adoption_requirement"], f"{context}.adoption_requirement")
    generation = value["generation"]
    if not isinstance(generation, dict):
        _fail(f"{context}.generation", "must be an object")
    _exact_keys(generation, _GENERATION_KEYS, f"{context}.generation")
    for key in _GENERATION_KEYS:
        _string(generation[key], f"{context}.generation.{key}")

    members = value["members"]
    if not isinstance(members, list) or len(members) != 3:
        _fail(f"{context}.members", "must contain exactly three member records")
    records: list[dict[str, str]] = []
    seen_roles: set[str] = set()
    seen_paths: set[str] = set()
    for index, raw in enumerate(members):
        if not isinstance(raw, dict):
            _fail(f"{context}.members[{index}]", "must be an object")
        _exact_keys(raw, _MEMBER_KEYS, f"{context}.members[{index}]")
        role = _string(raw["role"], f"{context}.members[{index}].role")
        relative = _relative(raw["path"], f"{context}.members[{index}].path")
        digest = _digest(raw["sha256"], f"{context}.members[{index}].sha256")
        if role in seen_roles:
            _fail(context, f"duplicate member role {role!r}")
        if relative in seen_paths:
            _fail(context, f"duplicate member path {relative!r}")
        seen_roles.add(role)
        seen_paths.add(relative)
        records.append({"role": role, "path": relative, "sha256": digest})
    expected = {
        "controlled-values": "controlled-values.json",
        "extensions": "extensions.json",
        "common-rules": "common-rules.sch",
    }
    actual = {record["role"]: record["path"] for record in records}
    if actual != expected:
        _fail(context, f"members must match exact role/path map {expected!r}")
    return records


def _load_controlled(path: Path, spec: _ProfileSpec) -> dict[str, list[str]]:
    value = _load_json(path, "controlled-values")
    _exact_keys(value, _CONTROLLED_KEYS, "controlled-values")
    if value["schema_version"] != spec.controlled_schema:
        _fail("controlled-values.schema_version", f"expected {spec.controlled_schema!r}")
    if value["status"] != "provisional":
        _fail("controlled-values.status", "must remain provisional")
    _string(value["adoption_requirement"], "controlled-values.adoption_requirement")
    if value["lexical_rule"] != "lowercase-kebab-case":
        _fail("controlled-values.lexical_rule", "must be lowercase-kebab-case")
    contexts = value["contexts"]
    if not isinstance(contexts, list) or len(contexts) != len(spec.context_order):
        _fail("controlled-values.contexts", "must contain every declared common context exactly once")
    result: dict[str, list[str]] = {}
    for index, raw in enumerate(contexts):
        if not isinstance(raw, dict):
            _fail(f"controlled-values.contexts[{index}]", "must be an object")
        _exact_keys(raw, _CONTEXT_KEYS, f"controlled-values.contexts[{index}]")
        context = _string(raw["context"], f"controlled-values.contexts[{index}].context")
        if context not in _CONTEXT_RULES:
            _fail(f"controlled-values.contexts[{index}].context", "is not an allowed common context")
        if context in result:
            _fail("controlled-values.contexts", f"duplicate context {context!r}")
        values = raw["values"]
        if not isinstance(values, list) or not values:
            _fail(f"controlled-values.contexts[{index}].values", "must be a nonempty array")
        normalized: list[str] = []
        for value_index, token in enumerate(values):
            token = _string(token, f"controlled-values.contexts[{index}].values[{value_index}]")
            if _LOWER_KEBAB.fullmatch(token) is None:
                _fail(
                    f"controlled-values.contexts[{index}].values[{value_index}]",
                    "must use lowercase-kebab case",
                )
            if token in normalized:
                _fail(f"controlled-values.contexts[{index}].values", f"duplicate value {token!r}")
            normalized.append(token)
        result[context] = normalized
    if tuple(result) != spec.context_order:
        _fail("controlled-values.contexts", "contexts must be in the declared deterministic order")
    return result


def _load_extensions(path: Path, spec: _ProfileSpec) -> list[dict[str, Any]]:
    value = _load_json(path, "extensions")
    _exact_keys(value, _EXTENSIONS_KEYS, "extensions")
    if value["schema_version"] != spec.extensions_schema:
        _fail("extensions.schema_version", f"expected {spec.extensions_schema!r}")
    if value["status"] != "provisional":
        _fail("extensions.status", "must remain provisional")
    try:
        return validate_extension_records(value["extensions"], context="extensions.extensions")
    except ProfileError:
        raise
    except (TypeError, ValueError) as exc:
        raise ProfileError("extensions.extensions: invalid extension records") from exc


def load_profile(path: Path | None = None) -> Profile:
    """Load and verify one complete profile package.

    ``path`` may identify either the package directory or its manifest.  The
    package directory may contain exactly the manifest and its three declared
    members; unlisted files, symlinks, stale hashes, duplicate JSON keys, and
    stale generated Schematron all fail closed.
    """

    root = _package_root(path)
    if not root.is_dir():
        raise ProfileError(f"profile package is not a directory: {root}")
    try:
        entries = list(root.iterdir())
    except OSError as exc:
        raise ProfileError("profile package cannot be listed") from exc
    unexpected = sorted(entry.name for entry in entries if entry.name not in _MEMBER_NAMES)
    if unexpected:
        _fail("profile package", f"unlisted members are not permitted: {', '.join(unexpected)}")
    manifest_path = _member_path(root, _MANIFEST_NAME, "profile-registry")
    manifest_raw = manifest_path.read_bytes()
    manifest = _load_json(manifest_path, "profile-registry")
    spec = _profile_spec(manifest.get("schema_version"), "profile-registry")
    member_records = _validate_manifest(manifest, "profile-registry", spec)

    paths: dict[str, Path] = {}
    member_hashes: dict[str, str] = {}
    for record in member_records:
        member_path = _member_path(root, record["path"], f"member {record['role']}")
        actual = _sha256_file(member_path, f"member {record['role']}")
        if actual != record["sha256"]:
            _fail(f"member {record['role']}", "SHA-256 does not match manifest")
        paths[record["role"]] = member_path
        member_hashes[record["path"]] = actual

    controlled_values = _load_controlled(paths["controlled-values"], spec)
    extensions = _load_extensions(paths["extensions"], spec)
    profile = Profile(
        root=root.resolve(),
        manifest=manifest,
        controlled_values=controlled_values,
        extensions=extensions,
        manifest_sha256=sha256(manifest_raw).hexdigest(),
        member_sha256=member_hashes,
    )
    try:
        rendered = render_schematron(profile)
        checked_in = paths["common-rules"].read_bytes()
    except (OSError, TypeError, ValueError) as exc:
        if isinstance(exc, ProfileError):
            raise
        raise ProfileError("common-rules: unable to render or read generated rules") from exc
    if checked_in != rendered:
        _fail("common-rules", "checked-in Schematron is stale or was not generated deterministically")
    return profile


def _xpath_literal(value: str) -> str:
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    return "concat(" + ', "\'", '.join(_xpath_literal(part) for part in parts) + ")"


def _closed_test(attribute: str, values: Iterable[str]) -> str:
    return " or ".join(f"@{attribute} = {_xpath_literal(value)}" for value in values)


def _concrete_attribute_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if re.fullmatch(r"[A-Za-z0-9]+(?:[-:.][A-Za-z0-9]+)*", value):
        return value
    return None


def _extension_value_allowances(
    selected: Iterable[Mapping[str, Any]], element: str, attribute: str
) -> list[tuple[str, list[str]]]:
    """Return values and exact node scopes for one extension attribute."""

    allowances: list[tuple[str, list[str]]] = []
    for record in selected:
        parsed = parse_extension_path(record)
        if element != "*" and parsed.element not in {element, "*"}:
            continue
        values: list[str] = []
        required = record["representation"].get("required_attributes", {})
        concrete = _concrete_attribute_value(required.get(attribute))
        if concrete is not None:
            values.append(concrete)
        predicate = parsed.predicate
        if predicate:
            match = re.fullmatch(
                rf"@{re.escape(attribute)}\s*=\s*(['\"])(.*?)\1", predicate
            )
            if match:
                values.append(match.group(2))
        for context_name, controlled in record["representation"].get("controlled_values", {}).items():
            context_attribute = context_name.rsplit("/", 1)[-1].removeprefix("@")
            if context_attribute != attribute:
                continue
            context_element = context_name.split("/", 1)[0]
            if (element != "*" and context_name not in {attribute, f"@{attribute}"}
                    and context_element not in {element, "*"}):
                continue
            values.extend(controlled)
        if values:
            allowances.append((f"{_extension_condition(record)}", list(dict.fromkeys(values))))
    return allowances


def _add_assert(rule: ET.Element, rule_id: str, test: str, message: str) -> None:
    assertion = ET.SubElement(rule, f"{{{SCH_NS}}}assert")
    assertion.set("id", rule_id)
    assertion.set("test", test)
    assertion.text = message


def _add_rule(pattern: ET.Element, context: str) -> ET.Element:
    return ET.SubElement(pattern, f"{{{SCH_NS}}}rule", {"context": context})


def _extension_condition(record: Mapping[str, Any]) -> str:
    selector = parse_extension_path(record).context
    # XPath 1.0 has no direct node-membership operator.  Unioning the current
    # node with the source-bound selector preserves the exact ancestor scope:
    # the counts are equal only when the current node belongs to that set.
    return f"count(. | {selector}) = count({selector})"


def _selected_extension_conditions(records: list[dict[str, Any]]) -> str:
    conditions = [_extension_condition(record) for record in records]
    return " or ".join(conditions) if conditions else "false()"


def _add_undeclared_rules(
    root: ET.Element,
    selected: list[dict[str, Any]],
    context_order: tuple[str, ...],
    extra_cases: tuple[tuple[str, str, str, str], ...] = (),
) -> None:
    cases = (
        ("quote", "type", "quote type", "ocd-undeclared-quote-type"),
        ("ab", "type", "ab type", "ocd-undeclared-ab-type"),
        ("p", "rend", "paragraph rendition", "ocd-undeclared-p-rend"),
        ("note", "type", "note type", "ocd-undeclared-note-type"),
        ("*", "ana", "annotation", "ocd-undeclared-annotation"),
    ) + extra_cases
    for element, attribute, label, rule_id in cases:
        context = f"tei:{element}[@{attribute}]"
        allowed = _extension_value_allowances(selected, element, attribute)
        allowance = " or ".join(
            f"({scope} and ({_closed_test(attribute, values)}))" for scope, values in allowed
        ) or "false()"
        pattern = ET.SubElement(
            root,
            f"{{{SCH_NS}}}pattern",
            {"id": f"{rule_id}-pattern"},
        )
        rule = _add_rule(pattern, context)
        _add_assert(
            rule,
            rule_id,
            allowance,
            f"[{rule_id}] {label} is not admitted by the common profile; select a complete bound extension.",
        )
    known_type_elements = [name.split("/")[0] for name in context_order if name.endswith("/@type")]
    known_type_elements.extend(element for element, attribute, _, _ in cases if attribute == "type")
    exclusion = " or ".join(f"self::tei:{element}" for element in known_type_elements)
    pattern = ET.SubElement(root, f"{{{SCH_NS}}}pattern", {"id": "ocd-other-custom-types"})
    rule = _add_rule(pattern, f"tei:*[@type][not({exclusion})]")
    allowed = _extension_value_allowances(selected, "*", "type")
    allowance = " or ".join(f"({scope} and ({_closed_test('type', values)}))" for scope, values in allowed) or "false()"
    _add_assert(rule, "ocd-undeclared-element-type", allowance,
                "[ocd-undeclared-element-type] This element type requires an explicit source-bound extension.")


def _add_dictionary_entry_rules(root: ET.Element) -> None:
    """Require every dictionary entry to carry its own headword heading.

    The nearest dictionary-entry ancestor test prevents a nested entry's
    headword from satisfying its outer entry.  No sibling position is tested,
    so the headword may occur after other entry content.
    """

    pattern = ET.SubElement(root, f"{{{SCH_NS}}}pattern", {"id": "ocd-dictionary-entry-structure"})
    rule = _add_rule(pattern, "tei:div[@type='dictionary-entry']")
    _add_assert(
        rule,
        "ocd-dictionary-entry-headword",
        "count(.//tei:head[@type='headword'][normalize-space(.) != ''][count(ancestor::tei:div[@type='dictionary-entry'][1] | current()) = 1]) > 0",
        "[ocd-dictionary-entry-headword] A dictionary entry must contain its own nonempty headword heading; nested entry headings do not satisfy the outer entry.",
    )


def _extension_value_specs(selected: list[dict[str, Any]]) -> list[tuple[str, str, str, str]]:
    specs: list[tuple[str, str, str, str]] = []
    for record in selected:
        parsed = parse_extension_path(record)
        rule_ids = list(record["validation_rule_ids"])
        next_rule = len(record["representation"].get("required_attributes", {})) + len(
            record["representation"].get("required_children", [])
        ) + len(record["representation"].get("order", []))
        for context_name, values in record["representation"].get("controlled_values", {}).items():
            if "/@" in context_name:
                _, attribute = context_name.rsplit("/@", 1)
            elif context_name.startswith("@"):
                attribute = context_name[1:]
            else:
                attribute = context_name
            rule_id = (
                rule_ids[next_rule]
                if next_rule < len(rule_ids)
                else f"{record['extension_id']}-controlled-{attribute}"
            )
            next_rule += 1
            specs.append(
                (
                    rule_id,
                    parsed.context,
                    _closed_test(attribute, values),
                    f"[{rule_id}] {record['extension_id']} {attribute} must use a declared extension value.",
                )
            )
    return specs


def render_schematron(profile: Profile, extension_ids: tuple[str, ...] = ()) -> bytes:
    """Render deterministic common rules and explicitly selected extensions."""

    if not isinstance(profile, Profile):
        raise ProfileError("render_schematron: expected a Profile")
    spec = _profile_spec(profile.schema_version, "profile")
    selected = select_extensions(profile.extensions, extension_ids)

    ET.register_namespace("sch", SCH_NS)
    root = ET.Element(f"{{{SCH_NS}}}schema")
    ET.SubElement(root, f"{{{SCH_NS}}}title").text = "OCD provisional TEI common profile"
    ET.SubElement(root, f"{{{SCH_NS}}}ns", {"prefix": "tei", "uri": TEI_NS})
    ET.SubElement(root, f"{{{SCH_NS}}}ns", {"prefix": "xml", "uri": XML_NS})

    closed = ET.SubElement(root, f"{{{SCH_NS}}}pattern", {"id": "ocd-registry-generated-closed-values"})
    for context_name in spec.context_order:
        context, attribute, label = _CONTEXT_RULES[context_name]
        rule = _add_rule(closed, context)
        rule_id = f"ocd-controlled-{context_name.split('/')[0]}-{attribute}"
        values = list(profile.controlled_values[context_name])
        test = _closed_test(attribute, values)
        extension_terms = [
            f"({scope} and ({_closed_test(attribute, allowed_values)}))"
            for scope, allowed_values in _extension_value_allowances(
                selected, context_name.split("/", 1)[0], attribute
            )
        ]
        if extension_terms:
            test = f"({test}) or " + " or ".join(extension_terms)
        _add_assert(
            rule,
            rule_id,
            test,
            f"[{rule_id}] A {label} must be admitted by the controlled-values registry.",
        )

    note_pattern = ET.SubElement(root, f"{{{SCH_NS}}}pattern", {"id": "ocd-note-target-resolution"})
    note_rule = _add_rule(note_pattern, "tei:ref[@type='note']")
    _add_assert(
        note_rule,
        "ocd-note-target-required",
        "starts-with(normalize-space(@target), '#') and string-length(substring-after(normalize-space(@target), '#')) > 0",
        "[ocd-note-target-required] A note reference must use a nonempty fragment target.",
    )
    _add_assert(
        note_rule,
        "ocd-note-target-resolves",
        "count(//tei:note[@xml:id = substring-after(normalize-space(current()/@target), '#')]) = 1",
        "[ocd-note-target-resolves] A note reference must resolve to exactly one note.",
    )

    reference_pattern = ET.SubElement(root, f"{{{SCH_NS}}}pattern", {"id": "ocd-reference-locator-semantics"})
    target_rule = _add_rule(reference_pattern, "tei:ref[@target or @cRef]")
    _add_assert(
        target_rule,
        "ocd-ref-target-cRef-exclusive",
        "not(@target and @cRef)",
        "[ocd-ref-target-cRef-exclusive] A reference cannot carry both target and cRef.",
    )
    _add_assert(
        target_rule,
        "ocd-ref-target-uri",
        "not(@target) or (normalize-space(@target) = string(@target) and normalize-space(@target) != '' and not(contains(@target, ' ')))",
        "[ocd-ref-target-uri] A target locator must be a nonempty space-free URI or fragment.",
    )
    _add_assert(
        target_rule,
        "ocd-ref-cRef-scripture",
        "not(@cRef) or (@type = 'scripture' and normalize-space(@cRef) = string(@cRef) and normalize-space(@cRef) != '' and not(@target))",
        "[ocd-ref-cRef-scripture] A canonical cRef requires type scripture and cannot share target.",
    )

    identity_pattern = ET.SubElement(root, f"{{{SCH_NS}}}pattern", {"id": "ocd-identifier-context-and-format"})
    source_id_rule = _add_rule(identity_pattern, "tei:idno[@type='sha256' or @type='git-commit-sha1']")
    _add_assert(
        source_id_rule,
        "ocd-sha256-format",
        "not(@type = 'sha256') or (string-length(string(.)) = 64 and translate(string(.), '0123456789abcdef', '') = '')",
        "[ocd-sha256-format] sha256 must be exactly 64 lowercase hexadecimal characters.",
    )
    _add_assert(
        source_id_rule,
        "ocd-git-commit-sha1-format",
        "not(@type = 'git-commit-sha1') or (string-length(string(.)) = 40 and translate(string(.), '0123456789abcdef', '') = '')",
        "[ocd-git-commit-sha1-format] git-commit-sha1 must be exactly 40 lowercase hexadecimal characters.",
    )
    _add_assert(
        source_id_rule,
        "ocd-source-idno-context",
        "ancestor::tei:sourceDesc",
        "[ocd-source-idno-context] Source digest and revision identifiers belong under a source description.",
    )
    ocd_id_rule = _add_rule(identity_pattern, "tei:idno[starts-with(@type, 'ocd-') and substring(@type, string-length(@type) - 2) = '-id']")
    _add_assert(
        ocd_id_rule,
        "ocd-identity-idno-context",
        "ancestor::tei:teiHeader and not(ancestor::tei:text)",
        "[ocd-identity-idno-context] OCD identity identifiers belong in the TEI header, outside the text.",
    )

    _add_undeclared_rules(
        root,
        selected,
        spec.context_order,
        spec.undeclared_attribute_cases,
    )
    if spec.dictionary_entry_rules:
        _add_dictionary_entry_rules(root)

    extension_rule_ids: set[str] = set()
    for record in selected:
        witness_rule_id = f"{record['extension_id']}-witness"
        extension_rule_ids.add(witness_rule_id)
        witness_pattern = ET.SubElement(
            root,
            f"{{{SCH_NS}}}pattern",
            {"id": f"ocd-selected-extension-{witness_rule_id}"},
        )
        witness_rule = _add_rule(witness_pattern, "tei:TEI")
        selector = parse_extension_path(record).context
        _add_assert(
            witness_rule,
            witness_rule_id,
            f"count({selector}) > 0",
            f"[{witness_rule_id}] The selected bound extension must have at least one XML witness.",
        )
    for rule_id, context, test, message in extension_rule_specs(selected):
        if rule_id in extension_rule_ids:
            _fail("selected extensions", f"duplicate validation rule id {rule_id!r}")
        extension_rule_ids.add(rule_id)
        extension_pattern = ET.SubElement(
            root,
            f"{{{SCH_NS}}}pattern",
            {"id": f"ocd-selected-extension-{rule_id}"},
        )
        rule = _add_rule(extension_pattern, context)
        _add_assert(rule, rule_id, test, message)
    for rule_id, context, test, message in extension_order_specs(selected):
        if rule_id in extension_rule_ids:
            _fail("selected extensions", f"duplicate validation rule id {rule_id!r}")
        extension_rule_ids.add(rule_id)
        extension_pattern = ET.SubElement(
            root,
            f"{{{SCH_NS}}}pattern",
            {"id": f"ocd-selected-extension-{rule_id}"},
        )
        rule = _add_rule(extension_pattern, context)
        _add_assert(rule, rule_id, test, message)
    for rule_id, context, test, message in _extension_value_specs(selected):
        if rule_id in extension_rule_ids:
            _fail("selected extensions", f"duplicate validation rule id {rule_id!r}")
        extension_rule_ids.add(rule_id)
        extension_pattern = ET.SubElement(
            root,
            f"{{{SCH_NS}}}pattern",
            {"id": f"ocd-selected-extension-{rule_id}"},
        )
        rule = _add_rule(extension_pattern, context)
        _add_assert(rule, rule_id, test, message)

    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True, short_empty_elements=True)


__all__ = ["Profile", "ProfileError", "load_profile", "render_schematron"]
