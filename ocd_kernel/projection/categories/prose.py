"""Source-bound prose projection for PIPE-001.

This is intentionally a bounded provisional mapper.  It projects native
source paragraph boundaries and refuses to invent rows for an unsupported
structural family.  The later category ticket owns the adopted prose schema.
"""

from __future__ import annotations
from ocd_kernel.projection.native_content_check import projection_validator

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from lxml import etree
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ocd_kernel.library._common import PipelineError, io_path, sha256_file
from ocd_kernel.lib.path_io import resolve_path
from ocd_kernel.projection.envelope import make_row, row_text_hash

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
XML_LANG = f"{{{XML_NS}}}lang"
MAPPING_VERSION = "ocd-prose-mapping-provisional-v1"
ASSEMBLER_VERSION = "ocd-projection-assembler-provisional-v1"
_SAMUEL_IDENTITY = {
    'work_id': 'tyerman-life-times-samuel-wesley-1866',
    'textual_form_id': 'english',
    'edition_id': 'pg67980-1866-simpkin-marshall',
}
_SAMUEL_SOURCE = 'raw/gutenberg/67980/html/pg67980-images.html'
_SAMUEL_SOURCE_SHA = '98cca9b96a0e81ef16fc4409c2a37b6baba20ee64527456616670f7f3f906094'
_SAMUEL_TEXT_C14N_SHA = '427c1819cb53e948da2c66096915c6808b2bab8ec2a4d8cf44af0e5f1667c58c'
_SAMUEL_ACCEPTED_DRAFT_SHA = '193b6e6921df36eddb0f06c4dd815f05f11a78272754476fa69d3c0dd7617802'
_JOHN_IDENTITY = {'work_id': 'tyerman-life-times-john-wesley',
                  'textual_form_id': 'tyerman-life-times-john-wesley--retained-en',
                  'edition_id': 'tyerman-life-times-john-wesley--gutenberg-electronic'}
_JOHN_ACQUISITION = 'tyerman-life-times-john-wesley--retained-three-volumes'
_JOHN_MASTER_SHA = 'd56533f26e5ed677fa1d8afe6c451c209dfc49e4b211e6035b046b0727907c9c'
_JOHN_SOURCE = 'reports/_logs/tyerman-john-wesley-existing-install-20261004-v1/identity-proposal-v1/retained-member-set.json'
_JOHN_SOURCE_SHA = '84bcfb4926d70a447cbc4ec31baedeb23052574524d839fa593c5014e54aebad'



_TURTON_IDENTITY = {
    'work_id': 'turton-truth-of-christianity-1919',
    'textual_form_id': 'turton-truth-of-christianity-1919-gutenberg-retained-en',
    'edition_id': 'turton-truth-of-christianity-1919-gutenberg-electronic',
}
_TURTON_ACQUISITION = 'turton-truth-of-christianity-1919-gutenberg-electronic-acquired'
_TURTON_ACCEPTANCE_SHA = 'c2df2729129610c060ac9bb014f06b7434c192b96303aa265ecce15b55ce4fdc'
_TURTON_MASTER_SHA = '172e6f53424b51ce3c432f4707ff8aa8c48b879f57b92bde2b616dfcd68feb4d'
_TURTON_ACQUISITION_SHA = '4b83ab7b4337821a8be4cc405f76142ef1ac0a5797dbdfede266cb984a8dd28f'


def _turton_accepted_native(root, context):
    """Route only this accepted PG witness's source roles through native content."""
    if context['identity'].get('work_id') != _TURTON_IDENTITY['work_id']:
        return False
    authority = context['authority']
    if (context['identity'] != _TURTON_IDENTITY
            or context['accepted'].get('identity') != {
                **_TURTON_IDENTITY, 'acquisition_id': _TURTON_ACQUISITION}
            or context['language'] != 'en'
            or authority['acceptance']['sha256'] != _TURTON_ACCEPTANCE_SHA
            or authority['master']['sha256'] != _TURTON_MASTER_SHA
            or authority['acquisition']['sha256'] != _TURTON_ACQUISITION_SHA
            or _accepted_projection_profile(root, context) is not None):
        raise PipelineError('Turton accepted identity, authority, or profile differs')
    return True


def _john_accepted_native(root, context):
    """Select only the validated three-volume prose acceptance and source set."""
    if context['identity'].get('work_id') != _JOHN_IDENTITY['work_id']:
        return False
    from ocd_kernel.library.acquisitions import acquisition_for_edition

    identity = context['accepted'].get('identity', {})
    source = context['accepted'].get('source', {})
    if (context['identity'] != _JOHN_IDENTITY
            or identity != {**_JOHN_IDENTITY, 'acquisition_id': _JOHN_ACQUISITION}
            or context['language'] != 'en'
            or context['authority']['master']['sha256'] != _JOHN_MASTER_SHA
            or _accepted_projection_profile(root, context) is not None
            or source.get('source_path') != _JOHN_SOURCE
            or source.get('source_sha256') != _JOHN_SOURCE_SHA
            or source.get('source_bytes') != 1902):
        raise PipelineError('John accepted identity, source set, or projection profile differs')
    _, acquisition = acquisition_for_edition(
        root, _JOHN_IDENTITY['work_id'], _JOHN_IDENTITY['edition_id'],
        acquisition_id=_JOHN_ACQUISITION)
    retained = io_path(root / _JOHN_SOURCE).read_bytes()
    if (acquisition.get('source_path') != _JOHN_SOURCE
            or acquisition.get('source_sha256') != _JOHN_SOURCE_SHA
            or acquisition.get('source_bytes') != 1902
            or len(retained) != 1902
            or hashlib.sha256(retained).hexdigest() != _JOHN_SOURCE_SHA):
        raise PipelineError('John retained acquisition member set differs')
    try:
        source_set = json.loads(retained)
    except (UnicodeError, ValueError) as exc:
        raise PipelineError('John retained member set is invalid') from exc
    members = source_set.get('members') if isinstance(source_set, dict) else None
    if not isinstance(members, list) or len(members) != 3:
        raise PipelineError('John retained member set volume count differs')
    expected = (
        ('raw/gutenberg/69582/pg69582-h.zip', 892244, 'fd78f98a6b79186a5f886c2e0f49a30c4b6d2ab9eae59c43d49e5f582898bf8b'),
        ('raw/gutenberg/71130/pg71130-h.zip', 1115690, '0dd3ef53f9081c06cb604c052748cb155ae1100e52720961472e387421bfe062'),
        ('raw/gutenberg/76882/pg76882-h.zip', 2360274, '7e3d35ea02e40d5bdfee8294ac4c3bd3316ce11c3322a06e687c2b6199824245'),
    )
    for member, (path, size, digest) in zip(members, expected, strict=True):
        raw = io_path(root / path).read_bytes()
        if (member.get('path') != path or member.get('bytes') != size
                or member.get('sha256') != digest
                or member.get('position') != expected.index((path, size, digest)) + 1
                or len(raw) != size or hashlib.sha256(raw).hexdigest() != digest):
            raise PipelineError('John retained source volume differs')
    if hashlib.sha256(io_path(context['edition'].path).read_bytes()).hexdigest() != _JOHN_MASTER_SHA:
        raise PipelineError('John accepted master bytes differ')
    return True


