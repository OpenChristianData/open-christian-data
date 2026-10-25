"""Producer-independent checks for the provisional TEI-004 projection.

The projection producer and this checker deliberately have different
implementations.  The checker reads the TEI with lxml and derives every
correspondence claim from the accepted document, then compares those claims
with the public rows and the private receipt.  A receipt status is evidence
to inspect; it is never used as the check result.
"""

from __future__ import annotations
from ocd_kernel.projection.scripture_authority import BOOK_CODES_PATH, load_book_codes
from ocd_kernel.projection.scripture_targets_check import observe_reference_record


import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from lxml import etree
from ocd_kernel.lib.path_io import io_path, resolve_path


TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
XML_LANG = f"{{{XML_NS}}}lang"
NS = {"tei": TEI_NS}

EXPECTED_MAPPING_VERSION = "ocd-common-prose-provisional-v4"
EXPECTED_RECEIPT_SCHEMA_VERSION = "2.0"
EXPECTED_ASSEMBLER_VERSION = "ocd-correspondence-assembler-provisional-v1"
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
LANGUAGE_RE = re.compile(r"^[a-zA-Z]{2,8}(?:-[a-zA-Z0-9]{1,8})*$")
OMITTED_BOUNDARY = "\x00"

REQUIRED_RECEIPT_KEYS = {
    "schema_version",
    "mapping_version",
    "master_sha256",
    "book_codes_sha256",
    "scope_id",
    "identity",
    "authority",
    "output_sha256",
    "row_count",
    "anchors",
    "inventory",
    "references",
    "warnings",
    "exclusions",
    "independent_check",
    "assembler_version",
}
PUBLIC_ROW_KEYS = {
    "work_id",
    "textual_form_id",
    "edition_id",
    "record_id",
    "sequence",
    "category",
    "language",
    "text",
    "representation_revision",
    "locator",
    "provenance",
    "notes",
    "references",
}
PRIVATE_FIELD_NAMES = {
    "assessment",
    "authority",
    "master_path",
    "acquisition_path",
    "source_path",
    "source_sha256",
    "retained_sha256",
    "original_target",
    "tei_path",
    "xml_id",
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _canonical_rows(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(_canonical_bytes(row) for row in rows)


def _schema_path(name: str) -> Path:
    return Path(__file__).resolve().parents[2] / "schemas" / "v2" / name


def _schema_diagnostics(value: Any, *, schema_name: str, label: str) -> list[str]:
    """Validate a boundary value against the shared closed schema."""

    try:
        import jsonschema

        schema = json.loads(_schema_path(schema_name).read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        failures = sorted(
            validator.iter_errors(value),
            key=lambda failure: tuple(
                (type(part).__name__, str(part)) for part in failure.absolute_path
            ),
        )
    except (ImportError, OSError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
        return [f"cannot validate {label} against {schema_name}: {exc}"]
    diagnostics: list[str] = []
    for failure in failures:
        location = "".join(
            f"[{part}]" if isinstance(part, int) else f".{part}"
            for part in failure.absolute_path
        ) or "<root>"
        diagnostics.append(f"{label}{location}: {failure.message}")
    return diagnostics


def _row_schema_diagnostics(rows: Any) -> list[str]:
    if not isinstance(rows, list):
        return _schema_diagnostics(
            rows,
            schema_name="public-row.schema.json",
            label="public rows",
        )
    diagnostics: list[str] = []
    for index, row in enumerate(rows):
        diagnostics.extend(
            _schema_diagnostics(
                row,
                schema_name="public-row.schema.json",
                label=f"public row {index + 1}",
            )
        )
    return diagnostics


def _load_projection_policy(errors: list[str]) -> dict[str, Any] | None:
    """Load the declarative projection policy without importing the producer."""

    policy: dict[str, Any] = {}
    initial_error_count = len(errors)
    try:
        schema = json.loads(
            _schema_path("public-row.schema.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"cannot load projection policy: {exc}")
        return None
    raw = schema.get("x-ocd-projection-policy")
    if not isinstance(raw, Mapping):
        errors.append("public row schema is missing x-ocd-projection-policy")
        return None
    if raw.get("version") != "3":
        errors.append("unsupported projection policy version")

    required_lists = (
        "text_parts",
        "carrier_parents",
        "container_elements",
        "scope_elements",
        "block_parent_elements",
        "allowed_elements",
    )
    for key in required_lists:
        value = raw.get(key)
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item for item in value
        ):
            errors.append(f"projection policy {key} must be a nonempty string list")
            continue
        policy[key] = set(value)

    raw_attributes = raw.get("allowed_attributes")
    if isinstance(raw_attributes, Mapping):
        parsed_attributes: dict[str, set[str]] = {}
        valid = True
        for element, values in raw_attributes.items():
            if not isinstance(element, str) or not isinstance(values, list) or not all(
                isinstance(item, str) for item in values
            ):
                errors.append("projection policy allowed_attributes has invalid shape")
                valid = False
                continue
            parsed_attributes[element] = set(values)
        if valid:
            policy["allowed_attributes"] = parsed_attributes
    else:
        errors.append("projection policy allowed_attributes must be an object")

    raw_divisions = raw.get("division_types")
    if isinstance(raw_divisions, Mapping):
        for output_key, policy_key in (
            ("excluded_paratext", "excluded_paratext"),
            ("unsupported_prose", "unsupported_prose"),
            ("supported_prose", "supported_prose"),
        ):
            value = raw_divisions.get(policy_key)
            if not isinstance(value, list) or not all(
                isinstance(item, str) and item for item in value
            ):
                errors.append(
                    f"projection policy division_types.{policy_key} must be a string list"
                )
            else:
                policy[output_key] = set(value)
    else:
        errors.append("projection policy division_types must be an object")

    raw_rendering = raw.get("rendering")
    if isinstance(raw_rendering, Mapping):
        normalized_rendering: dict[str, Any] = {}
        for key in (
            "paragraph_element",
            "heading_element",
            "division_element",
            "note_element",
            "line_break_element",
            "script_element",
            "break_no_value",
        ):
            value = raw_rendering.get(key)
            if not isinstance(value, str) or not value:
                errors.append(f"projection policy rendering.{key} must be a string")
            else:
                normalized_rendering[key] = value
        for key in (
            "reference_elements",
            "omitted_elements",
            "milestone_elements",
        ):
            value = raw_rendering.get(key)
            if not isinstance(value, list) or not all(
                isinstance(item, str) and item for item in value
            ):
                errors.append(
                    f"projection policy rendering.{key} must be a string list"
                )
            else:
                normalized_rendering[key] = list(value)
        policy["rendering"] = normalized_rendering
    else:
        errors.append("projection policy rendering must be an object")

    raw_script = raw.get("script")
    if isinstance(raw_script, Mapping):
        styles = raw_script.get("styles")
        if isinstance(styles, list) and all(
            isinstance(item, str) and item for item in styles
        ):
            policy["script_styles"] = set(styles)
        else:
            errors.append("projection policy script.styles must be a string list")
        raw_maps = raw_script.get("maps")
        if isinstance(raw_maps, Mapping):
            parsed_maps: dict[str, dict[str, str]] = {}
            valid = True
            for style in policy.get("script_styles", set()):
                value = raw_maps.get(style)
                if not isinstance(value, Mapping) or not all(
                    isinstance(key, str)
                    and len(key) == 1
                    and isinstance(mapped, str)
                    and mapped
                    for key, mapped in value.items()
                ):
                    errors.append(
                        f"projection policy script.maps.{style} has invalid shape"
                    )
                    valid = False
                    continue
                parsed_maps[style] = dict(value)
            if valid:
                policy["script_maps"] = parsed_maps
        else:
            errors.append("projection policy script.maps must be an object")
        punctuation = raw_script.get("safe_punctuation")
        if isinstance(punctuation, list) and all(
            isinstance(item, str) and len(item) == 1 for item in punctuation
        ):
            policy["script_safe_punctuation"] = set(punctuation)
        else:
            errors.append(
                "projection policy script.safe_punctuation must be single-character strings"
            )
        allow_whitespace = raw_script.get("allow_whitespace")
        if isinstance(allow_whitespace, bool):
            policy["script_allow_whitespace"] = allow_whitespace
        else:
            errors.append("projection policy script.allow_whitespace must be boolean")
    else:
        errors.append("projection policy script must be an object")

    raw_warnings = raw.get("warning_reasons")
    if isinstance(raw_warnings, Mapping) and all(
        isinstance(key, str)
        and isinstance(value, str)
        and value
        for key, value in raw_warnings.items()
    ):
        policy["warning_reasons"] = dict(raw_warnings)
    else:
        errors.append("projection policy warning_reasons must be an object")
    required_warning_keys = {
        "styling",
        "script",
        "language_span",
        "segmentation",
        "milestone",
        "line_break_omitted",
        "line_break_space",
        "note",
    }
    if isinstance(raw_warnings, Mapping) and not required_warning_keys <= set(
        raw_warnings
    ):
        errors.append("projection policy warning_reasons is incomplete")
    if len(errors) != initial_error_count:
        return None
    return policy


def _normalize(value: str) -> str:
    return " ".join(value.split())


def _script_text(
    value: str,
    mode: str | None,
    *,
    node: etree._Element,
    errors: list[str] | None,
    policy: Mapping[str, Any] | None = None,
) -> str:
    """Render one text fragment under an optional super/subscript span.

    The source mapper has the same deliberately narrow rendering contract,
    but this implementation performs the conversion while consuming the
    parser event stream.  Keeping unsupported characters visible in the
    diagnostic path lets the checker explain why a producer result is
    unacceptable instead of silently comparing a flattened value.
    """

    if mode not in {"superscript", "subscript"} or not value:
        return value
    if not isinstance(policy, Mapping):
        if errors is not None:
            errors.append(
                f"unsupported-visible: no projection script policy at {_path(node)}"
            )
        return value
    translation = policy.get("script_maps", {}).get(mode)
    safe_punctuation = policy.get("script_safe_punctuation", set())
    allow_whitespace = policy.get("script_allow_whitespace", False)
    if not isinstance(translation, Mapping):
        if errors is not None:
            errors.append(
                f"unsupported-visible: no {mode} script policy at {_path(node)}"
            )
        return value
    output: list[str] = []
    for character in value:
        if character in translation:
            output.append(translation[character])
            continue
        # These punctuation characters have no script-specific Unicode form,
        # but retaining them preserves their value.  The list is deliberately
        # closed: a raised mathematical symbol can carry meaning that is not
        # preserved by leaving it at the baseline.
        if character in safe_punctuation or (
            allow_whitespace and character.isspace()
        ):
            output.append(character)
            continue
        if errors is not None:
            errors.append(
                f"unsupported-visible: unsupported {mode} script character "
                f"{character!r} at {_path(node)}"
            )
        output.append(character)
    return "".join(output)


def _local(node: etree._Element) -> str:
    return etree.QName(node).localname


def _namespace(node: etree._Element) -> str | None:
    return etree.QName(node).namespace


def _path(node: etree._Element) -> str:
    """Return an ordinal local-name path independent of the producer."""

    components: list[str] = []
    current: etree._Element | None = node
    while current is not None:
        name = _local(current)
        parent = current.getparent()
        if parent is None:
            ordinal = 1
        else:
            siblings = [
                child
                for child in parent
                if isinstance(child.tag, str) and _local(child) == name
            ]
            ordinal = siblings.index(current) + 1
        components.append(f"{name}[{ordinal}]")
        current = parent
    return "/" + "/".join(reversed(components))


def _ancestors(node: etree._Element) -> list[etree._Element]:
    result: list[etree._Element] = []
    current = node.getparent()
    while current is not None:
        result.append(current)
        current = current.getparent()
    result.reverse()
    return result


def _element_children(node: etree._Element) -> list[etree._Element]:
    return [child for child in node if isinstance(child.tag, str)]


def _render_text(
    node: etree._Element,
    *,
    omit_notes: bool = True,
    errors: list[str] | None = None,
    policy: Mapping[str, Any] | None = None,
) -> str:
    """Render text through an lxml event stream.

    The producer uses a recursive child helper.  This checker instead consumes
    start/end events, so text, tails, milestones, and omitted note subtrees are
    ordered by the parser's event stream rather than by the producer's walk.
    """

    pieces: list[str] = []
    omitted_note_depth = 0
    script_modes: list[str | None] = []
    rendering = policy.get("rendering", {}) if isinstance(policy, Mapping) else {}
    note_element = rendering.get("note_element")
    paragraph_element = rendering.get("paragraph_element")
    line_break_element = rendering.get("line_break_element")
    script_element = rendering.get("script_element")
    omitted_elements = set(rendering.get("omitted_elements", ()))
    milestone_elements = set(rendering.get("milestone_elements", ()))
    break_no_value = rendering.get("break_no_value")
    for event, current in etree.iterwalk(node, events=("start", "end")):
        kind = _local(current)
        if event == "start":
            if omitted_note_depth:
                if kind == note_element:
                    omitted_note_depth += 1
                continue
            if omit_notes and kind == note_element and current is not node:
                omitted_note_depth = 1
                pieces.append(OMITTED_BOUNDARY)
                continue
            if kind in omitted_elements and kind != note_element:
                script_modes.append(script_modes[-1] if script_modes else None)
                pieces.append(OMITTED_BOUNDARY)
                continue
            inherited_mode = script_modes[-1] if script_modes else None
            mode = inherited_mode
            script_styles = (
                policy.get("script_styles", set())
                if isinstance(policy, Mapping)
                else set()
            )
            if kind == script_element and current.get("rend") in script_styles:
                mode = current.get("rend")
                if inherited_mode is not None:
                    if errors is not None:
                        errors.append(
                            "unsupported-visible: nested super/subscript spans "
                            f"at {_path(current)}"
                        )
            script_modes.append(mode)
            if current is node:
                pieces.append(
                    _script_text(
                        current.text or "",
                        mode,
                        node=current,
                        errors=errors,
                        policy=policy,
                    )
                )
            elif kind == line_break_element:
                pieces.append(
                    "" if current.get("break") == break_no_value else " "
                )
            else:
                pieces.append(
                    _script_text(
                        current.text or "",
                        mode,
                        node=current,
                        errors=errors,
                        policy=policy,
                    )
                )
            continue

        if omitted_note_depth:
            if kind == note_element:
                omitted_note_depth -= 1
                if omitted_note_depth == 0:
                    pieces.append(
                        _script_text(
                            current.tail or "",
                            script_modes[-1] if script_modes else None,
                            node=(
                                current.getparent()
                                if current.getparent() is not None
                                else current
                            ),
                            errors=errors,
                            policy=policy,
                        )
                    )
            continue
        if current is not node:
            if kind == paragraph_element:
                pieces.append(" ")
            parent_mode = script_modes[-2] if len(script_modes) > 1 else None
            pieces.append(
                _script_text(
                    current.tail or "",
                    parent_mode,
                    node=(
                        current.getparent()
                        if current.getparent() is not None
                        else current
                    ),
                    errors=errors,
                    policy=policy,
                )
            )
        if script_modes:
            script_modes.pop()
    return "".join(pieces)


def _normalize_rendered(
    value: str,
    *,
    node: etree._Element,
    errors: list[str],
) -> str:
    """Normalize rendered text while rejecting an ambiguous omitted boundary."""

    index = 0
    while index < len(value):
        if value[index] != OMITTED_BOUNDARY:
            index += 1
            continue
        end = index + 1
        while end < len(value) and value[end] == OMITTED_BOUNDARY:
            end += 1
        previous = value[index - 1] if index else ""
        following = value[end] if end < len(value) else ""
        if previous.isalnum() and following.isalnum():
            errors.append(
                "unsupported-visible: omitted inline element creates an "
                f"ambiguous alphanumeric boundary at {_path(node)}"
            )
            break
        index = end
    return _normalize(value.replace(OMITTED_BOUNDARY, ""))


def _row_language(
    paragraph: etree._Element, fallback: str | None
) -> str | None:
    candidates = [paragraph, *_ancestors(paragraph)[::-1]]
    for node in candidates:
        value = node.get(XML_LANG)
        if value:
            return value
    return fallback


def _load_controlled_values(errors: list[str]) -> dict[str, set[str]]:
    """Load the explicit TEI vocabulary dependency without importing the producer."""

    path = Path(__file__).resolve().parents[2] / "schemas" / "v2" / "tei" / "controlled-values.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"cannot load TEI controlled values: {exc}")
        return {}
    contexts = value.get("contexts") if isinstance(value, dict) else None
    if not isinstance(contexts, list):
        errors.append("TEI controlled values must contain a contexts list")
        return {}
    result: dict[str, set[str]] = {}
    for item in contexts:
        if not isinstance(item, dict):
            errors.append("TEI controlled value context must be an object")
            continue
        context = item.get("context")
        values = item.get("values")
        if (
            not isinstance(context, str)
            or not context
            or not isinstance(values, list)
            or not all(isinstance(entry, str) and entry for entry in values)
        ):
            errors.append("TEI controlled value context has invalid shape")
            continue
        if context in result:
            errors.append(f"duplicate TEI controlled value context: {context}")
            continue
        result[context] = set(values)
    return result


def _safe_identifier(value: Any, *, field: str, errors: list[str]) -> bool:
    if not isinstance(value, str) or not value or IDENTIFIER_RE.fullmatch(value) is None:
        errors.append(f"{field} is not a valid public identifier")
        return False
    return True


def _validate_context(
    identity: Any,
    *,
    language: Any,
    representation_revision: Any,
    edition_title: Any,
    scope_id: Any,
    errors: list[str],
) -> bool:
    valid = True
    if not isinstance(identity, Mapping):
        errors.append("projection identity must be an object")
        valid = False
    else:
        if set(identity) != {"work_id", "textual_form_id", "edition_id"}:
            errors.append("projection identity must contain exactly work_id, textual_form_id, and edition_id")
            valid = False
        for key in ("work_id", "textual_form_id", "edition_id"):
            if not _safe_identifier(identity.get(key), field=f"identity.{key}", errors=errors):
                valid = False
    if not isinstance(language, str) or not language or LANGUAGE_RE.fullmatch(language) is None:
        errors.append("projection language is invalid")
        valid = False
    if not isinstance(representation_revision, str) or not representation_revision.strip():
        errors.append("representation_revision is required")
        valid = False
    if not isinstance(edition_title, str) or not edition_title.strip():
        errors.append("edition_title is required")
        valid = False
    if scope_id is not None and (
        not isinstance(scope_id, str) or not scope_id
    ):
        errors.append("scope_id must be a nonempty string or null")
        valid = False
    return valid


def _source_comment_inventory(root: etree._Element, errors: list[str]) -> list[dict[str, Any]]:
    """Independently bind permitted source comments to private receipt evidence."""
    comments = list(root.xpath(".//comment()"))
    sibling = root.getprevious()
    while sibling is not None:
        comments.append(sibling)
        sibling = sibling.getprevious()
    sibling = root.getnext()
    while sibling is not None:
        comments.append(sibling)
        sibling = sibling.getnext()
    inventory: list[dict[str, Any]] = []
    for comment in comments:
        if not isinstance(comment, etree._Comment):
            continue
        body = comment.text or ""
        prolog = comment.getparent() is None
        marker = body.strip() in {
            'added reason="insertIndex" class="scripRef"',
            'Start of automatically inserted scripRef index',
            'End of scripRef index', '/added',
        }
        if (not (prolog and body.strip().startswith("Copyright "))
                and not marker) or (comment.tail or "").strip():
            errors.append("unsupported-visible: XML comments are not mapped")
            continue
        inventory.append({
            "tei_path": "comment:" + comment.getroottree().getpath(comment),
            "disposition": "private-header" if prolog else "structure",
            "attributes": {},
            "text_sha256": _sha256_bytes(body.encode("utf-8")),
            "tail_sha256": _sha256_bytes((comment.tail or "").encode("utf-8")),
        })
    return sorted(inventory, key=lambda item: item["tei_path"])


def _load_tei(
    tei_path: Path,
    errors: list[str],
) -> tuple[etree._Element, bytes, list[dict[str, Any]]] | None:
    try:
        raw = tei_path.read_bytes()
    except OSError as exc:
        errors.append(f"cannot read TEI {tei_path}: {exc}")
        return None
    declaration = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)\b", flags=re.IGNORECASE)
    decoded_forms: list[str] = []
    for encoding in (
        "utf-8",
        "utf-16",
        "utf-16-le",
        "utf-16-be",
        "utf-32",
        "utf-32-le",
        "utf-32-be",
    ):
        try:
            decoded_forms.append(raw.decode(encoding))
        except UnicodeDecodeError:
            continue
    if any(declaration.search(value) for value in decoded_forms):
        errors.append("unsupported-visible: DTD or entity declaration")
        return None
    parser = etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        recover=False,
        remove_comments=False,
        remove_pis=False,
    )
    try:
        root = etree.fromstring(raw, parser)
    except (etree.XMLSyntaxError, ValueError) as exc:
        errors.append(f"invalid TEI: {exc}")
        return None
    if _namespace(root) != TEI_NS or _local(root) != "TEI":
        errors.append("unsupported-visible: TEI root is not a TEI element")
        return None
    comment_inventory = _source_comment_inventory(root, errors)
    for comment in root.xpath(".//comment()"):
        parent = comment.getparent()
        if parent is not None:
            parent.remove(comment)
    for instruction in root.xpath(".//processing-instruction() | self::processing-instruction()"):
        del instruction
        errors.append("unsupported-visible: processing instructions are not mapped")
    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        if _namespace(node) != TEI_NS:
            errors.append(f"unsupported-visible: non-TEI element at {_path(node)}")
    if errors:
        return None
    return root, raw, comment_inventory


def _id_map(
    root: etree._Element,
    errors: list[str],
) -> dict[str, etree._Element]:
    result: dict[str, etree._Element] = {}
    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        value = node.get(XML_ID)
        if value is None:
            continue
        if not value:
            errors.append(f"empty xml:id at {_path(node)}")
            continue
        if value in result:
            errors.append(f"duplicate TEI xml:id: {value}")
        else:
            result[value] = node
    return result


def _validate_tei_shape(
    root: etree._Element,
    text_root: etree._Element,
    vocabulary: Mapping[str, set[str]],
    errors: list[str],
    *,
    policy: Mapping[str, Any] | None = None,
    ids: Mapping[str, etree._Element] | None = None,
) -> None:
    root_children = [
        (_namespace(child), _local(child))
        for child in root
        if isinstance(child.tag, str)
    ]
    if root_children != [(TEI_NS, "teiHeader"), (TEI_NS, "text")]:
        errors.append("unsupported-visible: root requires header then text")
    all_text = root.xpath(".//tei:text", namespaces=NS)
    if len(all_text) != 1:
        errors.append("unsupported-visible: exactly one text required")
    text_children = [
        (_namespace(child), _local(child))
        for child in text_root
        if isinstance(child.tag, str)
    ]
    if [name for namespace, name in text_children if namespace == TEI_NS] not in (
        ["body"],
        ["front", "body"],
        ["body", "back"],
        ["front", "body", "back"],
    ) or any(namespace != TEI_NS for namespace, _name in text_children):
        errors.append("unsupported-visible: text requires ordered front/body/back")
    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        node_path = _path(node)
        xml_id = node.get(XML_ID)
        if XML_ID in node.attrib and not xml_id:
            errors.append(f"unsupported-visible: empty xml:id at {node_path}")
        xml_lang = node.get(XML_LANG)
        if XML_LANG in node.attrib and (
            not isinstance(xml_lang, str) or LANGUAGE_RE.fullmatch(xml_lang) is None
        ):
            errors.append(f"unsupported-visible: invalid xml:lang at {node_path}")
    projection_policy = policy if isinstance(policy, Mapping) else {}
    allowed_elements = projection_policy.get("allowed_elements", set())
    allowed_attributes = projection_policy.get("allowed_attributes", {})
    unsupported_prose = projection_policy.get("unsupported_prose", set())
    block_parent_elements = projection_policy.get("block_parent_elements", set())
    container_elements = projection_policy.get("container_elements", set())
    text_parts = projection_policy.get("text_parts", set())
    rendering = projection_policy.get("rendering", {})
    paragraph_element = rendering.get("paragraph_element")
    heading_element = rendering.get("heading_element")
    division_element = rendering.get("division_element")
    note_element = rendering.get("note_element")
    line_break_element = rendering.get("line_break_element")
    milestone_elements = set(rendering.get("milestone_elements", ()))
    break_no_value = rendering.get("break_no_value")
    private_attributes = {"div": {"prev", "ana"}, "pb": {"facs"}}
    from pathlib import PurePosixPath
    from urllib.parse import urlsplit

    for node in text_root.iter():
        if not isinstance(node.tag, str):
            continue
        kind = _local(node)
        node_path = _path(node)
        if kind not in allowed_elements:
            errors.append(f"unsupported-visible: {kind} at {node_path}")
            continue
        if kind == "div" and node.get("type") in unsupported_prose:
            errors.append(
                f"unsupported-visible: category semantics {node.get('type')} at {node_path}"
            )
        if kind == line_break_element and node.get("break") not in {
            None,
            "yes",
            break_no_value,
        }:
            errors.append(f"unsupported-visible: lb/@break at {node_path}")
        for attribute, value in node.attrib.items():
            if attribute in private_attributes.get(kind, set()):
                if not value or value != value.strip() or any(char.isspace() for char in value):
                    errors.append(f"unsupported-visible: malformed {kind}/@{attribute} at {node_path}")
                elif attribute == "ana":
                    if re.fullmatch(r"source-tag:[A-Za-z][A-Za-z0-9._-]*", value) is None:
                        errors.append(f"unsupported-visible: malformed div/@ana at {node_path}")
                elif attribute == "prev":
                    if value.startswith("#"):
                        target = (ids or {}).get(value[1:])
                        if target is None or _local(target) != "div" or target is node:
                            errors.append(f"unsupported-visible: unresolved div/@prev at {node_path}")
                    else:
                        parsed = urlsplit(value)
                        if parsed.scheme != "https" or not parsed.netloc or not parsed.fragment:
                            errors.append(f"unsupported-visible: malformed div/@prev at {node_path}")
                else:
                    parsed = urlsplit(value)
                    if parsed.scheme or parsed.netloc or not value.startswith("/") or value.startswith("//") or ".." in PurePosixPath(parsed.path).parts:
                        errors.append(f"unsupported-visible: malformed pb/@facs at {node_path}")
            elif attribute not in set(allowed_attributes.get(kind, set())) | {
                XML_ID,
                XML_LANG,
            }:
                errors.append(f"unsupported-visible: {kind}/@{attribute} at {node_path}")
                continue
            if attribute in {XML_ID, XML_LANG} and not value:
                errors.append(f"unsupported-visible: empty {kind}/@{attribute} at {node_path}")
            context = f"{kind}/@{attribute}"
            allowed = vocabulary.get(context)
            if allowed is not None and value not in allowed:
                errors.append(f"unsupported-visible: {context}={value} at {node_path}")
        parent = node.getparent()
        parent_kind = _local(parent) if parent is not None else None
        if kind in text_parts and parent_kind != "text":
            errors.append(f"unsupported-visible: nested text container at {node_path}")
        if kind in {paragraph_element, heading_element, division_element} and parent_kind not in block_parent_elements:
            if not (kind == paragraph_element and parent_kind == note_element):
                errors.append(f"unsupported-visible: nested block at {node_path}")
        if kind == note_element and any(
            _local(ancestor) in {note_element, heading_element}
            for ancestor in _ancestors(node)
        ):
            errors.append(f"unsupported-visible: nested or heading note at {node_path}")
        if kind in container_elements:
            if _normalize(node.text or "") or any(
                _normalize(child.tail or "") for child in _element_children(node)
            ):
                errors.append(f"unsupported-visible: unwrapped container text at {node_path}")
        if kind in milestone_elements and (
            len(_element_children(node)) or _normalize(node.text or "")
        ):
            errors.append(f"unsupported-visible: nonempty milestone at {node_path}")

    text_nodes = set(text_root.iter())
    direct_text = root.xpath("/tei:TEI/tei:text", namespaces=NS)
    if len(direct_text) != 1:
        errors.append("unsupported-visible: exactly one direct text required")
    if text_root not in text_nodes:
        errors.append("unsupported-visible: invalid text root")


def _scope(
    text_root: etree._Element,
    ids: Mapping[str, etree._Element],
    scope_id: str | None,
    errors: list[str],
    *,
    policy: Mapping[str, Any] | None = None,
) -> etree._Element | None:
    if scope_id is None:
        return text_root
    target = ids.get(scope_id)
    if target is None:
        errors.append(f"invalid projection scope: {scope_id}")
        return None
    scope_elements = (
        policy.get("scope_elements", set())
        if isinstance(policy, Mapping)
        else set()
    )
    if target not in set(text_root.iter()) or _local(target) not in scope_elements:
        errors.append(f"invalid projection scope: {scope_id}")
        return None
    return target


def _excluded_nodes(
    text_root: etree._Element,
    *,
    policy: Mapping[str, Any] | None = None,
) -> set[etree._Element]:
    excluded: set[etree._Element] = set()
    paratext_types = (
        policy.get("excluded_paratext", set())
        if isinstance(policy, Mapping)
        else set()
    )
    for division in text_root.xpath(".//tei:div", namespaces=NS):
        if division.get("type") in paratext_types:
            excluded.update(division.iter())
    return excluded


def _used_headings(
    carriers: list[etree._Element],
    *,
    policy: Mapping[str, Any] | None = None,
) -> set[etree._Element]:
    result: set[etree._Element] = set()
    container_elements = (
        policy.get("container_elements", set())
        if isinstance(policy, Mapping)
        else set()
    )
    heading_element = (
        policy.get("rendering", {}).get("heading_element")
        if isinstance(policy, Mapping)
        else None
    )
    for carrier in carriers:
        for ancestor in _ancestors(carrier):
            if _local(ancestor) not in container_elements:
                continue
            result.update(
                child
                for child in _element_children(ancestor)
                if _local(child) == heading_element
            )
    return result


def _division_context(
    paragraph: etree._Element,
    *,
    errors: list[str] | None = None,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive a structurally paired public division locator."""

    rendering = policy.get("rendering", {}) if isinstance(policy, Mapping) else {}
    division_element = rendering.get("division_element")
    heading_element = rendering.get("heading_element")
    divisions = [
        ancestor
        for ancestor in _ancestors(paragraph)
        if _local(ancestor) == division_element
    ]
    result: list[dict[str, Any]] = []
    render_errors = errors if errors is not None else []
    for division in divisions:
        parent = division.getparent()
        siblings = [
            child
            for child in _element_children(parent)
            if _local(child) == division_element
        ] if parent is not None else []
        if division not in siblings:
            continue
        result.append(
            {
                "order": siblings.index(division) + 1,
                "type": division.get("type"),
                "titles": [
                    _normalize_rendered(
                        _render_text(
                            heading,
                            errors=render_errors,
                            policy=policy,
                        ),
                        node=heading,
                        errors=render_errors,
                    )
                    for heading in _element_children(division)
                    if _local(heading) == heading_element
                ],
            }
        )
    return {"divisions": result}


def _text_part(
    paragraph: etree._Element,
    *,
    policy: Mapping[str, Any] | None = None,
) -> tuple[str | None, etree._Element | None]:
    """Return the direct text-part ancestor and its element."""

    text_parts = (
        policy.get("text_parts", set())
        if isinstance(policy, Mapping)
        else set()
    )
    for ancestor in reversed(_ancestors(paragraph)):
        if _local(ancestor) in text_parts:
            return _local(ancestor), ancestor
    return None, None


def _part_titles(
    paragraph: etree._Element,
    *,
    errors: list[str] | None = None,
    policy: Mapping[str, Any] | None = None,
) -> list[str]:
    """Return headings on the source text part containing this paragraph."""

    _part, part = _text_part(paragraph, policy=policy)
    if part is None:
        return []
    render_errors = errors if errors is not None else []
    heading_element = (
        policy.get("rendering", {}).get("heading_element")
        if isinstance(policy, Mapping)
        else None
    )
    return [
        _normalize_rendered(
            _render_text(heading, errors=render_errors, policy=policy),
            node=heading,
            errors=render_errors,
        )
        for heading in _element_children(part)
        if _local(heading) == heading_element
    ]


def _paragraph_order(paragraph: etree._Element) -> int:
    parent = paragraph.getparent()
    if parent is None:
        return 1
    siblings = parent.xpath("./tei:p", namespaces=NS)
    return siblings.index(paragraph) + 1 if paragraph in siblings else 1


def _derive_projection(
    root: etree._Element,
    *,
    comment_inventory: list[dict[str, Any]],
    identity: Mapping[str, str],
    language: str,
    representation_revision: str,
    edition_title: str,
    scope_id: str | None,
    errors: list[str],
) -> dict[str, Any] | None:
    text_roots = root.xpath("/tei:TEI/tei:text", namespaces=NS)
    if len(text_roots) != 1:
        errors.append("unsupported-visible: exactly one text required")
        return None
    text_root = text_roots[0]
    ids = _id_map(root, errors)
    vocabulary = _load_controlled_values(errors)
    policy = _load_projection_policy(errors)
    if policy is None:
        return None
    controlled_divisions = set(vocabulary.get("div/@type", set()))
    classified_divisions = (
        set(policy.get("excluded_paratext", set()))
        | set(policy.get("unsupported_prose", set()))
        | set(policy.get("supported_prose", set()))
    )
    category_sets = (
        set(policy.get("excluded_paratext", set())),
        set(policy.get("unsupported_prose", set())),
        set(policy.get("supported_prose", set())),
    )
    if (
        not controlled_divisions
        or classified_divisions != controlled_divisions
        or any(left & right for index, left in enumerate(category_sets) for right in category_sets[index + 1 :])
    ):
        errors.append(
            "unsupported-visible: projection policy does not exhaustively "
            "classify controlled div/@type values"
        )
    _validate_tei_shape(
        root,
        text_root,
        vocabulary,
        errors,
        policy=policy,
        ids=ids,
    )
    scope = _scope(text_root, ids, scope_id, errors, policy=policy)
    if scope is None:
        return None
    selected = set(scope.iter())
    excluded = _excluded_nodes(text_root, policy=policy)
    rendering = policy["rendering"]
    paragraph_element = rendering["paragraph_element"]
    heading_element = rendering["heading_element"]
    division_element = rendering["division_element"]
    note_element = rendering["note_element"]
    reference_elements = set(rendering["reference_elements"])
    carrier_parents = policy["carrier_parents"]
    candidates = [
        paragraph
        for paragraph in text_root.iter()
        if isinstance(paragraph.tag, str)
        and _local(paragraph) == paragraph_element
        and paragraph.getparent() is not None
        and _local(paragraph.getparent()) in carrier_parents
    ]
    source_ordinal = {
        paragraph: ordinal
        for ordinal, paragraph in enumerate(candidates, start=1)
    }
    carriers = [
        paragraph
        for paragraph in candidates
        if paragraph in selected and paragraph not in excluded
    ]
    row_for: dict[etree._Element, str] = {}
    rows: list[dict[str, Any]] = []
    anchors: list[dict[str, Any]] = []
    for sequence, paragraph in enumerate(carriers, start=1):
        record_id = f"{identity['edition_id']}:unit-{source_ordinal[paragraph]:06d}"
        for descendant in paragraph.iter():
            row_for[descendant] = record_id
        text_part, _part = _text_part(paragraph, policy=policy)
        if text_part is None:
            errors.append(
                f"unsupported-visible: paragraph has no front/body/back ancestor at {_path(paragraph)}"
            )
        division_context = _division_context(
            paragraph,
            errors=errors,
            policy=policy,
        )
        row = {
            **dict(identity),
            "record_id": record_id,
            "sequence": sequence,
            "category": "prose",
            "language": _row_language(paragraph, language),
            "representation_revision": representation_revision,
            "text": _normalize_rendered(
                _render_text(paragraph, errors=errors, policy=policy),
                node=paragraph,
                errors=errors,
            ),
            "locator": {
                "kind": "paragraph",
                "text_part": text_part,
                "part_titles": _part_titles(
                    paragraph,
                    errors=errors,
                    policy=policy,
                ),
                **division_context,
                "paragraph": _paragraph_order(paragraph),
            },
            "provenance": {"edition_title": edition_title},
            "notes": [
                {
                    "text": _normalize_rendered(
                        _render_text(
                            note,
                            omit_notes=False,
                            errors=errors,
                            policy=policy,
                        ),
                        node=note,
                        errors=errors,
                    ),
                    "place": note.get("place", "unspecified"),
                    "label": note.get("n", ""),
                }
                for note in paragraph.iter()
                if _local(note) == note_element
            ],
            "references": [],
        }
        rows.append(row)
        anchors.append(
            {
                "record_id": record_id,
                "tei_path": _path(paragraph),
                "text_sha256": _sha256_bytes(row["text"].encode("utf-8")),
            }
        )

    note_index: dict[etree._Element, int] = {}
    for carrier in carriers:
        for index, note in enumerate(
            (node for node in carrier.iter() if _local(node) == note_element),
            start=1,
        ):
            note_index[note] = index

    book_codes = load_book_codes()
    references: list[dict[str, Any]] = []
    for reference_node in text_root.iter():
        if _local(reference_node) not in reference_elements:
            continue
        has_target = "target" in reference_node.attrib
        has_c_ref = "cRef" in reference_node.attrib
        target = (
            reference_node.get("target")
            if has_target
            else reference_node.get("cRef")
        )
        if has_target == has_c_ref:
            errors.append(
                "unsupported-visible: reference requires exactly one of "
                f"@target or @cRef at {_path(reference_node)}"
            )
            continue
        if not target or target != target.strip() or len(target.split()) != 1:
            errors.append(
                f"unsupported-visible: reference requires one unambiguous locator at {_path(reference_node)}"
            )
            continue
        if not has_target and target.startswith("#"):
            errors.append(
                f"unsupported-visible: cRef cannot identify a local TEI target at {_path(reference_node)}"
            )
            continue
        if reference_node.get("type") == "note" and (
            not has_target or not target.startswith("#")
        ):
            errors.append(
                "unsupported-visible: note references require @target with a "
                f"complete local target at {_path(reference_node)}"
            )
            continue
        if target.startswith("#"):
            destination = ids.get(target[1:])
            if destination is None:
                errors.append(
                    f"unresolved complete-TEI target: {target} at {_path(reference_node)}"
                )
                continue
            if (
                reference_node.get("type") == "note"
                and _local(destination) != note_element
            ):
                errors.append(
                    f"note pointer target is not a note: {target} at {_path(reference_node)}"
                )
                continue
            resolution = (
                "in-projection" if destination in row_for else "outside-projection"
            )
            target_record_id = row_for.get(destination)
        else:
            resolution = "external"
            target_record_id = None
        target_note = (
            note_index.get(ids.get(target[1:]))
            if has_target and target.startswith("#")
            else None
        )
        source_note = next(
            (note_index[ancestor] for ancestor in _ancestors(reference_node) if ancestor in note_index),
            None,
        )
        reference = {
            "tei_path": _path(reference_node),
            "original_target": target,
            "resolution": resolution,
            "target_record_id": target_record_id,
            "target_note": target_note,
            "source_note": source_note,
        }
        references.append(reference)
        owner = row_for.get(reference_node)
        if owner is not None:
            owner_row = next(row for row in rows if row["record_id"] == owner)
            owner_row["references"].append(
                {
                    "label": _normalize_rendered(
                        _render_text(
                            reference_node,
                            errors=errors,
                            policy=policy,
                        ),
                        node=reference_node,
                        errors=errors,
                    ),
                    **({"source_target": target} if resolution == "external" else {}),
                    **({key: value for key, value in observe_reference_record({"target": target}, book_codes=book_codes).items() if key in ("scripture", "normalization_status")} if resolution == "external" else {}),
                    "resolution": resolution,
                    "target_record_id": target_record_id,
                    "target_note": target_note,
                    "source_note": source_note,
                }
            )

    used_headings = _used_headings(carriers, policy=policy)
    text_nodes = set(text_root.iter())
    inventory: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        heading_ancestors = [
            ancestor
            for ancestor in _ancestors(node) + [node]
            if _local(ancestor) == heading_element
        ]
        if any(heading in used_headings for heading in heading_ancestors):
            disposition = "locator-heading"
        elif node not in text_nodes:
            disposition = "private-header"
        elif node not in selected:
            disposition = "outside-scope"
        elif node in excluded:
            disposition = "excluded-paratext"
        elif node in row_for:
            disposition = "row-content"
        else:
            if heading_ancestors:
                disposition = "excluded-heading"
            elif _local(node) in policy.get("container_elements", set()):
                disposition = "structure"
            else:
                errors.append(f"unsupported-visible: unassigned element at {_path(node)}")
                continue
        item = {
            "tei_path": _path(node),
            "disposition": disposition,
            "attributes": dict(sorted(node.attrib.items())),
            "text_sha256": _sha256_bytes((node.text or "").encode("utf-8")),
            "tail_sha256": _sha256_bytes((node.tail or "").encode("utf-8")),
        }
        inventory.append(item)
        if disposition in {"outside-scope", "excluded-paratext", "excluded-heading"}:
            exclusions.append({"tei_path": _path(node), "reason": disposition})
        if disposition in {"row-content", "locator-heading"}:
            kind = _local(node)
            warning_reasons = policy.get("warning_reasons", {})
            warning_reason = None
            if kind == "hi":
                warning_reason = warning_reasons.get(
                    "script"
                    if node.get("rend") in policy.get(
                        "script_styles", {"superscript", "subscript"}
                    )
                    else "styling"
                )
            elif kind == "foreign":
                warning_reason = warning_reasons.get("language_span")
            elif kind == "seg":
                warning_reason = warning_reasons.get("segmentation")
            elif kind in {"pb", "anchor", "ptr"}:
                warning_reason = warning_reasons.get("milestone")
            elif kind == "lb":
                warning_reason = warning_reasons.get(
                    "line_break_omitted"
                    if node.get("break") == "no"
                    else "line_break_space"
                )
            elif kind == "note":
                warning_reason = warning_reasons.get("note")
            if warning_reason is not None:
                warnings.append(
                    {"tei_path": _path(node), "reason": warning_reason}
                )
        if node in carriers and not next(
            row["text"] for row in rows if row["record_id"] == row_for[node]
        ):
            warnings.append({"tei_path": _path(node), "reason": "empty-native-paragraph"})

    inventory.extend(comment_inventory)

    return {
        "rows": rows,
        "anchors": anchors,
        "inventory": inventory,
        "references": references,
        "warnings": warnings,
        "exclusions": exclusions,
        "scope_id": scope_id,
        "mapping_version": EXPECTED_MAPPING_VERSION,
        "book_codes_sha256": _sha256_file(BOOK_CODES_PATH),
    }


def _compare_private_fields(
    value: Any,
    *,
    location: str,
    errors: list[str],
) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in PRIVATE_FIELD_NAMES:
                errors.append(f"public row contains private field {location}.{key}")
            _compare_private_fields(child, location=f"{location}.{key}", errors=errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _compare_private_fields(child, location=f"{location}[{index}]", errors=errors)


def _compare_rows(
    actual: Any,
    expected: list[dict[str, Any]],
    errors: list[str],
) -> None:
    if not isinstance(actual, list):
        errors.append("public rows must be a list")
        return
    if len(actual) != len(expected):
        errors.append(
            f"public row count mismatch: expected {len(expected)}, found {len(actual)}"
        )
    seen: set[str] = set()
    for index, row in enumerate(actual):
        if not isinstance(row, dict):
            errors.append(f"public row {index + 1} is not an object")
            continue
        _compare_private_fields(row, location=f"rows[{index}]", errors=errors)
        unknown = sorted(set(row) - PUBLIC_ROW_KEYS)
        missing = sorted(PUBLIC_ROW_KEYS - set(row))
        if unknown:
            errors.append(
                f"public row {index + 1} contains unexpected fields: {', '.join(unknown)}"
            )
        if missing:
            errors.append(
                f"public row {index + 1} is missing fields: {', '.join(missing)}"
            )
        record_id = row.get("record_id")
        if isinstance(record_id, str):
            if record_id in seen:
                errors.append(f"duplicate public record_id: {record_id}")
            seen.add(record_id)
        if index < len(expected):
            expected_row = expected[index]
            if row != expected_row:
                differing = [
                    key
                    for key in sorted(set(row) | set(expected_row))
                    if row.get(key) != expected_row.get(key)
                ]
                if differing:
                    errors.append(
                        f"public row {index + 1} mismatch in {', '.join(differing)}"
                    )


def _compare_sequence(
    label: str,
    actual: Any,
    expected: Any,
    errors: list[str],
) -> None:
    if actual != expected:
        errors.append(f"{label} do not independently match accepted TEI")


def _check_receipt_shape(
    receipt: Any,
    *,
    identity: Mapping[str, str],
    scope_id: str | None,
    expected_authority: Mapping[str, Any],
    errors: list[str],
) -> bool:
    if not isinstance(receipt, dict):
        errors.append("projection receipt must be an object")
        return False
    missing = sorted(REQUIRED_RECEIPT_KEYS - set(receipt))
    extra = sorted(set(receipt) - REQUIRED_RECEIPT_KEYS)
    if missing:
        errors.append(f"projection receipt is missing fields: {', '.join(missing)}")
    if extra:
        errors.append(
            f"projection receipt contains unexpected fields: {', '.join(extra)}"
        )
    if receipt.get("schema_version") != EXPECTED_RECEIPT_SCHEMA_VERSION:
        errors.append("unsupported projection receipt schema version")
    if receipt.get("mapping_version") != EXPECTED_MAPPING_VERSION:
        errors.append("unsupported projection mapping version")
    if receipt.get("assembler_version") != EXPECTED_ASSEMBLER_VERSION:
        errors.append("unsupported projection assembler version")
    if receipt.get("scope_id") != scope_id:
        errors.append("projection receipt scope_id does not match authoritative context")
    receipt_identity = receipt.get("identity")
    if receipt_identity != dict(identity):
        errors.append("projection receipt identity does not match authoritative context")
    authority = receipt.get("authority")
    if not isinstance(authority, dict):
        errors.append("projection receipt authority must be an object")
    elif authority != dict(expected_authority):
        if expected_authority:
            errors.append("projection receipt authority does not bind accepted evidence")
        else:
            errors.append("pure document proof requires an empty receipt authority")
    digest_fields = ("master_sha256", "output_sha256")
    for field in digest_fields:
        value = receipt.get(field)
        if (
            not isinstance(value, str)
            or len(value) != 64
            or value.lower() != value
            or any(char not in "0123456789abcdef" for char in value)
        ):
            errors.append(f"projection receipt {field} is not a lowercase SHA-256")
    if (
        not isinstance(receipt.get("row_count"), int)
        or isinstance(receipt.get("row_count"), bool)
        or receipt["row_count"] < 0
    ):
        errors.append("projection receipt row_count is invalid")
    for field in ("anchors", "inventory", "references", "warnings", "exclusions"):
        if not isinstance(receipt.get(field), list):
            errors.append(f"projection receipt {field} must be a list")
    check = receipt.get("independent_check")
    if not isinstance(check, dict):
        errors.append("projection receipt independent_check must be an object")
    else:
        if check.get("status") not in {"pending", "pass", "fail"}:
            errors.append("projection receipt independent_check status is invalid")
        if not isinstance(check.get("errors"), list) or not all(
            isinstance(item, str) for item in check.get("errors", [])
        ):
            errors.append("projection receipt independent_check errors must be strings")
    return not missing and not extra


def _verify_document(
    tei_path: Path,
    rows: Any,
    receipt: Any,
    *,
    identity: Mapping[str, str],
    language: str,
    representation_revision: str,
    edition_title: str,
    scope_id: str | None,
    expected_authority: Mapping[str, Any],
) -> list[str]:
    errors: list[str] = []
    context_ok = _validate_context(
        identity,
        language=language,
        representation_revision=representation_revision,
        edition_title=edition_title,
        scope_id=scope_id,
        errors=errors,
    )
    errors.extend(_row_schema_diagnostics(rows))
    errors.extend(
        _schema_diagnostics(
            receipt,
            schema_name="projection-receipt.schema.json",
            label="projection receipt",
        )
    )
    receipt_shape_ok = _check_receipt_shape(
        receipt,
        identity=identity if isinstance(identity, Mapping) else {},
        scope_id=scope_id,
        expected_authority=expected_authority,
        errors=errors,
    )
    loaded = _load_tei(Path(tei_path), errors)
    if loaded is None or not context_ok or not receipt_shape_ok:
        return errors
    root, raw, comment_inventory = loaded
    if not isinstance(receipt, dict):
        return errors
    receipt_master = receipt.get("master_sha256")
    actual_master = _sha256_bytes(raw)
    if receipt_master != actual_master:
        errors.append("projection receipt master_sha256 does not match TEI")
    derived = _derive_projection(
        root,
        comment_inventory=comment_inventory,
        identity=dict(identity),
        language=language,
        representation_revision=representation_revision,
        edition_title=edition_title,
        scope_id=scope_id,
        errors=errors,
    )
    if derived is None:
        return errors
    derived["master_sha256"] = actual_master
    if receipt.get("book_codes_sha256") != derived["book_codes_sha256"]:
        errors.append("projection receipt book_codes_sha256 does not match reference authority")
    expected_rows = derived["rows"]
    _compare_rows(rows, expected_rows, errors)
    if isinstance(rows, list):
        try:
            output_digest = _sha256_bytes(_canonical_rows(rows))
            if receipt.get("output_sha256") != output_digest:
                errors.append("projection receipt output_sha256 does not match public rows")
        except (TypeError, ValueError) as exc:
            errors.append(f"cannot canonicalize public rows: {exc}")
    if not isinstance(rows, list) or receipt.get("row_count") != len(rows):
        errors.append("projection receipt row_count does not match public rows")
    _compare_sequence(
        "projection anchors",
        receipt.get("anchors"),
        derived["anchors"],
        errors,
    )
    _compare_sequence(
        "projection inventory",
        receipt.get("inventory"),
        derived["inventory"],
        errors,
    )
    _compare_sequence(
        "projection references",
        receipt.get("references"),
        derived["references"],
        errors,
    )
    _compare_sequence(
        "projection warnings",
        receipt.get("warnings"),
        derived["warnings"],
        errors,
    )
    _compare_sequence(
        "projection exclusions",
        receipt.get("exclusions"),
        derived["exclusions"],
        errors,
    )
    return errors


def verify_document(
    tei_path,
    rows,
    receipt,
    *,
    identity,
    language,
    representation_revision,
    edition_title,
    scope_id=None,
) -> list[str]:
    """Return independent mismatch diagnostics for one TEI projection."""

    try:
        return _verify_document(
            Path(tei_path),
            rows,
            receipt,
            identity=identity,
            language=language,
            representation_revision=representation_revision,
            edition_title=edition_title,
            scope_id=scope_id,
            expected_authority={},
        )
    except (OSError, TypeError, ValueError, KeyError, etree.XMLSyntaxError) as exc:
        return [f"projection verification failed: {exc}"]


def _accepted_header_identity(
    master_path: Path,
    identity: Mapping[str, str],
    errors: list[str],
) -> None:
    parser = etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        recover=False,
    )
    try:
        resolved_master = io_path(master_path)
        root = etree.parse(str(resolved_master), parser).getroot()
    except (OSError, RuntimeError, etree.XMLSyntaxError, ValueError) as exc:
        errors.append(f"cannot parse accepted master for identity proof: {exc}")
        return
    headers = root.xpath("/tei:TEI/tei:teiHeader", namespaces=NS)
    if len(headers) != 1:
        errors.append("accepted master must contain exactly one teiHeader")
        return
    header = headers[0]
    for key, expected in identity.items():
        alias = "ocd-" + key.replace("_", "-")
        matches = header.xpath(
            ".//tei:idno[@type=$key or @type=$alias]",
            namespaces=NS,
            key=key,
            alias=alias,
        )
        if not matches or len({node.get("type") for node in matches}) != len(matches):
            errors.append(f"accepted master requires one {key} idno per spelling")
            continue
        if any("".join(node.itertext()).strip() != expected for node in matches):
            errors.append(f"accepted master {key} idno does not match acceptance identity")


def _authority(
    root: Path,
    paths: Mapping[str, Path],
    errors: list[str],
) -> dict[str, dict[str, str]]:
    root = resolve_path(root)
    expected: dict[str, dict[str, str]] = {}
    for key in ("acceptance", "work", "master", "acquisition"):
        path = paths.get(key)
        if path is None:
            errors.append(f"accepted authority path is missing: {key}")
            continue
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            resolved = resolve_path(candidate)
        except (OSError, RuntimeError) as exc:
            errors.append(f"cannot resolve accepted authority {key}: {exc}")
            continue
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError:
            errors.append(f"accepted authority path is outside root: {key}")
            continue
        try:
            digest = _sha256_file(io_path(resolved))
        except OSError as exc:
            errors.append(f"cannot hash accepted authority {key}: {exc}")
            continue
        expected[key] = {"path": relative, "sha256": digest}
    return expected


def verify_accepted(
    root,
    *,
    acceptance_path,
    rows,
    receipt,
) -> list[str]:
    """Verify a promoted accepted edition and its exact authority bindings."""

    errors: list[str] = []
    root_path = resolve_path(root)
    acceptance_file = resolve_path(acceptance_path)
    try:
        from ocd_kernel.library.acquisitions import acquisition_for_edition
        from ocd_kernel.library.identities import edition_by_id, resolve_edition_language
        from ocd_kernel.tei.acceptance import validate_acceptance

        accepted = validate_acceptance(acceptance_file, root=root_path)
    except (OSError, TypeError, ValueError, KeyError) as exc:
        return [f"accepted authority validation failed: {exc}"]
    if accepted.get("promotion", {}).get("status") != "promoted":
        errors.append("accepted projection requires a promoted master")
        return errors
    accepted_identity = accepted.get("identity")
    if not isinstance(accepted_identity, Mapping):
        return ["accepted authority identity is missing"]
    required_identity = ("work_id", "textual_form_id", "edition_id", "acquisition_id")
    if any(not isinstance(accepted_identity.get(key), str) for key in required_identity):
        return ["accepted authority identity is incomplete"]
    try:
        work, edition = edition_by_id(
            root_path, str(accepted_identity["edition_id"])
        )
        acquisition_path, _acquisition = acquisition_for_edition(
            root_path,
            work.work_id,
            edition.edition_id,
            acquisition_id=str(accepted_identity["acquisition_id"]),
        )
    except (OSError, TypeError, ValueError, KeyError) as exc:
        return [f"accepted projection context resolution failed: {exc}"]
    if (
        work.work_id != accepted_identity["work_id"]
        or edition.textual_form_id != accepted_identity["textual_form_id"]
        or edition.edition_id != accepted_identity["edition_id"]
    ):
        errors.append("accepted identity does not identify the canonical edition")
        return errors
    category = edition.record.get("category", work.record.get("category"))
    if category != "prose":
        errors.append("unsupported-visible: accepted category requires its own mapping")
        return errors
    revision = accepted.get("representation_revision")
    if not isinstance(revision, Mapping) or not isinstance(revision.get("id"), str):
        errors.append("accepted representation revision is missing")
        return errors
    language = resolve_edition_language(work.record, edition.record, edition.textual_form_id)
    edition_title = edition.title
    # Acceptance scope is source-native prose, while this boundary verifies the
    # complete promoted master.  project_accepted therefore uses no TEI scope.
    scope_id = None
    context_identity = {
        key: str(accepted_identity[key])
        for key in ("work_id", "textual_form_id", "edition_id")
    }
    _accepted_header_identity(edition.path, accepted_identity, errors)
    expected_authority = _authority(
        root_path,
        {
            "acceptance": acceptance_file,
            "work": work.path,
            "master": edition.path,
            "acquisition": acquisition_path,
        },
        errors,
    )
    errors.extend(
        _verify_document(
            io_path(edition.path),
            rows,
            receipt,
            identity=context_identity,
            language=language,
            representation_revision=revision["id"],
            edition_title=edition_title,
            scope_id=scope_id,
            expected_authority=expected_authority,
        )
    )
    return errors


__all__ = ["verify_document", "verify_accepted"]


def restore_release_item(root: Path, selected: dict, rows: list, receipt: dict,
                         transform: dict | None, *, retained: bool = False):
    """Undo declared publication layers before the independent category check."""
    from .selection import resolve_acceptance_path
    from ocd_kernel.library._common import PipelineError, load_json
    from .work_metadata import check_work_metadata, strip_retained_metadata
    from .public_rows import HASH_BOUND_ITEMS, publication_transform_key, restore_private_source_locations
    from .public_rights import CONTRACT as RIGHTS_CONTRACT, requires_wrapper
    acceptance = resolve_acceptance_path(root, selected['acceptance_path'])
    accepted = load_json(acceptance)
    identity = accepted['identity']
    if 'work_metadata' in receipt and not isinstance(receipt['work_metadata'], dict):
        raise PipelineError('work metadata receipt must be an object')
    outer = receipt.get('work_metadata', {}).get('version') == 'ocd-work-metadata-v3-public'
    strip = strip_retained_metadata if retained else lambda r, p: check_work_metadata(root, r, p)
    if outer:
        rows, receipt = strip(rows, receipt)
    key = publication_transform_key(identity)
    wrapper = requires_wrapper(key, selected.get('license'))
    if (key in HASH_BOUND_ITEMS or wrapper) and transform is None:
        raise PipelineError('historical public-row transform missing')
    if transform is not None:
        if wrapper and transform.get('contract') != RIGHTS_CONTRACT:
            raise PipelineError('publication rights wrapper missing')
        authority = {'acceptance_sha256': hashlib.sha256(acceptance.read_bytes()).hexdigest(),
                     'master_sha256': receipt.get('master_sha256')} if key in HASH_BOUND_ITEMS or wrapper else {}
        rows = restore_private_source_locations(rows, transform, item_id=selected['item_id'],
                                                accepted_identity=identity, **authority)
    if not outer:
        rows, receipt = strip(rows, receipt)
    license = selected.get('license')
    if license is not None:
        if any(row.get('license') != license for row in rows):
            raise PipelineError('public row license differs from selection')
        rows = [{k: v for k, v in row.items() if k != 'license'} for row in rows]
    elif any('license' in row for row in rows):
        raise PipelineError('public row has a license absent from selection')
    return rows, receipt


def check_projection_item(root: Path, selected: dict, rows: list, receipt: dict) -> list[str]:
    import importlib
    from .selection import resolve_acceptance_path
    module = importlib.import_module(f"ocd_kernel.projection.categories.{selected['category']}")
    checker = getattr(module, f"verify_accepted_{selected['category']}")
    return checker(root, acceptance_path=resolve_acceptance_path(root, selected['acceptance_path']),
                   rows=rows, receipt=receipt)


def verify_release_item(root: Path, selected: dict, rows: list, receipt: dict,
                        transform: dict | None) -> list[str]:
    from .selection import resolve_acceptance_path
    from .rights import require_release_rights
    from .public_allowlist import _scan
    from ocd_kernel.library._common import load_json
    accepted = load_json(resolve_acceptance_path(root, selected['acceptance_path']))
    require_release_rights(root, selected, accepted['identity'], rows)
    errors = _scan(rows, f"item {selected['item_id']} public rows")
    base, proof = restore_release_item(root, selected, rows, receipt, transform)
    return errors + check_projection_item(root, selected, base, proof)


def _verify_release_v2(root, release, *, selection=None, progress=None) -> dict[str, Any]:
    """Independently check the tree against the caller's original selection.

    Never invoke an assembler or projector. Category checkers re-read the
    promoted authority; internal receipts and selection hashes cannot authorize
    a changed request. Failed requested items keep the whole release failed.
    """
    import importlib
    from ocd_kernel.library._common import PipelineError, load_json
    from .selection import validate_release_selection, validate_work_cohort, resolve_acceptance_path
    from .streaming import file_sha256, iter_jsonl
    from .build_state import MANIFEST, READER, READY, check_inputs, check_ranges, check_ready
    from itertools import islice

    errors: list[str] = []
    rows_by_category = {}
    if selection is None:
        return {"status": "fail", "errors": ["original external selection is required"]}
    try:
        request = validate_release_selection(selection)
        root_path = Path(root).resolve(strict=True)
        item_work_ids = validate_work_cohort(root_path, request)
        target_keys = [(item["category"], str(resolve_acceptance_path(root_path, item["acceptance_path"])).casefold())
                       for item in request["items"]]
        if len(set(target_keys)) != len(target_keys):
            raise PipelineError("duplicate resolved release target")
        release_input = Path(release).absolute()
        if _release_is_reparse(release_input):
            raise PipelineError("release root cannot be a reparse point")
        directory = release_input.resolve(strict=True)
        files: set[str] = set()
        pending = [directory]
        while pending:
            folder = pending.pop()
            for path in folder.iterdir():
                if _release_is_reparse(path):
                    raise PipelineError("release cannot contain reparse points")
                if path.is_dir():
                    pending.append(path)
                elif path.is_file():
                    files.add(path.relative_to(directory).as_posix())
                else:
                    raise PipelineError("release contains a nonregular entry")
        stored = load_json(directory / "internal/release-selection.json")
        if stored != request:
            errors.append("stored selection differs from original external selection")
        report = load_json(directory / "internal/release-report.json")
        shape = _schema_diagnostics(report, schema_name="release-report.schema.json", label="release report")
        if shape:
            return {"status": "fail", "errors": errors + shape}
        if report["release_id"] != request["release_id"]:
            errors.append("release identity differs from selection")
        if report["selection_sha256"] != _sha256_bytes(_canonical_bytes(request)):
            errors.append("selection digest differs")
        actual_items = report["items"]
        if [i["item_id"] for i in actual_items] != [i["item_id"] for i in request["items"]]:
            raise PipelineError("release items do not account for original selection exactly once in order")
        expected_files = {"internal/release-selection.json", "internal/release-report.json",
                          "internal/checks/independent-check.json"}
        manifest = None
        if MANIFEST in files:
            expected_files.add(MANIFEST)
            manifest = load_json(directory / MANIFEST)
            check_inputs(root_path, request, manifest["inputs"])
            check_ranges(directory, report, manifest)
            from .resume import check_checkpoints
            expected_files.update(check_checkpoints(directory, request, manifest, report))
            if READY in files:
                expected_files.add(READY)
                check_ready(directory)
        if READER in files:
            expected_files.add(READER)
            reader = load_json(directory / READER)
            if (reader.get("status") not in {"pass", "reader-only-pass"}
                    or reader.get("release_report_sha256") != file_sha256(directory / "internal/release-report.json")):
                errors.append("reader evidence differs from release report")
        if "work_coverage" in request:
            expected_files.add("internal/work-coverage.json")
            expected_works = []
            for work_id in request["work_coverage"]["included_work_ids"]:
                text_items = [
                    {"item_id": item["item_id"], "status": item["status"]}
                    for item in actual_items
                    if item_work_ids.get(item["item_id"]) == work_id
                ]
                statuses = {entry["status"] for entry in text_items}
                disposition = (
                    "failed_text_selection" if "failed" in statuses else
                    "warned_text" if "warned" in statuses else
                    "included_text" if text_items else
                    "no_accepted_text_selected"
                )
                expected_works.append({
                    "work_id": work_id, "disposition": disposition,
                    "text_items": text_items,
                })
            expected_coverage = {
                "schema_version": "1.0",
                "selected_works": expected_works,
                "excluded_works": request["work_coverage"]["excluded_works"],
            }
            if (directory / "internal/work-coverage.json").read_bytes() != _canonical_bytes(expected_coverage):
                errors.append("private work coverage differs from canonical selection and verified item accounting")
        configurations = report["configurations"]
        from .notices import selected_notice_texts
        notices = selected_notice_texts(root_path, request["items"], actual_items)
        if configurations:
            from .public_allowlist import render_dataset_card
            expected_files.add("public/README.md")
            if (directory / "public/README.md").read_bytes() != render_dataset_card(configurations, notices=notices).encode("utf-8"):
                errors.append("public dataset card differs from original selection and bound notices")
        if len({c["category"] for c in configurations}) != len(configurations):
            raise PipelineError("duplicate release configuration")
        row_counts = {}

        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise PipelineError(f"duplicate public row key: {key}")
                result[key] = value
            return result

        for config in configurations:
            category = config["category"]
            if progress is not None:
                progress('verifying-configuration', category=category)
            # Do not read a report-supplied path before checking its exact shape.
            expected_path = f"public/data/{category}/train.jsonl"
            if category not in {"prose", "quotations", "devotionals", "bible", "commentary", "topical_indexes",
                                "sermons", "hymns", "liturgies", "poetry", "catechisms",
                                "doctrinal_documents", "reference_entries", "prayers"} or config["path"] != expected_path:
                raise PipelineError("unsupported or unsafe configuration path")
            path = directory / expected_path
            count = sum(1 for _ in iter_jsonl(path, canonical=True))
            if not count:
                raise PipelineError("configuration requires nonempty object rows")
            if config["row_count"] != count or config["sha256"] != file_sha256(path):
                errors.append("configuration row count or digest differs")
            rows_by_category[category] = iter_jsonl(path, canonical=True)
            row_counts[category] = count
            expected_files.add(expected_path)
            if "typed_companion" in config:
                if config["typed_companion"]["path"] != f"public/data/{category}/train.arrow":
                    raise PipelineError("unsafe typed companion path")
                expected_files.add(config["typed_companion"]["path"])
        offsets = {category: 0 for category in rows_by_category}
        if configurations:
            from .public_allowlist import check_public_boundary
            errors.extend(check_public_boundary(directory, report, require_success=False, notices=notices))
        used_categories = set()
        for index, (requested, item) in enumerate(zip(request["items"], actual_items, strict=True)):
            if progress is not None:
                progress('verifying-item', item_id=requested['item_id'], completed=index, total=len(actual_items))
            if any(item[k] != requested[k] for k in ("item_id", "category", "acceptance_path")):
                raise PipelineError("release item identity differs from selection")
            status = item["status"]
            if "exclude_reason" in requested:
                if status != "excluded" or item["reasons"] != [requested["exclude_reason"]]:
                    errors.append("explicit exclusion differs from original request")
            elif status == "excluded":
                errors.append("unrequested exclusion")
            if status in {"excluded", "failed"}:
                if item["row_count"] != 0 or item["receipt_path"] is not None or not item["reasons"]:
                    errors.append("nonincluded item has rows, receipt or missing reason")
                continue
            accepted = load_json(resolve_acceptance_path(root_path, item["acceptance_path"]))
            identity = accepted.get("identity")
            if "work_coverage" in request:
                if not isinstance(identity, dict) or identity.get("work_id") != item_work_ids[item["item_id"]]:
                    errors.append(f"{item['item_id']}: selected work_id differs from accepted identity")
            category = item["category"]
            if category not in rows_by_category or item["row_count"] <= 0:
                raise PipelineError("included item has no configuration rows")
            used_categories.add(category)
            expected_receipt = f"internal/projection-receipts/{item['item_id']}.json"
            if item["receipt_path"] != expected_receipt:
                raise PipelineError("receipt path differs from canonical item path")
            expected_files.add(expected_receipt)
            receipt = load_json(directory / expected_receipt)
            begin = offsets[category]
            end = begin + item["row_count"]
            rows = list(islice(rows_by_category[category], item["row_count"]))
            if len(rows) != item["row_count"]:
                raise PipelineError("configuration rows truncated within selected item")
            offsets[category] = end
            transform_path = f"internal/public-row-transforms/{item['item_id']}.json"
            transform = None
            if transform_path in files:
                expected_files.add(transform_path)
                transform = load_json(directory / transform_path)
            errors.extend(f"{item['item_id']}: {message}" for message in
                          verify_release_item(root_path, requested, rows, receipt, transform))
            warnings = receipt.get("warnings", [])
            reasons = [v if isinstance(v, str) else _canonical_bytes(v).decode().strip() for v in warnings]
            if status != ("warned" if warnings else "included") or item["reasons"] != reasons:
                errors.append("included/warned accounting differs from verified receipt")
            if progress is not None:
                progress('verified-item', item_id=requested['item_id'], completed=index + 1, total=len(actual_items))
        if used_categories != set(rows_by_category) or any(offsets[c] != row_counts[c] for c in offsets):
            errors.append("configuration rows not fully accounted for")
        if [c["category"] for c in configurations] != sorted(used_categories):
            errors.append("configuration inventory/order differs")
        accounting = {"requested": len(request["items"])}
        accounting.update({name: sum(item["status"] == name for item in actual_items)
                           for name in ("included", "warned", "failed", "excluded")})
        if report["accounting"] != accounting:
            errors.append("release accounting differs")
        expected_status = "fail" if accounting["failed"] else "pass"
        if report["status"] != expected_status:
            errors.append("release status differs from accounting")
        if files != expected_files:
            errors.append("release file set differs from accounted outputs")
        if accounting["failed"]:
            errors.append("release contains failed items")
        stored_check = load_json(directory / "internal/checks/independent-check.json")
        actual_check = {"status": "fail" if errors else "pass", "errors": list(errors)}
        if stored_check != actual_check:
            errors.append("stored independent check differs from fresh verification")
    except (PipelineError, OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(f"release verification failed: {exc}")
    finally:
        for iterator in rows_by_category.values():
            iterator.close()
    return {"status": "fail" if errors else "pass", "errors": errors}


def _release_is_reparse(path: Path) -> bool:
    """Detect symlinks and Windows reparse points on supported Python 3.11+."""
    import stat
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def verify_release_v2(root, release, *, selection=None, progress=None) -> dict[str, Any]:
    """Independently verify a release with a fresh catalog scan for this phase."""
    from ocd_kernel.library.identities import cached_edition_lookups

    with cached_edition_lookups():
        return _verify_release_v2(root, release, selection=selection, progress=progress)
