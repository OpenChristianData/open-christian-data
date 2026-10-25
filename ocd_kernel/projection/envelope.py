"""The common public row envelope for the provisional prose projection."""

from __future__ import annotations
from ocd_kernel.projection.scripture_authority import BOOK_CODES_PATH, load_book_codes
from ocd_kernel.projection.scripture_targets import normalize_reference_record


from typing import Any
from pathlib import Path

from ocd_kernel.library._common import canonical_bytes, sha256_bytes


def row_text_hash(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def make_row(
    *,
    record_id: str,
    sequence: int,
    work_id: str,
    textual_form_id: str,
    edition_id: str,
    category: str,
    language: str,
    text: str,
    locator: dict[str, Any],
    provenance: dict[str, Any],
    representation_revision: str,
    notes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "record_id": record_id,
        "sequence": sequence,
        "work_id": work_id,
        "textual_form_id": textual_form_id,
        "edition_id": edition_id,
        "category": category,
        "language": language,
        "text": text,
        "locator": locator,
        "provenance": provenance,
        "representation_revision": representation_revision,
    }
    if notes:
        row["notes"] = notes
    return row


def canonical_row_bytes(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(canonical_bytes(row) for row in rows)


# TEI-004 is a separate, provisional contract. The PIPE-001 API above remains
# available until its consumer cutover ticket runs.
def project_document(
    tei_path: Path, *, identity: dict[str, str], language: str,
    representation_revision: str, edition_title: str, scope_id: str | None = None,
) -> dict[str, Any]:
    """Map a document for correspondence experiments, not master acceptance.

    Call project_accepted for an authority-checked master. This pure mapper has
    no release or publication side effects and accepts no caller-supplied rows
    or locators. Unsupported semantics fail before any result is returned.
    """
    import json
    import re
    import xml.etree.ElementTree as ET
    from pathlib import Path
    from ocd_kernel.library._common import PipelineError, sha256_file

    ns = "{http://www.tei-c.org/ns/1.0}"
    xid = "{http://www.w3.org/XML/1998/namespace}id"
    xlang = "{http://www.w3.org/XML/1998/namespace}lang"
    path = Path(tei_path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PipelineError(f"cannot read TEI {path}: {exc}") from exc
    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise PipelineError("unsupported-visible: DTD or entity declaration")

    class NoDoctype(ET.TreeBuilder):
        def doctype(self, name, pubid, system):
            raise PipelineError("unsupported-visible: DTD or entity declaration")

        def comment(self, text):
            # Approved comments are separately bound to the private inventory.
            return None

        def pi(self, target, text):
            raise PipelineError("unsupported-visible: processing instruction")

    try:
        root = ET.fromstring(raw, parser=ET.XMLParser(target=NoDoctype()))
    except ET.ParseError as exc:
        raise PipelineError(f"invalid TEI: {exc}") from exc
    comment_inventory = []
    if b"<!--" in raw:
        # ElementTree deliberately excludes comments from the row mapper. Independently
        # retain the exact location and content of the source's bounded notice and
        # generated index markers in the private correspondence receipt.
        from lxml import etree
        try:
            comment_root = etree.fromstring(
                raw, etree.XMLParser(resolve_entities=False, load_dtd=False,
                                     no_network=True, remove_comments=False, recover=False)
            )
        except (etree.XMLSyntaxError, ValueError) as exc:
            raise PipelineError(f"invalid TEI comment accounting: {exc}") from exc
        comment_nodes = list(comment_root.xpath(".//comment()"))
        before = comment_root.getprevious()
        while before is not None:
            comment_nodes.append(before)
            before = before.getprevious()
        after = comment_root.getnext()
        while after is not None:
            comment_nodes.append(after)
            after = after.getnext()
        comment_inventory = []
        for comment in comment_nodes:
            if not isinstance(comment, etree._Comment):
                continue
            body = comment.text or ""
            prolog = comment.getparent() is None
            index_marker = (
                body.strip() in {"added reason=\"insertIndex\" class=\"scripRef\"",
                                 "Start of automatically inserted scripRef index",
                                 "End of scripRef index", "/added"}
            )
            if (not (prolog and body.strip().startswith("Copyright "))
                    and not index_marker) or (comment.tail or "").strip():
                raise PipelineError("unsupported-visible: XML comment is not an accounted source marker")
            comment_inventory.append({
                "tei_path": "comment:" + comment.getroottree().getpath(comment),
                "disposition": "private-header" if prolog else "structure",
                "attributes": {},
                "text_sha256": row_text_hash(body),
                "tail_sha256": row_text_hash(comment.tail or ""),
            })
    if root.tag != ns + "TEI" or any(
        not isinstance(node.tag, str) or not node.tag.startswith(ns)
        for node in root.iter()
    ):
        raise PipelineError("unsupported-visible: non-TEI element")
    if [node.tag for node in root] != [ns + "teiHeader", ns + "text"]:
        raise PipelineError("unsupported-visible: root requires header then text")
    if set(identity) != {"work_id", "textual_form_id", "edition_id"}:
        raise PipelineError("public identity requires exactly work, form, and edition")
    if any(
        not isinstance(value, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value)
        for value in identity.values()
    ):
        raise PipelineError("invalid public identity")
    if not isinstance(language, str) or not re.fullmatch(
        r"[a-zA-Z]{2,8}(-[a-zA-Z0-9]{1,8})*", language
    ):
        raise PipelineError("invalid sidecar language")
    if any(
        not isinstance(value, str) or not value.strip()
        for value in (edition_title, representation_revision)
    ):
        raise PipelineError("missing edition title or representation revision")
    if scope_id is not None and (
        not isinstance(scope_id, str) or not scope_id.strip()
    ):
        raise PipelineError("invalid projection scope")

    schema_path = Path(__file__).resolve().parents[2] / "schemas/v2/public-row.schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        policy = schema.get("x-ocd-projection-policy")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PipelineError(f"cannot load projection policy: {exc}") from exc
    if not isinstance(policy, dict) or policy.get("version") != "3":
        raise PipelineError("unsupported-visible: missing projection policy v3")

    def policy_strings(value: Any, label: str) -> list[str]:
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item for item in value
        ):
            raise PipelineError(f"invalid projection policy {label}")
        return value

    def policy_string(value: Any, label: str) -> str:
        if not isinstance(value, str) or not value:
            raise PipelineError(f"invalid projection policy {label}")
        return value

    allowed = set(policy_strings(policy.get("allowed_elements"), "allowed_elements"))
    text_parts = tuple(policy_strings(policy.get("text_parts"), "text_parts"))
    carrier_parents = set(
        policy_strings(policy.get("carrier_parents"), "carrier_parents")
    )
    container_elements = set(
        policy_strings(policy.get("container_elements"), "container_elements")
    )
    scope_elements = set(
        policy_strings(policy.get("scope_elements"), "scope_elements")
    )
    block_parent_elements = set(
        policy_strings(policy.get("block_parent_elements"), "block_parent_elements")
    )
    raw_attributes = policy.get("allowed_attributes")
    if not isinstance(raw_attributes, dict):
        raise PipelineError("invalid projection policy allowed_attributes")
    attrs = {
        element: set(policy_strings(values, f"allowed_attributes.{element}"))
        for element, values in raw_attributes.items()
    }
    raw_division_types = policy.get("division_types")
    if not isinstance(raw_division_types, dict):
        raise PipelineError("invalid projection policy division_types")
    excluded_types = set(
        policy_strings(
            raw_division_types.get("excluded_paratext"),
            "division_types.excluded_paratext",
        )
    )
    unsupported_types = set(
        policy_strings(
            raw_division_types.get("unsupported_prose"),
            "division_types.unsupported_prose",
        )
    )
    supported_types = set(
        policy_strings(
            raw_division_types.get("supported_prose"),
            "division_types.supported_prose",
        )
    )
    rendering = policy.get("rendering")
    if not isinstance(rendering, dict):
        raise PipelineError("invalid projection policy rendering")
    paragraph_element = policy_string(
        rendering.get("paragraph_element"), "rendering.paragraph_element"
    )
    heading_element = policy_string(
        rendering.get("heading_element"), "rendering.heading_element"
    )
    division_element = policy_string(
        rendering.get("division_element"), "rendering.division_element"
    )
    note_element = policy_string(
        rendering.get("note_element"), "rendering.note_element"
    )
    line_break_element = policy_string(
        rendering.get("line_break_element"), "rendering.line_break_element"
    )
    script_element = policy_string(
        rendering.get("script_element"), "rendering.script_element"
    )
    reference_elements = set(
        policy_strings(rendering.get("reference_elements"), "rendering.reference_elements")
    )
    omitted_elements = set(
        policy_strings(rendering.get("omitted_elements"), "rendering.omitted_elements")
    )
    milestone_elements = set(
        policy_strings(rendering.get("milestone_elements"), "rendering.milestone_elements")
    )
    break_no_value = policy_string(
        rendering.get("break_no_value"), "rendering.break_no_value"
    )
    if not omitted_elements <= allowed or not milestone_elements <= allowed:
        raise PipelineError("invalid projection policy rendering element")

    script_policy = policy.get("script")
    if not isinstance(script_policy, dict):
        raise PipelineError("invalid projection policy script")
    script_styles = set(policy_strings(script_policy.get("styles"), "script.styles"))
    raw_script_maps = script_policy.get("maps")
    if not isinstance(raw_script_maps, dict):
        raise PipelineError("invalid projection policy script.maps")
    script_maps: dict[str, dict[str, str]] = {}
    for style in script_styles:
        raw_map = raw_script_maps.get(style)
        if not isinstance(raw_map, dict) or not all(
            isinstance(key, str)
            and key
            and isinstance(value, str)
            and value
            for key, value in raw_map.items()
        ):
            raise PipelineError(f"invalid projection policy script.maps.{style}")
        script_maps[style] = dict(raw_map)
    safe_punctuation = set(
        policy_strings(script_policy.get("safe_punctuation"), "script.safe_punctuation")
    )
    if not isinstance(script_policy.get("allow_whitespace"), bool):
        raise PipelineError("invalid projection policy script.allow_whitespace")
    allow_script_whitespace = script_policy["allow_whitespace"]
    raw_warning_reasons = policy.get("warning_reasons")
    if not isinstance(raw_warning_reasons, dict):
        raise PipelineError("invalid projection policy warning_reasons")
    warning_reasons = {
        key: policy_string(value, f"warning_reasons.{key}")
        for key, value in raw_warning_reasons.items()
    }
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
    if not required_warning_keys <= set(warning_reasons):
        raise PipelineError("invalid projection policy warning_reasons")

    values_path = Path(__file__).resolve().parents[2] / "schemas/v2/tei/controlled-values.json"
    try:
        values = json.loads(values_path.read_text(encoding="utf-8"))
        vocabulary = {item["context"]: item["values"] for item in values["contexts"]}
    except (KeyError, TypeError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PipelineError(f"cannot load TEI controlled values: {exc}") from exc
    controlled_divisions = set(vocabulary.get("div/@type", []))
    policy_divisions = excluded_types | unsupported_types | supported_types
    if (
        not controlled_divisions
        or policy_divisions != controlled_divisions
        or excluded_types & unsupported_types
        or excluded_types & supported_types
        or unsupported_types & supported_types
    ):
        raise PipelineError(
            "projection policy does not exhaustively classify controlled div/@type values"
        )

    def norm(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()

    def name(node: Any) -> str:
        tag = node.tag
        return tag[len(ns) :] if isinstance(tag, str) and tag.startswith(ns) else tag

    parents = {child: node for node in root.iter() for child in node}
    paths = {root: "/TEI[1]"}
    for node in root.iter():
        counts: dict[str, int] = {}
        for child in node:
            k = name(child)
            counts[k] = counts.get(k, 0) + 1
            paths[child] = f"{paths[node]}/{k}[{counts[k]}]"
    ids: dict[str, Any] = {}
    for node in root.iter():
        if xid in node.attrib and not node.get(xid):
            raise PipelineError(f"unsupported-visible: empty xml:id at {paths[node]}")
        if xlang in node.attrib and not re.fullmatch(
            r"[a-zA-Z]{2,8}(-[a-zA-Z0-9]{1,8})*", node.get(xlang) or ""
        ):
            raise PipelineError(f"unsupported-visible: invalid xml:lang at {paths[node]}")
        if node.get(xid):
            value = node.get(xid)
            if value in ids:
                raise PipelineError(f"unsupported-visible: duplicate TEI xml:id at {paths[node]}")
            ids[value] = node
    texts = root.findall(ns + "text")
    if len(texts) != 1:
        raise PipelineError("unsupported-visible: exactly one text required")
    text_root = texts[0]
    if len(list(root.iter(ns + "text"))) != 1:
        raise PipelineError("unsupported-visible: nested text")
    text_children = [name(node) for node in text_root]
    if text_children not in (
        ["body"],
        ["front", "body"],
        ["body", "back"],
        ["front", "body", "back"],
    ):
        raise PipelineError("unsupported-visible: text requires ordered front/body/back")
    scope = ids.get(scope_id) if scope_id else text_root
    if (
        scope is None
        or scope not in set(text_root.iter())
        or name(scope) not in scope_elements
    ):
        raise PipelineError("invalid projection scope")
    selected = set(scope.iter())

    def ancestors(node: Any) -> list[Any]:
        out: list[Any] = []
        current = node
        while current in parents:
            current = parents[current]
            out.insert(0, current)
        return out

    excluded = {
        node
        for node in text_root.iter()
        if any(
            name(ancestor) == division_element
            and ancestor.get("type") in excluded_types
            for ancestor in ancestors(node) + [node]
        )
    }
    private_attributes = {"div": {"prev", "ana"}, "pb": {"facs"}}

    def check_private_attribute(node: Any, kind: str, attribute: str, value: str) -> None:
        """Admit source navigation only with exact private inventory accounting."""
        from urllib.parse import urlsplit
        from pathlib import PurePosixPath

        location = paths[node]
        if not value or value != value.strip() or any(char.isspace() for char in value):
            raise PipelineError(f"unsupported-visible: malformed {kind}/@{attribute} at {location}")
        if attribute == "ana":
            if re.fullmatch(r"source-tag:[A-Za-z][A-Za-z0-9._-]*", value) is None:
                raise PipelineError(f"unsupported-visible: malformed div/@ana at {location}")
        elif attribute == "prev":
            if value.startswith("#"):
                target = ids.get(value[1:])
                if target is None or name(target) != "div" or target is node:
                    raise PipelineError(f"unsupported-visible: unresolved div/@prev at {location}")
            else:
                parsed = urlsplit(value)
                if parsed.scheme != "https" or not parsed.netloc or not parsed.fragment:
                    raise PipelineError(f"unsupported-visible: malformed div/@prev at {location}")
        elif attribute == "facs":
            parsed = urlsplit(value)
            if parsed.scheme or parsed.netloc or not value.startswith("/") or value.startswith("//") or ".." in PurePosixPath(parsed.path).parts:
                raise PipelineError(f"unsupported-visible: malformed pb/@facs at {location}")

    for node in text_root.iter():
        k = name(node)
        if k not in allowed:
            raise PipelineError(f"unsupported-visible: {k} at {paths[node]}")
        if k == division_element and node.get("type") in unsupported_types:
            raise PipelineError(
                f"unsupported-visible: category semantics {node.get('type')} at {paths[node]}"
            )
        if k == line_break_element and node.get("break") not in {None, "yes", break_no_value}:
            raise PipelineError(f"unsupported-visible: {k}/@break at {paths[node]}")
        for attr, value in node.attrib.items():
            if attr in private_attributes.get(k, set()):
                check_private_attribute(node, k, attr, value)
            elif attr not in attrs.get(k, set()) | {xid, xlang}:
                raise PipelineError(f"unsupported-visible: {k}/@{attr} at {paths[node]}")
            context = f"{k}/@{attr}"
            if context in vocabulary and value not in vocabulary[context]:
                raise PipelineError(f"unsupported-visible: {context}={value} at {paths[node]}")
        parent_kind = name(parents[node])
        if k in text_parts and parent_kind != "text":
            raise PipelineError("unsupported-visible: nested text container")
        if k in {paragraph_element, heading_element, division_element} and parent_kind not in block_parent_elements:
            if not (k == paragraph_element and parent_kind == note_element):
                raise PipelineError(f"unsupported-visible: nested block at {paths[node]}")
        if k == note_element and any(
            name(ancestor) in {note_element, heading_element} for ancestor in ancestors(node)
        ):
            raise PipelineError(f"unsupported-visible: nested or heading note at {paths[node]}")
        if k in container_elements:
            if norm(node.text or "") or any(norm(child.tail or "") for child in node):
                raise PipelineError(f"unsupported-visible: unwrapped container text at {paths[node]}")
        if k in milestone_elements and (len(node) or norm(node.text or "")):
            raise PipelineError(f"unsupported-visible: nonempty milestone at {paths[node]}")

    ambiguous_boundary = "\x00"

    def script_text(value: str, style: str | None, owner: Any) -> str:
        if style is None or not value:
            return value
        mapping = script_maps[style]
        pieces: list[str] = []
        for character in value:
            if character in mapping:
                pieces.append(mapping[character])
            elif character.isspace() and allow_script_whitespace:
                pieces.append(character)
            elif character in safe_punctuation:
                pieces.append(character)
            else:
                raise PipelineError(
                    f"unsupported-visible: unsupported {style} script character "
                    f"{character!r} at {paths[owner]}"
                )
        return "".join(pieces)

    def content(node: Any, omit_notes: bool = True, script_style: str | None = None) -> str:
        current_script = script_style
        if name(node) == script_element and node.get("rend") in script_styles:
            declared_script = node.get("rend")
            if current_script is not None:
                raise PipelineError(
                    f"unsupported-visible: nested script styles at {paths[node]}"
                )
            current_script = declared_script
        out = [script_text(node.text or "", current_script, node)]
        for child in node:
            k = name(child)
            if k == note_element and omit_notes:
                out.append(ambiguous_boundary)
            elif k in omitted_elements:
                out.append(ambiguous_boundary)
            elif k == line_break_element:
                out.append("" if child.get("break") == break_no_value else " ")
            else:
                out.append(content(child, omit_notes, current_script))
                if k == paragraph_element:
                    out.append(" ")
            out.append(script_text(child.tail or "", current_script, child))
        return "".join(out)

    def rendered(node: Any, *, omit_notes: bool = True) -> str:
        value = re.sub("\x00+", ambiguous_boundary, content(node, omit_notes))
        for index, character in enumerate(value):
            if character != ambiguous_boundary:
                continue
            previous = value[index - 1] if index else ""
            following = value[index + 1] if index + 1 < len(value) else ""
            if previous.isalnum() and following.isalnum():
                raise PipelineError(
                    "unsupported-visible: omitted inline element creates an "
                    f"ambiguous alphanumeric boundary at {paths[node]}"
                )
        return norm(value.replace(ambiguous_boundary, ""))

    all_carriers = [
        node
        for node in text_root.iter()
        if name(node) == paragraph_element
        and name(parents[node]) in carrier_parents
    ]
    global_ordinals = {node: index for index, node in enumerate(all_carriers, start=1)}
    carriers = [
        node
        for node in all_carriers
        if node in selected and node not in excluded
    ]
    rows: list[dict[str, Any]] = []
    anchors: list[dict[str, Any]] = []
    row_for: dict[Any, str] = {}
    row_texts: dict[Any, str] = {}
    rows_by_id: dict[str, dict[str, Any]] = {}

    def text_part(node: Any) -> str:
        parts = [ancestor for ancestor in ancestors(node) if name(ancestor) in text_parts]
        if len(parts) != 1:
            raise PipelineError(f"unsupported-visible: carrier has no unique text part at {paths[node]}")
        return name(parts[0])

    def direct_headings(node: Any) -> list[Any]:
        return [child for child in node if name(child) == heading_element]

    used_headings: set[Any] = set()
    for carrier in carriers:
        for ancestor in ancestors(carrier):
            if name(ancestor) in {division_element, *text_parts}:
                used_headings.update(direct_headings(ancestor))

    for sequence, node in enumerate(carriers, start=1):
        rid = f"{identity['edition_id']}:unit-{global_ordinals[node]:06d}"
        for descendant in node.iter():
            row_for[descendant] = rid
        ancestor_divisions = [
            ancestor for ancestor in ancestors(node) if name(ancestor) == division_element
        ]
        divisions = []
        for division in ancestor_divisions:
            parent = parents[division]
            siblings = [child for child in parent if name(child) == division_element]
            divisions.append(
                {
                    "order": siblings.index(division) + 1,
                    "type": division.get("type"),
                    "titles": [rendered(heading) for heading in direct_headings(division)],
                }
            )
        part = next(
            ancestor for ancestor in reversed(ancestors(node)) if name(ancestor) in text_parts
        )
        row_text = rendered(node)
        row_texts[node] = row_text
        row_language = next(
            (
                ancestor.get(xlang)
                for ancestor in [node] + list(reversed(ancestors(node)))
                if ancestor.get(xlang)
            ),
            language,
        )
        row = dict(
            identity,
            record_id=rid,
            sequence=sequence,
            category="prose",
            language=row_language,
            representation_revision=representation_revision,
            text=row_text,
            locator={
                "kind": "paragraph",
                "text_part": name(part),
                "part_titles": [rendered(heading) for heading in direct_headings(part)],
                "divisions": divisions,
                "paragraph": [
                    child for child in parents[node] if name(child) == paragraph_element
                ].index(node)
                + 1,
            },
            provenance={"edition_title": edition_title},
            notes=[
                {
                    "text": rendered(note, omit_notes=False),
                    "place": note.get("place", "unspecified"),
                    "label": note.get("n", ""),
                }
                for note in node.iter()
                if name(note) == note_element
            ],
            references=[],
        )
        rows.append(row)
        rows_by_id[rid] = row
        anchors.append(
            {
                "record_id": rid,
                "tei_path": paths[node],
                "text_sha256": row_text_hash(row_text),
            }
        )

    note_index = {
        note: index
        for carrier in carriers
        for index, note in enumerate(
            (node for node in carrier.iter() if name(node) == note_element), start=1
        )
    }
    book_codes = load_book_codes()
    references: list[dict[str, Any]] = []
    for node in text_root.iter():
        if name(node) not in reference_elements:
            continue
        has_target = "target" in node.attrib
        has_cref = "cRef" in node.attrib
        if has_target == has_cref:
            raise PipelineError(
                f"unsupported-visible: reference requires exactly one of @target or @cRef at {paths[node]}"
            )
        target = node.get("target") if has_target else node.get("cRef")
        if not target or target != target.strip() or len(target.split()) != 1:
            raise PipelineError(
                f"unsupported-visible: reference requires one unambiguous locator at {paths[node]}"
            )
        if not has_target and target.startswith("#"):
            raise PipelineError(
                f"unsupported-visible: cRef cannot identify a local TEI target at {paths[node]}"
            )
        if node.get("type") == "note" and (
            not has_target or not target.startswith("#")
        ):
            raise PipelineError(
                f"unsupported-visible: note references require @target with a complete local target at {paths[node]}"
            )
        if has_target and target.startswith("#"):
            destination = ids.get(target[1:])
            if destination is None:
                raise PipelineError(
                    f"unresolved complete-TEI target: {target} at {paths[node]}"
                )
            if node.get("type") == "note" and name(destination) != note_element:
                raise PipelineError(
                    f"note pointer target is not a note: {target} at {paths[node]}"
                )
            resolved = "in-projection" if destination in row_for else "outside-projection"
            target_row = row_for.get(destination)
        else:
            resolved, target_row = "external", None
        target_note = (
            note_index.get(ids.get(target[1:]))
            if has_target and target.startswith("#")
            else None
        )
        source_note = next(
            (note_index[ancestor] for ancestor in ancestors(node) if ancestor in note_index),
            None,
        )
        reference = {
            "tei_path": paths[node],
            "original_target": target,
            "resolution": resolved,
            "target_record_id": target_row,
            "target_note": target_note,
            "source_note": source_note,
        }
        references.append(reference)
        owner = row_for.get(node)
        if owner is not None:
            rows_by_id[owner]["references"].append(
                {
                    "label": rendered(node),
                    **({"source_target": target} if resolved == "external" else {}),
                    **({key: value for key, value in normalize_reference_record({"target": target}, book_codes=book_codes).items() if key in ("scripture", "normalization_status")} if resolved == "external" else {}),
                    "resolution": resolved,
                    "target_record_id": target_row,
                    "target_note": target_note,
                    "source_note": source_note,
                }
            )

    inventory: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    text_nodes = set(text_root.iter())
    for node in root.iter():
        if node not in text_nodes:
            disposition = "private-header"
        elif any(ancestor in used_headings for ancestor in ancestors(node) + [node]):
            disposition = "locator-heading"
        elif node not in selected:
            disposition = "outside-scope"
        elif node in excluded:
            disposition = "excluded-paratext"
        elif node in row_for:
            disposition = "row-content"
        elif any(
            name(ancestor) == heading_element
            for ancestor in ancestors(node) + [node]
        ):
            disposition = (
                "locator-heading"
                if any(
                    ancestor in used_headings
                    for ancestor in ancestors(node) + [node]
                )
                else "excluded-heading"
            )
        elif name(node) in container_elements:
            disposition = "structure"
        else:
            raise PipelineError(f"unsupported-visible: unassigned element at {paths[node]}")
        inventory.append(
            {
                "tei_path": paths[node],
                "disposition": disposition,
                "attributes": dict(sorted(node.attrib.items())),
                "text_sha256": row_text_hash(node.text or ""),
                "tail_sha256": row_text_hash(node.tail or ""),
            }
        )
        if disposition in {"outside-scope", "excluded-paratext", "excluded-heading"}:
            exclusions.append({"tei_path": paths[node], "reason": disposition})
        if disposition in {"row-content", "locator-heading"}:
            kind = name(node)
            reason = None
            if kind == script_element:
                reason = (
                    warning_reasons["script"]
                    if node.get("rend") in script_styles
                    else warning_reasons["styling"]
                )
            elif kind == "foreign":
                reason = warning_reasons["language_span"]
            elif kind == "seg":
                reason = warning_reasons["segmentation"]
            elif kind == note_element:
                reason = warning_reasons["note"]
            elif kind == line_break_element:
                reason = (
                    warning_reasons["line_break_omitted"]
                    if node.get("break") == break_no_value
                    else warning_reasons["line_break_space"]
                )
            elif kind in milestone_elements:
                reason = warning_reasons["milestone"]
            if reason is not None:
                warnings.append({"tei_path": paths[node], "reason": reason})
        if node in carriers and not row_texts[node]:
            warnings.append(
                {"tei_path": paths[node], "reason": "empty-native-paragraph"}
            )

    inventory.extend(sorted(comment_inventory, key=lambda item: item["tei_path"]))

    import jsonschema

    validator = jsonschema.Draft202012Validator(schema)
    for row in rows:
        errors = list(validator.iter_errors(row))
        if errors:
            raise PipelineError(
                f"invalid public row {row['record_id']}: {errors[0].message}"
            )
    return {
        "rows": rows,
        "anchors": anchors,
        "inventory": inventory,
        "references": references,
        "warnings": warnings,
        "exclusions": exclusions,
        "master_sha256": sha256_file(path),
        "book_codes_sha256": sha256_file(BOOK_CODES_PATH),
        "scope_id": scope_id,
        "mapping_version": "ocd-common-prose-provisional-v4",
    }


def project_accepted(root: Path, *, acceptance_path: Path) -> dict[str, Any]:
    """Derive projection inputs from validated promoted TEI and upstream sidecars."""
    from pathlib import Path
    from ocd_kernel.library._common import PipelineError, sha256_file
    from ocd_kernel.library.identities import edition_by_id, resolve_edition_language
    from ocd_kernel.tei.acceptance import validate_acceptance
    import xml.etree.ElementTree as ET

    root = Path(root).resolve()
    acceptance_file = Path(acceptance_path).resolve()
    try:
        accepted = validate_acceptance(acceptance_file, root=root)
    except PipelineError:
        raise
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise PipelineError(
            f"cannot validate accepted projection evidence {acceptance_file}: {exc}"
        ) from exc
    if accepted["promotion"]["status"] != "promoted":
        raise PipelineError("projection requires a promoted accepted master")
    work, edition = edition_by_id(root, accepted["identity"]["edition_id"], work_id=accepted["identity"]["work_id"])
    try:
        header = ET.parse(edition.path).getroot().find(
            "{http://www.tei-c.org/ns/1.0}teiHeader"
        )
    except (ET.ParseError, OSError, ValueError) as exc:
        raise PipelineError(
            f"cannot read accepted master for projection {edition.path}: {exc}"
        ) from exc
    for key, value in accepted["identity"].items():
        spellings = {key, "ocd-" + key.replace("_", "-")}
        nodes = (
            []
            if header is None
            else [
                node
                for node in header.iter("{http://www.tei-c.org/ns/1.0}idno")
                if node.get("type") in spellings
            ]
        )
        if (not nodes or len({node.get("type") for node in nodes}) != len(nodes)
                or any("".join(node.itertext()).strip() != value for node in nodes)):
            raise PipelineError(f"accepted master requires exactly one consistent matching {key} per spelling")
    if edition.record.get("category", work.record.get("category")) != "prose":
        raise PipelineError("unsupported-visible: category requires its own mapping")
    projection = project_document(
        edition.path,
        identity={
            key: accepted["identity"][key]
            for key in ("work_id", "textual_form_id", "edition_id")
        },
        language=resolve_edition_language(work.record, edition.record, edition.textual_form_id),
        representation_revision=accepted["representation_revision"]["id"],
        edition_title=edition.title,
    )
    try:
        acquisition_relative = accepted["source"]["source_manifest"]["path"]
        if not isinstance(acquisition_relative, str) or not acquisition_relative:
            raise TypeError("source manifest path must be a nonempty string")
        bound_paths = {
            "acceptance": acceptance_file,
            "work": Path(work.path),
            "master": Path(edition.path),
            "acquisition": root / acquisition_relative,
        }
        authority: dict[str, dict[str, str]] = {}
        for key, candidate in bound_paths.items():
            path = candidate.resolve()
            try:
                relative = path.relative_to(root)
            except ValueError as exc:
                raise PipelineError(
                    f"accepted {key} evidence is outside repository root: {path}"
                ) from exc
            if not path.is_file():
                raise PipelineError(f"accepted {key} evidence is missing: {path}")
            try:
                digest = sha256_file(path)
            except OSError as exc:
                raise PipelineError(
                    f"cannot hash accepted {key} evidence {path}: {exc}"
                ) from exc
            authority[key] = {"path": relative.as_posix(), "sha256": digest}
    except PipelineError:
        raise
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise PipelineError(f"invalid accepted projection evidence paths: {exc}") from exc
    projection["authority"] = authority
    return projection