def _samuel_accepted_native(root, context):
    """Select only the validated Samuel acceptance with its retained member."""
    if context['identity'].get('work_id') != _SAMUEL_IDENTITY['work_id']:
        return False
    from ocd_kernel.library.acquisitions import acquisition_for_edition

    identity = context['accepted'].get('identity', {})
    source = context['accepted'].get('source', {})
    if (context['identity'] != _SAMUEL_IDENTITY
            or identity.get('acquisition_id') != 'pg67980-retained-html'
            or context['language'] != 'en'
            or context['authority']['master']['sha256'] != _SAMUEL_ACCEPTED_DRAFT_SHA
            or _accepted_projection_profile(root, context) is not None
            or source.get('source_path') != _SAMUEL_SOURCE
            or source.get('source_sha256') != _SAMUEL_SOURCE_SHA
            or source.get('source_bytes') != 1449525):
        raise PipelineError('Samuel accepted identity, source, or projection profile differs')
    _, acquisition = acquisition_for_edition(
        root, _SAMUEL_IDENTITY['work_id'], _SAMUEL_IDENTITY['edition_id'],
        acquisition_id='pg67980-retained-html')
    retained = io_path(root / _SAMUEL_SOURCE).read_bytes()
    if (acquisition.get('source_path') != _SAMUEL_SOURCE
            or acquisition.get('source_sha256') != _SAMUEL_SOURCE_SHA
            or acquisition.get('source_bytes') != 1449525
            or len(retained) != 1449525
            or hashlib.sha256(retained).hexdigest() != _SAMUEL_SOURCE_SHA):
        raise PipelineError('Samuel retained acquisition member differs')
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    master = etree.fromstring(io_path(context['edition'].path).read_bytes(), parser)
    texts = master.findall(f'{{{TEI_NS}}}text')
    if (master.tag != f'{{{TEI_NS}}}TEI' or len(texts) != 1
            or hashlib.sha256(etree.tostring(texts[0], method='c14n')).hexdigest()
            != _SAMUEL_TEXT_C14N_SHA):
        raise PipelineError('Samuel immutable front/body/back source text differs')
    return True


class UnsupportedStructure(PipelineError):
    """The selected TEI contains no declared supported prose shape."""


@dataclass(frozen=True)
class Projection:
    rows: list[dict[str, Any]]
    anchors: list[dict[str, Any]]
    warnings: list[str]
    exclusions: list[dict[str, Any]]
    master_sha256: str
    source_binding: dict[str, str]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(element: ET.Element, local_name: str) -> list[ET.Element]:
    return [child for child in list(element) if _local(child.tag) == local_name]


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _iter_text_without_notes(element: ET.Element) -> str:
    parts: list[str] = []

    def visit(node: ET.Element) -> None:
        if _local(node.tag) == "note":
            if node.tail:
                parts.append(node.tail)
            return
        if node.text:
            parts.append(node.text)
        for child in list(node):
            visit(child)
        if node.tail:
            parts.append(node.tail)

    visit(element)
    return _normalize_text("".join(parts))


def _note_text(note: ET.Element) -> str:
    # A note's body is evidence carried by the paragraph.  Nested p elements
    # are therefore never considered independent public rows.
    return _normalize_text("".join(note.itertext()))


def _descendant_notes(element: ET.Element) -> list[ET.Element]:
    return [node for node in element.iter() if _local(node.tag) == "note"]


def _header(root: ET.Element) -> tuple[str, str, str, dict[str, str]]:
    ptr_target = ""
    retained_hash = ""
    source_hash = ""
    identities: dict[str, str] = {}
    source_desc = next((node for node in root.iter() if _local(node.tag) == "sourceDesc"), None)
    if source_desc is None:
        raise PipelineError("accepted TEI must contain sourceDesc")
    for node in source_desc.iter():
        name = _local(node.tag)
        if name == "ptr" and not ptr_target:
            target = node.get("target")
            if target:
                ptr_target = target
        elif name == "idno":
            kind = (node.get("type") or "").lower()
            value = _normalize_text("".join(node.itertext()))
            if kind in {"sha256", "retained_sha256", "archive_sha256"}:
                retained_hash = value.lower()
            elif kind in {"source_sha256", "origin_sha256"}:
                source_hash = value.lower()
            elif kind in {"work_id", "textual_form_id", "edition_id", "acquisition_id", "representation_revision"}:
                identities[kind] = value
    if not ptr_target or not retained_hash:
        raise PipelineError("accepted TEI must bind source URL and retained sha256 in sourceDesc")
    for label, value in (("retained", retained_hash), ("source", source_hash)):
        if value and (len(value) != 64 or any(char not in "0123456789abcdef" for char in value)):
            raise PipelineError(f"TEI {label} source sha256 is invalid: {value}")
    return ptr_target, retained_hash, source_hash, identities


def _find_scope(root: ET.Element, scope_id: str | None) -> ET.Element:
    body = next((node for node in root.iter() if _local(node.tag) == "body"), None)
    if body is None:
        raise UnsupportedStructure("TEI has no text/body for prose projection")
    if scope_id:
        for node in body.iter():
            if node.get(XML_ID) == scope_id:
                if _local(node.tag) != "div":
                    raise UnsupportedStructure(f"prose scope is not a div: {scope_id}")
                return node
        raise UnsupportedStructure(f"prose scope xml:id not found in body: {scope_id}")

    # PIPE-001's bounded fixture carries one leaf section div beneath a work
    # div.  Choosing a unique leaf is explicit and deterministic; multiple
    # leaves require a later selection contract rather than guessed flattening.
    leaves = [
        node
        for node in body.iter()
        if _local(node.tag) == "div"
        and _children(node, "p")
        and not _children(node, "div")
    ]
    if len(leaves) == 1:
        return leaves[0]
    direct_paragraphs = _children(body, "p")
    if direct_paragraphs:
        return body
    raise UnsupportedStructure(
        f"prose source has {len(leaves)} candidate section divs; an explicit scope is required"
    )


