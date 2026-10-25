"""Opt-in served-node lineage; no route, cold reader, or byte-coverage claim."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cvw_app.bounded_tei_provenance import (
    BodyProvenance, TracedNode, render_body_provenance,
)
from cvw_app.renderer_nodes import RendererError
from cvw_app.review_contract import ReviewApplication


@dataclass(frozen=True)
class ServedProvenance:
    """Body emissions plus selected served occurrences and optional context.

    Unchanged nodes reuse their construction snapshot. Atomic truncations are
    new emissions derived from the exact page nodes supplied at replacement.
    SHA-mark context replacements inherit their selected construction nodes.
    Unsupported wrappers fail closed. This is process-local
    contribution evidence, not complete source text or byte ownership.
    """

    body: BodyProvenance
    served: tuple[TracedNode, ...]
    context: tuple[TracedNode, ...] | None


def render_served_provenance(
    master: Path, *, expected_sha256: str, master_member: str,
    start: int = 0, limit: int = 1, context_location: str | None = None,
) -> tuple[dict[str, Any], ServedProvenance]:
    """Render the supported body subset and trace an explicit segment selection.

    All body/page coverage must pass before selection. Unsupported non-list synthetic
    page wrappers are rejected even if outside this selection. No ownership is recovered
    from equal text, source IDs, page positions, or outline contributors.
    """
    if (type(start) is not int or type(limit) is not int
            or start < 0 or limit < 1):
        raise RendererError("served provenance requires a nonnegative start and positive limit")
    if context_location is not None and (
        not isinstance(context_location, str) or not context_location
    ):
        raise RendererError("served provenance context location must be a nonempty string")
    served: list[TracedNode] = []
    context = None

    def ready(rendered, builder, bound):
        nonlocal context
        if start + limit > len(rendered["segments"]):
            raise RendererError("served provenance segment range is out of bounds")

        def emitted(node, originals, *, replacement):
            parents = tuple(bound(original) for original in originals)
            if replacement:
                if not parents:
                    raise RendererError("served replacement has no construction parents")
                served.append(builder.emit(node, derived_from=parents))
            else:
                if len(originals) != 1 or originals[0] is not node:
                    raise RendererError("unchanged served node lacks construction identity")
                served.append(bound(node))

        ReviewApplication._served_page_nodes(
            None, rendered, start, limit, _on_served_node=emitted)
        if context_location is not None:
            if context_location not in rendered["contexts"]:
                raise RendererError("served provenance context location is unavailable")
            context = tuple(bound(node) for node in rendered["contexts"][context_location]["nodes"])

    rendered, body = render_body_provenance(
        master, expected_sha256=expected_sha256, master_member=master_member,
        _on_bound_output=ready)
    return rendered, ServedProvenance(body, tuple(served), context)
