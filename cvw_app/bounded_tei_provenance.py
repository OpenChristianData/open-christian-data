"""Opt-in WU-13 construction helpers, separate from registered CVW output.

Callers explicitly identify contributing parser elements and prior emissions.
No source reference is recovered from IDs, text, node equality, or position.
This process-local sidecar is neither a complete crosswalk nor an authenticated
persistent projection. Outline and table construction have separate opt-in
helpers; the bounded body helper rejects unbound nodes and unsupported wrappers.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Iterable, Mapping
from xml.etree import ElementTree

from cvw_app.bounded_xml_index import (
    ElementLocator,
    INDEXER_VERSION,
    IndexedTree,
    parse_indexed_master,
    _digest,
    _require_binding,
)
from cvw_app.renderer_nodes import (
    _DOCUMENT_NODE_TYPES,
    _validate_document_nodes,
    RendererError,
)

PROVENANCE_VERSION = "wu13-explicit-node-provenance-v1"


@dataclass(frozen=True)
class SourceReference:
    """An exact indexed source element; member identity is caller-declared."""

    master_member: str
    master_sha256: str
    indexer_version: str
    index_integrity: str
    renderer_version: str
    locator: ElementLocator


@dataclass(frozen=True)
class NodeProvenance:
    version: str
    occurrence: int
    sources: tuple[SourceReference, ...]
    derived_from: tuple[int, ...]
    no_source_reason: str | None


@dataclass(frozen=True)
class TracedNode:
    """Immutable emission snapshot; exporting produces ordinary CVW fields."""

    _node_json: str
    provenance: NodeProvenance

    def document_node(self) -> dict[str, Any]:
        return json.loads(self._node_json)


class ProvenanceBuilder:
    """Carry explicit references within one indexed-tree rendering session.

    Occurrence numbers identify this helper's emissions, not global CVW
    locations or pages. Source-free nodes must have an explicit reason.
    Derived nodes inherit the union of their explicitly supplied parents'
    references. A source reference indicates a contribution, not a claim that
    every byte in its element appears in the generated node.
    """

    def __init__(self, tree: IndexedTree, *, master_member: str,
                 expected_sha256: str, expected_renderer_version: str) -> None:
        _require_binding(expected_sha256, expected_renderer_version)
        member = PurePosixPath(master_member)
        if (not master_member or "\\" in master_member or ":" in master_member
                or member.is_absolute() or ".." in member.parts
                or member.as_posix() != master_member or master_member == "."):
            raise RendererError("provenance requires a canonical relative master member")
        index = tree.index
        if (index.master_sha256 != expected_sha256
                or index.renderer_version != expected_renderer_version
                or index.indexer_version != INDEXER_VERSION
                or index.integrity_sha256 != _digest(index)):
            raise RendererError("provenance index binding mismatch")
        # Consume only the parser-owned mapping. This is identity validation,
        # not an attempt to reconstruct a mapping from another tree traversal.
        references = {}
        for element, locator in tree.source_elements.items():
            if (type(locator.ordinal) is not int
                    or not 0 <= locator.ordinal < len(index.elements)
                    or index.elements[locator.ordinal] is not locator):
                raise RendererError("provenance has an unbound source locator")
            references[element] = SourceReference(
                master_member, index.master_sha256, index.indexer_version,
                index.integrity_sha256, index.renderer_version, locator,
            )
        if tree.root not in references:
            raise RendererError("provenance has no indexed root identity")
        self._references = references
        self._issued: dict[int, TracedNode] = {}

    def emit(self, node: dict[str, Any], *,
             sources: Iterable[ElementTree.Element] = (),
             derived_from: Iterable[TracedNode] = (),
             no_source_reason: str | None = None) -> TracedNode:
        """Snapshot one explicit occurrence, including splits and wrappers.

        Pass original parser elements for direct contributions. Pass returned
        TracedNodes for copied, split, aggregated, or wrapper contributions.
        Foreign or reconstructed emissions fail even if their values match.
        A failure consumes no occurrence number and returns no partial node.
        """
        references: dict[SourceReference, None] = {}
        parents: dict[int, None] = {}
        for element in sources:
            try:
                reference = self._references[element]
            except (KeyError, TypeError) as error:
                raise RendererError("provenance source has no parser identity") from error
            references[reference] = None
        for parent in derived_from:
            if (not isinstance(parent, TracedNode)
                    or self._issued.get(id(parent)) is not parent):
                raise RendererError("provenance parent is not an emission of this session")
            parents[parent.provenance.occurrence] = None
            references.update(dict.fromkeys(parent.provenance.sources))
        if no_source_reason is not None and (
            not isinstance(no_source_reason, str) or not no_source_reason.strip()
        ):
            raise RendererError("source-free provenance requires a nonempty reason")
        if not references and no_source_reason is None:
            raise RendererError("provenance has neither source references nor a no-source reason")
        if references and no_source_reason is not None:
            raise RendererError("source-backed provenance cannot claim no source")
        _validate_document_nodes([node], "provenance emission",
                                 allowed_types=_DOCUMENT_NODE_TYPES,
                                 validated_nodes=set(), active_nodes=set())
        packed = json.dumps(node, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        result = TracedNode(packed, NodeProvenance(
            PROVENANCE_VERSION, len(self._issued), tuple(references), tuple(parents),
            no_source_reason,
        ))
        self._issued[id(result)] = result
        return result


def render_outline_provenance(master: Path, *, expected_sha256: str,
                              master_member: str) -> tuple[dict[str, Any], Mapping[str, TracedNode]]:
    """Opt-in full render with source bindings for outline nodes only.

    Reread and hash the master in the indexed parser. Every actual outline
    allocation must invoke the renderer's construction callback with an
    original parser element or an explicitly bound renderer fragment. Fragment
    bindings describe their owning element, not exact displayed byte coverage. Empty outlines return an empty
    mapping, never a claim that body/page provenance is covered.
    """
    from cvw_app.bounded_tei_projection import renderer_version
    from cvw_app.renderer_nodes import _validate_renderer_output
    from cvw_app.tei_renderer import _render_tei_root

    version = renderer_version()
    tree = parse_indexed_master(master, expected_sha256=expected_sha256,
                                 renderer_version=version)
    builder = ProvenanceBuilder(tree, master_member=master_member,
                                expected_sha256=expected_sha256,
                                expected_renderer_version=version)
    bindings: dict[str, TracedNode] = {}
    contributions = {element: element for element in tree.source_elements}

    def fragment_created(source: ElementTree.Element, fragment: ElementTree.Element) -> None:
        if fragment in contributions or source not in contributions:
            raise RendererError("fragment provenance has an unbound source or reused identity")
        contributions[fragment] = contributions[source]


    def emitted(element: ElementTree.Element, node: dict[str, Any]) -> None:
        location = node.get("location")
        if not isinstance(location, str) or location in bindings:
            raise RendererError("outline provenance has a missing or duplicate allocated location")
        if element not in contributions:
            raise RendererError("provenance source has no parser identity or explicit fragment binding")
        bindings[location] = builder.emit(node, sources=[contributions[element]])

    rendered = _validate_renderer_output(_render_tei_root(
        tree.root, _on_outline_node=emitted, _on_fragment=fragment_created))
    if [item["location"] for item in rendered["outline"]] != list(bindings):
        raise RendererError("outline provenance coverage does not match allocated locations")
    return rendered, MappingProxyType(bindings)


def render_table_provenance(master: Path, *, expected_sha256: str,
                            master_member: str) -> tuple[dict[str, Any], tuple[TracedNode, ...]]:
    """Snapshot table construction, not final document or page occurrences.

    Each cell, row, or table has its explicit contributing source owner. Rows
    and tables also inherit their actual constructed children's emissions.
    Intermediate empty rows are retained even when no table reaches output.
    Inline descendants are covered only by their cell owner's contribution;
    neither complete byte coverage nor a final-output crosswalk is claimed.
    """
    from cvw_app.bounded_tei_projection import renderer_version
    from cvw_app.renderer_nodes import _validate_renderer_output
    from cvw_app.tei_renderer import _render_tei_root

    version = renderer_version()
    tree = parse_indexed_master(master, expected_sha256=expected_sha256,
                               renderer_version=version)
    builder = ProvenanceBuilder(tree, master_member=master_member,
                                expected_sha256=expected_sha256,
                                expected_renderer_version=version)
    contributions = {element: element for element in tree.source_elements}
    emissions: dict[int, tuple[dict[str, Any], TracedNode]] = {}

    def fragment_created(source: ElementTree.Element, fragment: ElementTree.Element) -> None:
        if fragment in contributions or source not in contributions:
            raise RendererError("fragment provenance has an unbound source or reused identity")
        contributions[fragment] = contributions[source]

    def emitted(element: ElementTree.Element, node: dict[str, Any]) -> None:
        if element not in contributions:
            raise RendererError("table provenance source has no parser identity or fragment binding")
        if id(node) in emissions:
            raise RendererError("table provenance reused a construction identity")
        parents = []
        for child in node.get("children", []):
            binding = emissions.get(id(child))
            if binding is None or binding[0] is not child:
                raise RendererError("table provenance child has no construction identity")
            parents.append(binding[1])
        traced = builder.emit(node, sources=[contributions[element]], derived_from=parents)
        emissions[id(node)] = (node, traced)

    rendered = _validate_renderer_output(_render_tei_root(
        tree.root, _on_table_node=emitted, _on_fragment=fragment_created))
    def check_nodes(nodes: Iterable[dict[str, Any]]) -> None:
        for node in nodes:
            if node["type"] in {"table", "table-row", "table-cell", "table-header"}:
                binding = emissions.get(id(node))
                if binding is None or binding[0] is not node:
                    raise RendererError("table provenance coverage lacks construction identity")
            check_nodes(node.get("children", []))

    check_nodes(rendered["nodes"])
    return rendered, tuple(binding[1] for binding in emissions.values())


def emit_inline_provenance(builder: ProvenanceBuilder, node_type: str,
                           element: ElementTree.Element, **extra: Any) -> TracedNode:
    """Trace an explicit inline-node construction, never a final page occurrence.

    Normalization carries parser handles for surviving text, pending whitespace,
    labels, and enclosing wrappers. Tails name their owning child plus ancestors.
    These are element contributions, not text-slot or byte-coverage claims.
    Empty output retains its explicitly supplied element owner. Copies must be
    bound by another construction helper; this seam rejects foreign elements.
    """
    from cvw_app.tei_inline import inline_node

    emitted = []

    def capture(node, sources):
        emitted.append(builder.emit(node, sources=(element, *sources)))

    inline_node(node_type, element, _on_contributions=capture, **extra)
    return emitted[0]


@dataclass(frozen=True)
class BodyProvenance:
    """Immutable canonical node and supported-page construction snapshots.

    Page tuples preserve actual renderer occurrence order. Canonical ordinary
    leaf splits and list/JSON-page wrappers inherit their original node. Page nodes without
    construction bindings fail closed. Context truncations inherit the exact
    selected body nodes; served replacements and full byte coverage are outside this proof.
    """

    nodes: tuple[TracedNode, ...]
    pages: tuple[tuple[TracedNode, ...], ...]
    emissions: tuple[TracedNode, ...]


def render_body_provenance(master: Path, *, expected_sha256: str,
                           master_member: str,
                           _on_bound_output=None) -> tuple[dict[str, Any], BodyProvenance]:
    """Trace inline paragraphs, headings, lists, quotes, and plain verse.

    Plain lines and flat plain stanzas bind their parser owners before text
    aggregation, including empty lines that contribute stanza separators.
    Mixed/nested verse and other unsupported aggregation branches are rejected,
    never assigned an inferred owner from text, IDs, or position.
    Ordinary lossless visible-leaf splits and list/JSON wrappers bind actual final pages.
    JSON wrappers require already-bound parents and properties; this adds no
    native JSON source-emission route.
    Structure-context truncations inherit the exact selected body emissions.
    This opt-in proof uses renderer callbacks, never value-matched ownership.
    """
    from cvw_app.bounded_tei_projection import renderer_version
    from cvw_app.renderer_nodes import _validate_renderer_output
    from cvw_app.tei_renderer import _render_tei_root

    version = renderer_version()
    tree = parse_indexed_master(master, expected_sha256=expected_sha256,
                               renderer_version=version)
    builder = ProvenanceBuilder(tree, master_member=master_member,
                                expected_sha256=expected_sha256,
                                expected_renderer_version=version)
    contributions = {element: element for element in tree.source_elements}
    bindings: dict[int, tuple[dict[str, Any], TracedNode]] = {}
    emissions = []

    def fragment_created(source, fragment):
        if fragment in contributions or source not in contributions:
            raise RendererError("body fragment has an unbound source or reused identity")
        contributions[fragment] = contributions[source]

    def bound(node):
        binding = bindings.get(id(node))
        if binding is None or binding[0] is not node:
            raise RendererError("body/page contribution lacks construction identity")
        if binding[1].document_node() != node:
            raise RendererError("body/page contribution changed without replacement")
        return binding[1]

    def emitted(element, node, sources, *, replacement=False):
        parents = []
        previous = bindings.get(id(node))
        if replacement:
            if previous is None or previous[0] is not node:
                raise RendererError("body replacement has no construction identity")
            parents.append(previous[1])
        elif previous is not None:
            raise RendererError("body contribution reused a construction identity")
        parents.extend(bound(child) for child in node.get("children", []))
        try:
            owners = tuple(contributions[source] for source in (element, *sources))
        except (KeyError, TypeError) as error:
            raise RendererError("body contribution has no parser or fragment identity") from error
        traced = builder.emit(node, sources=owners, derived_from=parents)
        bindings[id(node)] = (node, traced)
        emissions.append(traced)

    def table_emitted(element, node):
        """Bind table cells, rows, and wrappers before body/page lookup."""
        previous = bindings.get(id(node))
        if previous is not None:
            raise RendererError("table contribution reused a construction identity")
        try:
            owners = tuple(contributions[source] for source in element.iter())
        except (KeyError, TypeError) as error:
            raise RendererError("table contribution has no parser identity") from error
        parents = [bound(child) for child in node.get("children", [])]
        traced = builder.emit(node, sources=owners, derived_from=parents)
        bindings[id(node)] = (node, traced)
        emissions.append(traced)

    def page_split(original, fragment):
        # The validator constructs the actual returned page fragments. Bind
        # those identities here, not the discarded first-pass renderer pages.
        parent = bound(original)
        if id(fragment) in bindings:
            raise RendererError("page split reused a construction identity")
        traced = builder.emit(fragment, derived_from=(parent,))
        bindings[id(fragment)] = (fragment, traced)
        emissions.append(traced)

    def container_page(original, wrapper):
        # Wrapper kind/metadata depends on the complete original container.
        # Inherited sources conservatively describe that dependency, not
        # proof that all original sibling text is displayed on this page.
        parent = bound(original)
        if id(wrapper) in bindings:
            raise RendererError("container page reused a construction identity")
        children = tuple(bound(child) for child in wrapper["children"])
        traced = builder.emit(wrapper, derived_from=(parent, *children))
        bindings[id(wrapper)] = (wrapper, traced)
        emissions.append(traced)

    def context_replaced(originals, replacement):
        # The finalizer supplies the selected live nodes before replacing them.
        # Matching text or location cannot recover a missing identity.
        if not originals:
            raise RendererError("context replacement has no construction parents")
        parents = tuple(bound(original) for original in originals)
        if id(replacement) in bindings:
            raise RendererError("context replacement reused a construction identity")
        traced = builder.emit(replacement, derived_from=parents)
        bindings[id(replacement)] = (replacement, traced)
        emissions.append(traced)

    rendered = _validate_renderer_output(_render_tei_root(
        tree.root, _on_body_node=emitted, _on_table_node=table_emitted,
        _on_fragment=fragment_created,
        _on_context_replacement=context_replaced), _on_page_split=page_split,
        _on_list_page=container_page, _on_json_page=container_page,
        _on_context_replacement=context_replaced)
    canonical = tuple(bound(node) for node in rendered["nodes"])
    pages = tuple(tuple(bound(node) for node in page) for page in rendered["_pages"])
    proof = BodyProvenance(canonical, pages, tuple(emissions))
    # Internal opt-in continuation receives the live session and identity lookup,
    # never a positional reconstruction of the immutable page snapshots.
    if _on_bound_output is not None:
        _on_bound_output(rendered, builder, bound)
    return rendered, proof
