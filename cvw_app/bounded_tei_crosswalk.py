"""Opt-in process-local TEI element contribution crosswalk for supported output.

The member name is caller-declared; records are parser-owned TEI elements,
not original acquisition/commentary records. No complete source/byte coverage,
persistent authentication, outline mapping, or bounded admission is claimed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cvw_app.bounded_tei_pagination import ServedProvenance, render_served_provenance
from cvw_app.bounded_tei_provenance import SourceReference, TracedNode
from cvw_app.renderer_nodes import RendererError


@dataclass(frozen=True)
class OutputOccurrence:
    """An output address attached to an already proven construction identity.

    Ordinals name output slots only; they never establish source ownership.
    Page is populated only for page slots. Context uses the requested location.
    """

    surface: str
    ordinal: int
    node: TracedNode
    page: int | None = None
    context_location: str | None = None


@dataclass(frozen=True)
class SourceRecordCrosswalk:
    source: SourceReference
    emissions: tuple[TracedNode, ...]
    outputs: tuple[OutputOccurrence, ...]


@dataclass(frozen=True)
class ContributionCrosswalk:
    """Complete supported output incidence, not complete source accounting.

    Records include explicitly contributing sources only, including construction
    emissions absent from final output. Repeated output slots stay distinct.
    Source-free outputs, if any, retain their explicit reasons in their nodes.
    """

    records: tuple[SourceRecordCrosswalk, ...]
    outputs: tuple[OutputOccurrence, ...]
    source_free_outputs: tuple[OutputOccurrence, ...]
    proof: ServedProvenance


def _crosswalk(proof: ServedProvenance, context_location: str | None) -> ContributionCrosswalk:
    # Only called with the fresh producer result, never an expected mapping.
    issued: dict[int, TracedNode] = {}
    occurrences: dict[int, TracedNode] = {}
    for node in (*proof.body.emissions, *proof.served):
        if id(node) in issued:
            continue
        provenance = node.provenance
        if provenance.occurrence in occurrences:
            raise RendererError("crosswalk has a foreign or duplicate construction occurrence")
        for parent in provenance.derived_from:
            if parent not in occurrences:
                raise RendererError("crosswalk has an unresolved construction parent")
        if not provenance.sources and not provenance.no_source_reason:
            raise RendererError("crosswalk has an unexplained source-free construction")
        issued[id(node)] = node
        occurrences[provenance.occurrence] = node

    outputs = []

    def attach(surface, nodes, *, page=None, location=None):
        for ordinal, node in enumerate(nodes):
            if issued.get(id(node)) is not node:
                raise RendererError("crosswalk output lacks construction identity")
            outputs.append(OutputOccurrence(surface, ordinal, node, page, location))

    attach("body", proof.body.nodes)
    for page, nodes in enumerate(proof.body.pages):
        attach("page", nodes, page=page)
    attach("served", proof.served)
    if proof.context is not None:
        if context_location is None:
            raise RendererError("crosswalk context has no selected location")
        attach("context", proof.context, location=context_location)

    # Group by the actual immutable SourceReference object emitted by the
    # builder, not by a text/ID/ordinal comparison against another tree.
    sources: dict[int, SourceReference] = {}
    emissions: dict[int, list[TracedNode]] = {}
    incidence: dict[int, list[OutputOccurrence]] = {}
    for node in issued.values():
        for source in node.provenance.sources:
            key = id(source)
            sources[key] = source
            emissions.setdefault(key, []).append(node)
            incidence.setdefault(key, [])
    for output in outputs:
        for source in output.node.provenance.sources:
            incidence[id(source)].append(output)
    return ContributionCrosswalk(
        tuple(SourceRecordCrosswalk(source, tuple(emissions[key]), tuple(incidence[key]))
              for key, source in sources.items()),
        tuple(outputs),
        tuple(output for output in outputs if not output.node.provenance.sources),
        proof,
    )


def render_contribution_crosswalk(
    master: Path, *, expected_sha256: str, master_member: str,
    start: int = 0, limit: int = 1, context_location: str | None = None,
) -> tuple[dict[str, Any], ContributionCrosswalk]:
    """Build from a fresh hash-verified parse and renderer construction events.

    Every body/page/selected served/context slot must have a construction
    binding. Unsupported render or pagination branches fail before returning.
    No caller-supplied proof, source inventory, or expected map is accepted.
    """
    rendered, proof = render_served_provenance(
        master, expected_sha256=expected_sha256, master_member=master_member,
        start=start, limit=limit, context_location=context_location,
    )
    return rendered, _crosswalk(proof, context_location)
