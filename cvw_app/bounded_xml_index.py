"""Disposable single-master XML index primitives for WU-13.

This module is deliberately not registered as a CVW renderer. XML element
ordinals are source locators, not CVW locations or segment numbers. An adapter
must prove global renderer equivalence before it can serve these fragments.
The index contains no character data and never owns corrected text. Building
it parses the complete master; selecting retains only a bounded byte range,
but still hashes the complete master before returning anything.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Mapping
from xml.etree import ElementTree
from xml.parsers import expat

from cvw_app.renderer_nodes import RendererError

INDEXER_VERSION = "wu13-xml-source-index-v1"
_XML = "http://www.w3.org/XML/1998/namespace}"
_CHUNK_BYTES = 64 * 1024


@dataclass(frozen=True)
class ElementLocator:
    ordinal: int
    parent: int | None
    expanded_name: str
    attributes: tuple[tuple[str, str], ...]
    namespace_declarations: tuple[tuple[str, str], ...]
    start: int
    end: int


@dataclass(frozen=True)
class MasterIndex:
    master_sha256: str
    indexer_version: str
    renderer_version: str
    byte_count: int
    elements: tuple[ElementLocator, ...]
    integrity_sha256: str


@dataclass(frozen=True)
class IndexedTree:
    """One verified parse with construction-time element identities.

    The tree is mutable renderer input, not immutable authority. The mapping
    identifies retained XML elements only; generated renderer occurrences still
    require explicit provenance propagation. This full-tree API is not bounded.
    """

    index: MasterIndex
    root: ElementTree.Element
    source_elements: Mapping[ElementTree.Element, ElementLocator]


@dataclass(frozen=True)
class VerifiedFragment:
    """Exact source bytes plus ancestry, never a renderable standalone document."""

    payload: bytes
    locator: ElementLocator
    ancestors: tuple[ElementLocator, ...]
    namespace_bindings: tuple[tuple[str, str], ...]
    xml_space: str | None
    master_sha256: str
    bytes_verified: int

    def cvw_presentation(self) -> dict:
        raise RendererError(
            "bounded XML index has no equivalent CVW projection adapter; "
            "global locations, outline, segments, notes, and shared context "
            "must be verified before serving a selected view"
        )


def _digest(index: MasterIndex) -> str:
    value = asdict(index)
    value.pop("integrity_sha256")
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")
    ).hexdigest()


def _require_binding(expected_sha256: str, renderer_version: str) -> None:
    if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise RendererError("master digest must be lowercase SHA-256")
    if not renderer_version or not renderer_version.strip():
        raise RendererError("an explicit renderer version is required")


def _parse_master(
    master: Path,
    *,
    expected_sha256: str,
    renderer_version: str,
    max_elements: int = 1_000_000,
    tree_builder: ElementTree.TreeBuilder | None = None,
    element_ordinals: dict[ElementTree.Element, int] | None = None,
) -> MasterIndex:
    """Parse and hash all UTF-8 XML bytes without retaining the text tree.

    Duplicate IDs remain distinct element ordinals. DTDs/entities and other
    encodings fail closed in this initial bounded subset. No index is returned
    for malformed XML, a digest mismatch, or an exceeded element budget.
    """
    _require_binding(expected_sha256, renderer_version)
    if max_elements < 1:
        raise RendererError("element budget must be positive")
    parser = expat.ParserCreate(namespace_separator="}")
    records: list[ElementLocator] = []
    stack: list[int] = []
    empty_elements: set[int] = set()
    declarations: list[tuple[str, str]] = []

    def reject_dtd(*_args: object) -> None:
        raise RendererError("bounded XML index does not support DTDs or entities")

    def declaration(_version: str, encoding: str | None, _standalone: int) -> None:
        if encoding is not None and encoding.lower().replace("-", "") != "utf8":
            raise RendererError("bounded XML index supports UTF-8 masters only")

    def start(name: str, attributes: dict[str, str]) -> None:
        if len(records) >= max_elements:
            raise RendererError("bounded XML index element budget exceeded")
        ordinal = len(records)
        context = parser.GetInputContext() or b""
        quote = None
        for position, byte in enumerate(context):
            if quote is not None:
                if byte == quote:
                    quote = None
            elif byte in (34, 39):
                quote = byte
            elif byte == 62:
                if position and context[position - 1] == 47:
                    empty_elements.add(ordinal)
                break
        else:
            raise RendererError("opening tag exceeds available parser context")
        records.append(ElementLocator(
            ordinal, stack[-1] if stack else None, name,
            tuple(attributes.items()), tuple(declarations),
            parser.CurrentByteIndex, -1,
        ))
        if tree_builder is not None:
            # Both identities originate in this exact parser callback. Never
            # pair a second parser's traversal positions or source IDs.
            def expanded(value: str) -> str:
                return "{" + value if "}" in value else value

            element = tree_builder.start(
                expanded(name), {expanded(key): value for key, value in attributes.items()}
            )
            assert element_ordinals is not None
            element_ordinals[element] = ordinal
        declarations.clear()
        stack.append(ordinal)

    def end(_name: str) -> None:
        ordinal = stack.pop()
        offset = parser.CurrentByteIndex
        context = parser.GetInputContext() or b""
        # Expat reports the start of a closing tag, but the byte immediately
        # after an empty-element tag. XML names cannot contain a '>' character.
        if ordinal in empty_elements:
            empty_elements.remove(ordinal)
        elif context.startswith(b"</"):
            boundary = context.find(b">")
            if boundary < 0:
                raise RendererError("closing tag exceeds available parser context")
            offset += boundary + 1
        records[ordinal] = replace(records[ordinal], end=offset)
        if tree_builder is not None:
            tree_builder.end("{" + _name if "}" in _name else _name)

    parser.XmlDeclHandler = declaration
    parser.StartDoctypeDeclHandler = reject_dtd
    parser.EntityDeclHandler = reject_dtd
    parser.ExternalEntityRefHandler = reject_dtd
    parser.StartNamespaceDeclHandler = lambda prefix, uri: declarations.append(
        (prefix or "", uri or "")
    )
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    if tree_builder is not None:
        parser.CharacterDataHandler = tree_builder.data
    digest = hashlib.sha256()
    count = 0
    try:
        with master.open("rb") as stream:
            while chunk := stream.read(_CHUNK_BYTES):
                if count == 0 and (chunk.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in chunk):
                    raise RendererError("bounded XML index supports UTF-8 masters only")
                count += len(chunk)
                digest.update(chunk)
                parser.Parse(chunk, False)
            parser.Parse(b"", True)
    except expat.ExpatError as exc:
        raise RendererError(f"bounded XML master is malformed: {exc}") from exc
    if digest.hexdigest() != expected_sha256:
        raise RendererError("master bytes do not match declared sha256")
    index = MasterIndex(expected_sha256, INDEXER_VERSION, renderer_version,
                        count, tuple(records), "")
    return replace(index, integrity_sha256=_digest(index))


def build_index(master: Path, *, expected_sha256: str, renderer_version: str,
                max_elements: int = 1_000_000) -> MasterIndex:
    """Stream source locators without constructing or retaining a text tree."""
    return _parse_master(master, expected_sha256=expected_sha256,
                         renderer_version=renderer_version, max_elements=max_elements)


def parse_indexed_master(master: Path, *, expected_sha256: str, renderer_version: str,
                         max_elements: int = 1_000_000) -> IndexedTree:
    """Construct the renderer tree and byte locators in one hash-verified parse.

    Comments and processing instructions are ignored just as in the existing
    ElementTree renderer. Tail text, expanded names, and XML whitespace remain
    parser-derived. No result escapes on malformed or stale source bytes.
    """
    builder = ElementTree.TreeBuilder()
    ordinals: dict[ElementTree.Element, int] = {}
    index = _parse_master(master, expected_sha256=expected_sha256,
                          renderer_version=renderer_version, max_elements=max_elements,
                          tree_builder=builder, element_ordinals=ordinals)
    return IndexedTree(index, builder.close(), MappingProxyType({
        element: index.elements[ordinal] for element, ordinal in ordinals.items()
    }))


def read_fragment(
    master: Path,
    index: MasterIndex,
    ordinal: int,
    *,
    expected_sha256: str,
    renderer_version: str,
    max_fragment_bytes: int = 4 * 1024 * 1024,
) -> VerifiedFragment:
    """Capture selected bytes in the same pass that verifies the full master.

    Integrity covers accidental in-memory index alteration; this API does not
    deserialize or trust an external index. Context is structural ancestry,
    not a substitute for the renderer's global shared heading/note context.
    """
    _require_binding(expected_sha256, renderer_version)
    if (index.master_sha256 != expected_sha256
            or index.indexer_version != INDEXER_VERSION
            or index.renderer_version != renderer_version):
        raise RendererError("bounded XML index binding mismatch; rebuild required")
    if _digest(index) != index.integrity_sha256:
        raise RendererError("bounded XML index integrity mismatch; rebuild required")
    if type(ordinal) is not int or not 0 <= ordinal < len(index.elements):
        raise RendererError("unknown source element ordinal")
    selected = index.elements[ordinal]
    if not 0 <= selected.start < selected.end <= index.byte_count:
        raise RendererError("bounded XML index has an invalid byte range")
    if max_fragment_bytes < 1 or selected.end - selected.start > max_fragment_bytes:
        raise RendererError("selected XML exceeds the fragment byte budget")
    digest = hashlib.sha256()
    payload = bytearray()
    count = 0
    with master.open("rb") as stream:
        while chunk := stream.read(_CHUNK_BYTES):
            digest.update(chunk)
            start = max(selected.start - count, 0)
            end = min(selected.end - count, len(chunk))
            if start < end:
                payload.extend(chunk[start:end])
            count += len(chunk)
    if count != index.byte_count or digest.hexdigest() != expected_sha256:
        raise RendererError("master bytes no longer match the indexed sha256")
    ancestors: list[ElementLocator] = []
    parent = selected.parent
    while parent is not None:
        if not 0 <= parent < selected.ordinal or (ancestors and parent >= ancestors[-1].ordinal):
            raise RendererError("bounded XML index has invalid ancestry")
        ancestor = index.elements[parent]
        ancestors.append(ancestor)
        parent = ancestor.parent
    ancestors.reverse()
    bindings = {"xml": _XML[:-1]}
    space = None
    for entry in (*ancestors, selected):
        bindings.update(entry.namespace_declarations)
        space = dict(entry.attributes).get(_XML + "space", space)
    return VerifiedFragment(bytes(payload), selected, tuple(ancestors),
                            tuple(bindings.items()), space, expected_sha256, count)