def _ancestor_divs(root: ET.Element, target: ET.Element) -> list[ET.Element]:
    parent: dict[ET.Element, ET.Element] = {}
    for node in root.iter():
        for child in list(node):
            parent[child] = node
    result: list[ET.Element] = []
    current = parent.get(target)
    while current is not None:
        if _local(current.tag) == "div":
            result.append(current)
        current = parent.get(current)
    return list(reversed(result))


def _path(root: ET.Element, target: ET.Element) -> str:
    parent: dict[ET.Element, ET.Element] = {}
    for node in root.iter():
        for child in list(node):
            parent[child] = node
    components: list[str] = []
    current: ET.Element | None = target
    while current is not None:
        name = _local(current.tag)
        xml_id = current.get(XML_ID)
        components.append(f"{name}[@xml:id='{xml_id}']" if xml_id else name)
        current = parent.get(current)
    return "/" + "/".join(reversed(components))


def _language(root: ET.Element, requested: str | None) -> str:
    if requested:
        return requested
    value = root.get(XML_LANG) or next(
        (node.get(XML_LANG) for node in root.iter() if _local(node.tag) in {"text", "body"} and node.get(XML_LANG)),
        None,
    )
    if not value:
        raise PipelineError("prose language must be declared in the edition sidecar or TEI")
    return value


def project_prose(
    tei_path: Path,
    *,
    work_id: str,
    textual_form_id: str,
    edition_id: str,
    acquisition_id: str,
    edition_title: str,
    language: str | None,
    representation_revision: str | None,
    source_url: str,
    accessed_at: str | None,
    source_sha256: str,
    retained_sha256: str | None = None,
    scope_id: str | None = None,
    rights: str | None = None,
) -> Projection:
    try:
        root = ET.parse(tei_path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise PipelineError(f"cannot parse accepted TEI {tei_path}: {exc}") from exc
    if root.tag != f"{{{TEI_NS}}}TEI":
        raise PipelineError(f"accepted master root must be TEI: {tei_path}")
    if any(not node.tag.startswith(f"{{{TEI_NS}}}") for node in root.iter()):
        raise UnsupportedStructure("unsupported non-TEI namespace in master")
    tei_url, tei_retained_hash, tei_source_hash, header_ids = _header(root)
    if tei_url != source_url:
        raise PipelineError(f"TEI source URL mismatch: {tei_url} != {source_url}")
    if retained_sha256 is not None and tei_retained_hash != retained_sha256.lower():
        raise PipelineError(
            f"TEI retained sha256 mismatch: {tei_retained_hash} != {retained_sha256.lower()}"
        )
    if tei_source_hash and tei_source_hash != source_sha256.lower():
        raise PipelineError(f"TEI source sha256 mismatch: {tei_source_hash} != {source_sha256.lower()}")
    expected_ids = {
        "work_id": work_id,
        "textual_form_id": textual_form_id,
        "edition_id": edition_id,
        "acquisition_id": acquisition_id,
    }
    for kind, expected in expected_ids.items():
        actual = header_ids.get(kind)
        if actual is not None and actual != expected:
            raise PipelineError(f"TEI {kind} mismatch: {actual} != {expected}")
    actual_revision = header_ids.get("representation_revision")
    if representation_revision is None:
        if actual_revision is None:
            raise PipelineError("representation revision must be declared in the edition sidecar or TEI")
        representation_revision = actual_revision
    if actual_revision is not None and actual_revision != representation_revision:
        raise PipelineError(
            f"TEI representation revision mismatch: {actual_revision} != {representation_revision}"
        )
    scope = _find_scope(root, scope_id)
    text_root = root.find(f"{{{TEI_NS}}}text")
    if text_root is None or [_local(child.tag) for child in text_root] != ["body"]:
        raise UnsupportedStructure("tracer requires one body with no unaccounted front or back")
    wrapper = text_root[0]
    while wrapper is not scope:
        children = list(wrapper)
        divisions = _children(wrapper, "div")
        if len(divisions) != 1 or any(_local(child.tag) not in {"head", "div"} for child in children):
            raise UnsupportedStructure("unaccounted content outside the selected prose section")
        if len(_children(wrapper, "head")) > 1:
            raise UnsupportedStructure("multiple wrapper headings are unsupported")
        wrapper = divisions[0]
    if any(_local(child.tag) not in {"head", "p"} for child in scope):
        raise UnsupportedStructure("unsupported child in the bounded prose section")
    if len(_children(scope, "head")) > 1:
        raise UnsupportedStructure("multiple section headings are unsupported")
    paragraphs = _children(scope, "p")
    if not paragraphs:
        raise UnsupportedStructure("selected prose scope has no native paragraph boundaries")
    allowed_inline = {"pb", "lb", "seg", "hi", "foreign", "ref", "note", "anchor"}

    def validate_inline(node: ET.Element, *, in_note: bool = False) -> None:
        for child in list(node):
            kind = _local(child.tag)
            if kind == "note":
                validate_inline(child, in_note=True)
                continue
            if in_note and kind == "p":
                validate_inline(child, in_note=True)
                continue
            if kind not in allowed_inline:
                raise UnsupportedStructure(
                    f"unsupported prose inline element {kind!r} at {_path(root, child)}"
                )
            validate_inline(child, in_note=in_note)
    exclusions: list[dict[str, Any]] = []
    for child in list(scope):
        if _local(child.tag) in {"head", "p"}:
            continue
        if _local(child.tag) == "div":
            raise UnsupportedStructure("nested div in selected prose scope requires a narrower scope")
        if _local(child.tag) not in allowed_inline:
            exclusions.append({"kind": _local(child.tag), "reason": "unsupported scope child"})
    ancestors = _ancestor_divs(root, scope)
    division_context = [
        {
            "xml_id": node.get(XML_ID),
            "type": node.get("type"),
            "head": _normalize_text("".join(head.itertext())) if (head := next(iter(_children(node, "head")), None)) is not None else None,
        }
        for node in ancestors + ([scope] if scope not in ancestors else [])
    ]
    rows: list[dict[str, Any]] = []
    anchors: list[dict[str, Any]] = []
    for sequence, paragraph in enumerate(paragraphs, start=1):
        validate_inline(paragraph)
        text = _iter_text_without_notes(paragraph)
        if not text:
            exclusions.append(
                {"kind": "paragraph", "xml_id": paragraph.get(XML_ID), "reason": "empty source paragraph"}
            )
            continue
        xml_id = paragraph.get(XML_ID)
        if not xml_id:
            raise UnsupportedStructure(f"prose paragraph has no xml:id at {_path(root, paragraph)}")
        notes: list[dict[str, Any]] = []
        for note in _descendant_notes(paragraph):
            notes.append(
                {
                    "xml_id": note.get(XML_ID),
                    "place": note.get("place"),
                    "n": note.get("n"),
                    "text": _note_text(note),
                    "source_path": _path(root, note),
                }
            )
        locator = {
            "xml_id": xml_id,
            "source_path": _path(root, paragraph),
            "division_ids": [item["xml_id"] for item in division_context if item["xml_id"]],
            "division_titles": [item["head"] for item in division_context if item["head"]],
            "source_order": sequence,
        }
        provenance: dict[str, Any] = {
            "edition_title": edition_title,
            "source_url": source_url,
            "acquisition_id": acquisition_id,
        }
        if accessed_at is not None:
            provenance["accessed_at"] = accessed_at
        if rights:
            provenance["rights"] = rights
        row = make_row(
            record_id=f"{edition_id}:unit-{sequence:06d}",
            sequence=sequence,
            work_id=work_id,
            textual_form_id=textual_form_id,
            edition_id=edition_id,
            category="prose",
            language=_language(root, language),
            text=text,
            locator=locator,
            provenance=provenance,
            representation_revision=representation_revision,
            notes=notes,
        )
        rows.append(row)
        anchors.append(
            {
                "record_id": row["record_id"],
                "sequence": sequence,
                "tei_xml_id": xml_id,
                "tei_path": locator["source_path"],
                "locator": locator,
                "text_sha256": row_text_hash(text),
                "notes": [note["xml_id"] for note in notes if note["xml_id"]],
            }
        )
    if not rows:
        raise UnsupportedStructure("prose projection produced no rows")
    return Projection(
        rows=rows,
        anchors=anchors,
        warnings=[],
        exclusions=exclusions,
        master_sha256=sha256_file(tei_path),
        source_binding={
            "source_url": source_url,
            "source_sha256": source_sha256.lower(),
            "retained_sha256": tei_retained_hash,
        },
    )


project = project_prose


PROSE_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "schemas"
    / "v2"
    / "categories"
    / "prose.schema.json"
)
PUBLIC_ROW_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "schemas"
    / "v2"
    / "public-row.schema.json"
)


def _prose_validator() -> Any:
    """Load the closed prose-row schema with its common-row reference locally."""

    try:
        import jsonschema
        from referencing import Registry, Resource
        import referencing.jsonschema
    except ImportError as exc:  # pragma: no cover - project dependency
        raise PipelineError("jsonschema and referencing are required for prose projection") from exc

    try:
        prose_schema = json.loads(PROSE_SCHEMA_PATH.read_text(encoding="utf-8"))
        public_row_schema = json.loads(
            PUBLIC_ROW_SCHEMA_PATH.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PipelineError(
            f"cannot load prose projection schemas: {PROSE_SCHEMA_PATH}"
        ) from exc
    if not isinstance(prose_schema, dict) or not isinstance(public_row_schema, dict):
        raise PipelineError("prose projection schemas must be JSON objects")
    public_row_id = public_row_schema.get("$id")
    if not isinstance(public_row_id, str) or not public_row_id:
        raise PipelineError("common public-row schema must declare a nonempty $id")
    try:
        resource = Resource.from_contents(
            public_row_schema,
            default_specification=referencing.jsonschema.DRAFT202012,
        )
        native_schema = json.loads((PROSE_SCHEMA_PATH.parent.parent / 'native-content.schema.json').read_text(encoding='utf-8'))
        native_resource = Resource.from_contents(native_schema, default_specification=referencing.jsonschema.DRAFT202012)
        registry = Registry().with_resources([(public_row_id, resource), (native_schema['$id'], native_resource)])
        validator = projection_validator(
            prose_schema,
            registry=registry,
            format_checker=jsonschema.FormatChecker(),
        )
        validator.check_schema(prose_schema)
    except (TypeError, ValueError, jsonschema.SchemaError) as exc:
        raise PipelineError("invalid prose projection schema package") from exc
    return validator


def _validate_prose_projection(projection: Mapping[str, Any]) -> None:
    """Validate common rows through the prose category schema before returning them."""

    rows = projection.get("rows")
    if not isinstance(rows, list):
        raise PipelineError("prose projection rows must be a list")
    validator = _prose_validator()
    for index, row in enumerate(rows):
        errors = sorted(validator.iter_errors(row), key=lambda error: list(error.path))
        if errors:
            record_id = row.get("record_id", f"row-{index + 1}") if isinstance(row, dict) else f"row-{index + 1}"
            raise PipelineError(
                f"invalid prose public row {record_id}: {errors[0].message}"
            )


def project_prose_document(
    tei_path: Path,
    *,
    identity: dict[str, str],
    language: str,
    representation_revision: str,
    edition_title: str,
    scope_id: str | None = None,
    _allow_acceptance_metadata: bool = False,
) -> dict[str, Any]:
    """Project one nonaccepted prose document through the reviewed common mapper."""

    if _uses_native_content(tei_path):
        if scope_id is not None:
            raise PipelineError('native prose requires the complete document')
        from ocd_kernel.projection.categories.native_documents import project_document as native_project
        return native_project(tei_path, identity=identity, language=language,
                              representation_revision=representation_revision, edition_title=edition_title,
                              category='prose', _allow_acceptance_metadata=_allow_acceptance_metadata)

    if _allow_acceptance_metadata:
        raise PipelineError('acceptance-header prose requires native content')

    from ocd_kernel.projection.envelope import project_document

    projection = project_document(
        tei_path,
        identity=identity,
        language=language,
        representation_revision=representation_revision,
        edition_title=edition_title,
        scope_id=scope_id,
    )
    _validate_prose_projection(projection)
    return projection


def _moody_accepted_profile(root, context):
    """Admit only the exact accepted Moody source/accounting/master tuple."""
    from ocd_kernel.projection.categories.native_documents import MOODY_PROFILE, _MOODY_IDENTITY, _MOODY_MASTER_SHA
    if context['identity'].get('work_id') != _MOODY_IDENTITY['work_id']:
        return None
    if context['identity'] != _MOODY_IDENTITY:
        raise PipelineError('Moody native profile identity differs')
    accepted_identity = context['accepted'].get('identity', {})
    if accepted_identity.get('acquisition_id') != 'pg61883-retained-zip':
        raise PipelineError('Moody native profile acquisition binding differs')
    if context['authority']['master']['sha256'] != _MOODY_MASTER_SHA:
        raise PipelineError('Moody native profile master changed')
    reference = context['accepted'].get('source', {}).get('accounting')
    if not isinstance(reference, dict) or not isinstance(reference.get('path'), str):
        raise PipelineError('Moody accepted source accounting is missing')
    raw = io_path(root / reference['path']).read_bytes()
    if len(raw) != reference.get('bytes') or hashlib.sha256(raw).hexdigest() != reference.get('sha256'):
        raise PipelineError('Moody accepted source-accounting binding differs')
    accounting = json.loads(raw)
    accounting_identity = accounting.get('identity', {})
    if (accounting.get('projection_profile') != MOODY_PROFILE
            or {key: accounting_identity.get(key) for key in _MOODY_IDENTITY} != _MOODY_IDENTITY
            or accounting_identity.get('acquisition_id') != 'pg61883-retained-zip'
            or accounting.get('source_manifest_sha256') != 'd0fa96b1f2d9ec7378c010c03cd1d50bff8d0ceca752efa5be1016d282b4de6b'
            or accounting.get('retained_member_set_sha256') != 'b332decb87837d629d696537ab7a59143752335c2a38b3ad6cfd3bf2e8b4c7af'
            or accounting.get('retained_member_set_path') != 'library/works/d-l-moody-prevailing-prayer/forms/english/editions/d-l-moody-prevailing-prayer-pg61883/source-member-set.json'
            or accounting.get('source_sha256') != 'b332decb87837d629d696537ab7a59143752335c2a38b3ad6cfd3bf2e8b4c7af'
            or accounting.get('source', {}).get('source_kind') != 'retained-member-set'
            or accounting.get('source', {}).get('source_path') != accounting.get('retained_member_set_path')
            or accounting.get('source', {}).get('source_sha256') != 'b332decb87837d629d696537ab7a59143752335c2a38b3ad6cfd3bf2e8b4c7af'
            or accounting.get('primary_archive', {}).get('path') != 'raw/gutenberg/61883/pg61883-h.zip'
            or accounting.get('primary_archive', {}).get('sha256') != 'c3e9023f2c0e1065e4f2601c21b791ef50f94f1acb31ef4c61880b7592a3ff19'):
        raise PipelineError('Moody source manifest/member-set profile binding differs')
    return MOODY_PROFILE


def _coppens_accepted_profile(root, context):
    """Select only the exact fully pinned Coppens electronic edition."""
    from ocd_kernel.projection.categories import coppens_pg70790_source_profile as coppens_source
    return coppens_source.select(root, context)


def project_accepted_prose(
    root: Path,
    *,
    acceptance_path: Path,
) -> dict[str, Any]:
    """Project a promoted accepted prose master through the common accepted path."""

    from ocd_kernel.projection.categories.sermons import _accepted_context
    root = resolve_path(root)
    acceptance_path = resolve_path(acceptance_path)
    context = _accepted_context(root, acceptance_path, expected_category='prose')
    from ocd_kernel.projection.categories import jan_hus_native
    if jan_hus_native.route(context):
        return jan_hus_native.project(context)
    from build.tei.john_l812_profile_v1.accepted_runtime import select_context as _l812_select, project_accepted_document as _l812_project
    if _l812_select(root, context, category="prose", collection=False, projection_profile=None):
        return _l812_project(root, acceptance_path=acceptance_path, category="prose")
    from build.tei import eusebius_l811_native_context_proposal as l811
    if l811.select(root, context):
        from build.tei.eusebius_l811_native_accepted_proposal import project
        return project(root, acceptance_path=acceptance_path)
    if _turton_accepted_native(root, context):
        from ocd_kernel.projection.categories.native_documents import project_accepted_document
        return project_accepted_document(root, acceptance_path=acceptance_path, category='prose')
    if _john_accepted_native(root, context):
        from ocd_kernel.projection.categories.native_documents import project_accepted_document

        return project_accepted_document(root, acceptance_path=acceptance_path, category='prose')
    if _samuel_accepted_native(root, context):
        from ocd_kernel.projection.categories.native_documents import project_accepted_document
        return project_accepted_document(root, acceptance_path=acceptance_path, category='prose')
    from ocd_kernel.projection.categories import tyerman_whitefield_source_profile as whitefield_source
    if whitefield_source.select(root,context,_accepted_projection_profile(root,context)):
        from ocd_kernel.projection.categories.native_documents import project_accepted_document
        return project_accepted_document(root,acceptance_path=acceptance_path,category='prose')
    guyon_profile = _guyon_accepted_profile(root, context)
    if guyon_profile is not None:
        from ocd_kernel.projection.categories.native_documents import project_accepted_document
        return project_accepted_document(root, acceptance_path=acceptance_path,
                                         category='prose', projection_profile=guyon_profile)
    moody_profile = _moody_accepted_profile(root, context)
    if moody_profile is not None:
        from ocd_kernel.projection.categories.native_documents import project_accepted_document
        return project_accepted_document(root, acceptance_path=acceptance_path, category='prose',
                                         projection_profile=moody_profile)
    coppens_profile = _coppens_accepted_profile(root, context)
    if coppens_profile is not None:
        from ocd_kernel.projection.categories.native_documents import project_accepted_document
        return project_accepted_document(root, acceptance_path=acceptance_path, category='prose',
                                         projection_profile=coppens_profile)
    cassiodorus_profile = _cassiodorus_accepted_profile(root, context)
    if cassiodorus_profile is not None:
        from ocd_kernel.projection.categories.native_documents import project_accepted_document
        return project_accepted_document(root, acceptance_path=acceptance_path, category='prose',
                                         projection_profile=cassiodorus_profile)
    carey_profile = _carey_accepted_profile(root, context)
    if carey_profile is not None:
        from ocd_kernel.projection.categories.native_documents import project_accepted_document
        return project_accepted_document(root, acceptance_path=acceptance_path, category='prose',
                                         projection_profile=carey_profile)
    american_profile = _american_missionary_profile(root, context)
    if american_profile is not None:
        from ocd_kernel.projection.categories.native_documents import project_accepted_document

        return project_accepted_document(root, acceptance_path=acceptance_path, category='prose',
                                         projection_profile=american_profile)
    from ocd_kernel.projection.categories.native_documents import select_accepted_source_lines_profile
    source_lines_profile = select_accepted_source_lines_profile(root, context)
    if source_lines_profile is not None:
        from ocd_kernel.projection.categories.native_documents import project_accepted_document
        return project_accepted_document(root, acceptance_path=acceptance_path, category='prose',
                                         projection_profile=source_lines_profile)
    profile = _accepted_projection_profile(root, context)
    if profile is None:
        profile = _peter_jones_profile(context)
    if profile is not None:
        from ocd_kernel.projection.categories.apostolic_tradition import PROFILE as APOSTOLIC_PROFILE
        from ocd_kernel.projection.categories.native_documents import (
            GREENLEAF_MARKER_PROFILE, HOLY_IMAGES_PROFILE, PETER_JONES_PROFILE, HODGE_PROFILE,
        )
        if profile in {GREENLEAF_MARKER_PROFILE, HOLY_IMAGES_PROFILE, PETER_JONES_PROFILE, HODGE_PROFILE, APOSTOLIC_PROFILE}:
            from ocd_kernel.projection.categories.native_documents import project_accepted_document
            return project_accepted_document(root, acceptance_path=acceptance_path, category='prose',
                                             projection_profile=profile)
        from ocd_kernel.projection.categories.lib050_owen import PROFILE as OWEN_PROFILE, EVANGELICAL_PROFILE, COMMUNION_PROFILE
        if profile in {OWEN_PROFILE, EVANGELICAL_PROFILE, COMMUNION_PROFILE}:
            from ocd_kernel.projection.categories.lib050_owen import project
            return project(root, acceptance_path=acceptance_path)
        from ocd_kernel.projection.categories.lib051_owen import (
            PROFILE as OWEN_READABLE_PROFILE, FINAL_PROFILE as OWEN_FINAL_PROFILE,
        )
        if profile in {OWEN_READABLE_PROFILE, OWEN_FINAL_PROFILE}:
            from ocd_kernel.projection.categories.lib051_owen import project
            return project(root, acceptance_path=acceptance_path)
        from ocd_kernel.projection.categories.lib040_augustine_selected import PROFILE as SELECTED_PROFILE
        if profile == SELECTED_PROFILE:
            from ocd_kernel.projection.categories.lib040_augustine_selected import project
            return project(root, acceptance_path=acceptance_path, category='prose')
        from ocd_kernel.projection.categories.lib040_augustine_divisions import PROFILE as DIVISIONS_PROFILE
        if profile == DIVISIONS_PROFILE:
            from ocd_kernel.projection.categories.lib040_augustine_divisions import project
            return project(root, acceptance_path=acceptance_path, category='prose')
        from ocd_kernel.projection.categories.lib040_harmony import PROFILE, project
        if profile != PROFILE:
            raise PipelineError(f'unsupported accepted prose projection profile: {profile}')
        return project(root, acceptance_path=acceptance_path)
    if _uses_native_content(context['edition'].path):
        from ocd_kernel.projection.categories.native_documents import project_accepted_document
        return project_accepted_document(root, acceptance_path=acceptance_path, category='prose')

    from ocd_kernel.projection.envelope import project_accepted
    from ocd_kernel.projection.receipt import build_correspondence_receipt

    projection = project_accepted(root, acceptance_path=acceptance_path)
    _validate_prose_projection(projection)
    projection["receipt"] = build_correspondence_receipt(projection, identity=context["identity"])
    return projection


def _peter_jones_profile(context):
    """Enable the bounded source-marker mapping only for this accepted master."""
    if context['identity'] != {
        'work_id': 'peter-jones-life-and-journals',
        'textual_form_id': 'peter-jones-life-and-journals-wikisource-retained',
        'edition_id': 'peter-jones-life-and-journals-wikisource-electronic',
    }:
        return None
    if context['authority']['master']['sha256'] != 'ee67ac29066b35c6fc98252d5f1bbfa8988a94df53f0fd7d7cb11eaa09354039':
        raise PipelineError('Peter Jones accepted master changed; source-marker profile requires review')
    from ocd_kernel.projection.categories.native_documents import PETER_JONES_PROFILE
    return PETER_JONES_PROFILE


def _guyon_accepted_profile(root, context):
    """Choose the exact Short Method source set only after validated acceptance."""
    from ocd_kernel.projection.categories import guyon_source_profile
    from ocd_kernel.projection.categories.native_documents import GUYON_PROFILE

    binding = guyon_source_profile.select_accepted(
        context, category='prose', collection=False, projection_profile=None)
    if binding is None:
        return None
    declared = _accepted_projection_profile(root, context)
    if declared not in (None, GUYON_PROFILE):
        raise PipelineError('Guyon accepted source accounting names another projection profile')
    return GUYON_PROFILE


def _american_missionary_profile(root, context):
    """Admit only the two installed annual witnesses to the monthly native profile."""
    if context['identity'].get('work_id') != 'american-missionary':
        return None
    from ocd_kernel.projection.categories.native_documents import (
        AMERICAN_MISSIONARY_PROFILE, _AMERICAN_MISSIONARY_MASTERS,
    )

    identity = context['identity']
    edition_id = identity.get('edition_id')
    if (identity.get('textual_form_id') != 'american-missionary-gutenberg-retained-en'
            or _AMERICAN_MISSIONARY_MASTERS.get(edition_id) != context['authority']['master']['sha256']
            or context['accepted']['identity'].get('acquisition_id') != edition_id + '-acquired'
            or context['language'] != 'en'
            or _accepted_projection_profile(root, context) is not None):
        raise PipelineError('American Missionary accepted profile identity or master differs')
    return AMERICAN_MISSIONARY_PROFILE


def _cassiodorus_accepted_profile(root, context):
    """Select the exact retained Hodgkin translation/accounting for native rows."""
    from ocd_kernel.projection.categories import cassiodorus_source_profile as profile
    identity = context.get('identity', {})
    if identity.get('work_id') != profile.IDENTITY['work_id']:
        return None
    if identity != profile.IDENTITY:
        raise PipelineError('Cassiodorus accepted source identity differs')
    accepted_identity = context['accepted'].get('identity', {})
    if accepted_identity != {**profile.IDENTITY, 'acquisition_id': profile.ACQUISITION_ID}:
        raise PipelineError('Cassiodorus accepted acquisition identity differs')
    if context['language'] != 'en' or context['authority']['master']['sha256'] != profile.MASTER_SHA256:
        raise PipelineError('Cassiodorus accepted language/master differs')
    ref = context['accepted'].get('source', {}).get('accounting')
    if (not isinstance(ref, dict) or set(ref) != {'path','bytes','sha256'}
            or ref.get('path') != profile.ACCOUNTING_PATH
            or ref.get('sha256') != profile.ACCOUNTING_SHA256
            or not isinstance(ref.get('bytes'), int) or ref['bytes'] <= 0):
        raise PipelineError('Cassiodorus source-accounting reference differs')
    raw = io_path(root / profile.ACCOUNTING_PATH).read_bytes()
    if len(raw) != ref.get('bytes') or hashlib.sha256(raw).hexdigest() != profile.ACCOUNTING_SHA256:
        raise PipelineError('Cassiodorus source-accounting bytes differ')
    accounting = json.loads(raw)
    if (accounting.get('contract') != 'ocd-cassiodorus-pg18590-acceptance-accounting-v6'
            or accounting.get('source_manifest_sha256') != profile.SOURCE_MANIFEST_SHA256
            or accounting.get('archive_sha256') != profile.ARCHIVE_SHA256
            or accounting.get('html_sha256') != profile.HTML_SHA256
            or accounting.get('body_text_sha256') != profile.BODY_TEXT_SHA256
            or accounting.get('identity') != {**profile.IDENTITY, 'acquisition_id': profile.ACQUISITION_ID}
            or accounting.get('source', {}).get('source_path') != 'raw/gutenberg/18590/html/pg18590-images.html'
            or accounting.get('source', {}).get('source_sha256') != profile.HTML_SHA256
            or accounting.get('source', {}).get('source_bytes') != 1760552):
        raise PipelineError('Cassiodorus source accounting does not bind the retained title')
    return profile.PROFILE


def _carey_accepted_profile(root, context):
    """Admit only the installed Carey generation previously checked explicitly."""
    identity = {
        'work_id': 'carey-enquiry',
        'textual_form_id': 'carey-enquiry-retained-text',
        'edition_id': 'carey-enquiry-pg11449-electronic-witness',
    }
    accepted_identity = context['accepted'].get('identity', {})
    if (context['identity'].get('work_id') != identity['work_id']
            and accepted_identity.get('work_id') != identity['work_id']):
        return None
    if (context['identity'] != identity
            or accepted_identity != {**identity, 'acquisition_id': 'carey-enquiry-pg11449-acquired'}):
        raise PipelineError('Carey accepted profile identity differs')
    if context['authority']['master']['sha256'] != '74ea4ce79d468922d968de2ee5fe11a541784b7646ad8185b79f3bcc12468c6f':
        raise PipelineError('Carey accepted profile master differs')
    reference = context['accepted'].get('source', {}).get('accounting')
    if reference != {
        'path': 'library/works/carey-enquiry/integration/carey-pg11449-grouped-tables-v1/source-accounting.json',
        'bytes': 3977,
        'sha256': '1800db65399541e7584c640199bf4b2e84f5d1f1de3bb8dc9aa7c1b9333f5941',
    }:
        raise PipelineError('Carey accepted profile source-accounting reference differs')
    from ocd_kernel.projection.categories.native_documents import CAREY_GROUPED_TABLE_PROFILE
    profile = _accepted_projection_profile(root, context)
    if profile not in (None, CAREY_GROUPED_TABLE_PROFILE):
        raise PipelineError('Carey accepted projection profile differs')
    return CAREY_GROUPED_TABLE_PROFILE


def _accepted_projection_profile(root, context):
    """Read the validated acceptance's source-accounting projection contract."""
    reference = context['accepted'].get('source', {}).get('accounting')
    if not isinstance(reference, dict) or not isinstance(reference.get('path'), str):
        return None
    path = io_path(root / reference['path'])
    raw = path.read_bytes()
    if len(raw) != reference.get('bytes') or hashlib.sha256(raw).hexdigest() != reference.get('sha256'):
        raise PipelineError('accepted prose source-accounting binding differs')
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise PipelineError('accepted prose source accounting must be an object')
    return data.get('projection_profile')


def _uses_native_content(path):
    """Select native structure when the TEI carries non-flat source semantics.

    The common paragraph envelope has a deliberately small vocabulary. Native
    prose retains ordered blocks, presentation, and source annotations without
    choosing a route by work identity or by catching a failed projection.
    """
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise PipelineError('invalid prose XML') from exc
    text = root.find('{http://www.tei-c.org/ns/1.0}text')
    if root.tag == '{http://www.tei-c.org/ns/1.0}teiCorpus':
        return True
    if text is None:
        return False
    native_tags = {
        'g', 'gap', 'list', 'lg', 'sp', 'floatingText', 'expan', 'ab', 'milestone',
        'table', 'name', 'title', 'index',
    }
    source_attributes = {'rendition', 'style', 'ana', 'prev', 'next',
                         'corresp', 'facs', 'source'}
    for node in text.iter():
        if not isinstance(node.tag, str):
            continue
        tag = _local(node.tag)
        if tag in native_tags:
            return True
        if tag == 'head' and node.get('type') in {'label', 'title'}:
            return True
        # LIB-031's source-backed ThML <span> is a typed TEI segment. The
        # common paragraph envelope rejects seg/@type, while native content
        # preserves that source role and its ordered inline text.
        if tag == 'seg' and node.get('type') == 'thml-span':
            return True
        if any(attribute in node.attrib for attribute in source_attributes):
            return True
        if 'rend' in node.attrib and tag != 'hi':
            return True
        if f'{{{XML_NS}}}space' in node.attrib:
            return True
    return False


def verify_accepted_prose(root, *, acceptance_path, rows, receipt):
    """Verify the native profile or retain the independent common paragraph check."""
    from ocd_kernel.projection.categories.sermons import _accepted_context
    try:
        root = resolve_path(root)
        acceptance_path = resolve_path(acceptance_path)
        context = _accepted_context(root, acceptance_path, expected_category='prose')
        from ocd_kernel.projection.categories import jan_hus_native
        if jan_hus_native.route(context):
            return jan_hus_native.verify(context, rows, receipt)
        from build.tei.john_l812_profile_v1.accepted_runtime import select_context as _l812_select, verify_accepted_document as _l812_verify
        if _l812_select(root, context, category="prose", collection=False, projection_profile=None):
            return _l812_verify(root, acceptance_path=acceptance_path, rows=rows, receipt=receipt, category="prose")
        from build.tei import eusebius_l811_native_context_proposal as l811
        if l811.select(root, context):
            from build.tei.eusebius_l811_native_accepted_check_proposal import verify
            return verify(root, acceptance_path=acceptance_path, rows=rows, receipt=receipt)
        if _turton_accepted_native(root, context):
            from ocd_kernel.projection.categories.native_documents import verify_accepted_document
            return verify_accepted_document(root, acceptance_path=acceptance_path, rows=rows, receipt=receipt, category='prose')
        if _john_accepted_native(root, context):
            from ocd_kernel.projection.categories.native_documents import verify_accepted_document
            return verify_accepted_document(root, acceptance_path=acceptance_path,
                                            rows=rows, receipt=receipt, category='prose')
        if _samuel_accepted_native(root, context):
            from ocd_kernel.projection.categories.native_documents import verify_accepted_document
            return verify_accepted_document(root, acceptance_path=acceptance_path,
                                            rows=rows, receipt=receipt, category='prose')
        from ocd_kernel.projection.categories import tyerman_whitefield_source_profile as whitefield_source
        if whitefield_source.select(root,context,_accepted_projection_profile(root,context)):
            from ocd_kernel.projection.categories.native_documents import verify_accepted_document
            return verify_accepted_document(root,acceptance_path=acceptance_path,rows=rows,receipt=receipt,category='prose')
        guyon_profile = _guyon_accepted_profile(root, context)
        if guyon_profile is not None:
            from ocd_kernel.projection.categories.native_documents import verify_accepted_document
            return verify_accepted_document(root, acceptance_path=acceptance_path,
                                            rows=rows, receipt=receipt, category='prose',
                                            projection_profile=guyon_profile)
        moody_profile = _moody_accepted_profile(root, context)
        if moody_profile is not None:
            from ocd_kernel.projection.categories.native_documents import verify_accepted_document
            return verify_accepted_document(root, acceptance_path=acceptance_path, rows=rows,
                                            receipt=receipt, category='prose',
                                            projection_profile=moody_profile)
        coppens_profile = _coppens_accepted_profile(root, context)
        if coppens_profile is not None:
            from ocd_kernel.projection.categories.native_documents import verify_accepted_document
            return verify_accepted_document(root, acceptance_path=acceptance_path, rows=rows,
                                            receipt=receipt, category='prose',
                                            projection_profile=coppens_profile)
        cassiodorus_profile = _cassiodorus_accepted_profile(root, context)
        if cassiodorus_profile is not None:
            from ocd_kernel.projection.categories.native_documents import verify_accepted_document
            return verify_accepted_document(root, acceptance_path=acceptance_path, rows=rows,
                                            receipt=receipt, category='prose',
                                            projection_profile=cassiodorus_profile)
        carey_profile = _carey_accepted_profile(root, context)
        if carey_profile is not None:
            from ocd_kernel.projection.categories.native_documents import verify_accepted_document
            return verify_accepted_document(root, acceptance_path=acceptance_path, rows=rows,
                                            receipt=receipt, category='prose', projection_profile=carey_profile)
        american_profile = _american_missionary_profile(root, context)
        if american_profile is not None:
            from ocd_kernel.projection.categories.native_documents import verify_accepted_document

            return verify_accepted_document(root, acceptance_path=acceptance_path, rows=rows,
                                            receipt=receipt, category='prose', projection_profile=american_profile)
        from ocd_kernel.projection.categories.native_documents import select_accepted_source_lines_profile
        source_lines_profile = select_accepted_source_lines_profile(root, context)
        if source_lines_profile is not None:
            from ocd_kernel.projection.categories.native_documents import verify_accepted_document
            return verify_accepted_document(root, acceptance_path=acceptance_path, rows=rows,
                                            receipt=receipt, category='prose',
                                            projection_profile=source_lines_profile)
        profile = _accepted_projection_profile(root, context)
        if profile is None:
            profile = _peter_jones_profile(context)
        if profile is not None:
            from ocd_kernel.projection.categories.apostolic_tradition import PROFILE as APOSTOLIC_PROFILE
            from ocd_kernel.projection.categories.native_documents import (
                GREENLEAF_MARKER_PROFILE, HOLY_IMAGES_PROFILE, PETER_JONES_PROFILE, HODGE_PROFILE,
            )
            if profile in {GREENLEAF_MARKER_PROFILE, HOLY_IMAGES_PROFILE, PETER_JONES_PROFILE, HODGE_PROFILE, APOSTOLIC_PROFILE}:
                from ocd_kernel.projection.categories.native_documents import verify_accepted_document
                return verify_accepted_document(root, acceptance_path=acceptance_path, rows=rows,
                                                receipt=receipt, category='prose', projection_profile=profile)
            from ocd_kernel.projection.categories.lib050_owen import PROFILE as OWEN_PROFILE, EVANGELICAL_PROFILE, COMMUNION_PROFILE
            if profile in {OWEN_PROFILE, EVANGELICAL_PROFILE, COMMUNION_PROFILE}:
                from ocd_kernel.projection.categories.lib050_owen import verify
                return verify(root, acceptance_path=acceptance_path, rows=rows, receipt=receipt)
            from ocd_kernel.projection.categories.lib051_owen import (
                PROFILE as OWEN_READABLE_PROFILE, FINAL_PROFILE as OWEN_FINAL_PROFILE,
            )
            if profile in {OWEN_READABLE_PROFILE, OWEN_FINAL_PROFILE}:
                from ocd_kernel.projection.categories.lib051_owen import verify
                return verify(root, acceptance_path=acceptance_path, rows=rows, receipt=receipt)
            from ocd_kernel.projection.categories.lib040_augustine_selected import PROFILE as SELECTED_PROFILE
            if profile == SELECTED_PROFILE:
                from ocd_kernel.projection.categories.lib040_augustine_selected import verify
                return verify(root, acceptance_path=acceptance_path, category='prose', rows=rows, receipt=receipt)
            from ocd_kernel.projection.categories.lib040_augustine_divisions import PROFILE as DIVISIONS_PROFILE
            if profile == DIVISIONS_PROFILE:
                from ocd_kernel.projection.categories.lib040_augustine_divisions import verify
                return verify(root, acceptance_path=acceptance_path, category='prose', rows=rows, receipt=receipt)
            from ocd_kernel.projection.categories.lib040_harmony import PROFILE, verify
            if profile != PROFILE:
                return [f'unsupported accepted prose projection profile: {profile}']
            return verify(root, acceptance_path=acceptance_path, rows=rows, receipt=receipt)
        if not _uses_native_content(context['edition'].path):
            from ocd_kernel.release.verify import verify_accepted
            return verify_accepted(root, acceptance_path=acceptance_path, rows=rows, receipt=receipt)
        from ocd_kernel.projection.categories.native_documents import verify_accepted_document
        return verify_accepted_document(root, acceptance_path=acceptance_path, rows=rows, receipt=receipt, category='prose')
    except (PipelineError, OSError, ValueError, KeyError, TypeError) as exc:
        return [str(exc)]
