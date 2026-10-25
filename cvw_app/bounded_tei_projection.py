"""WU-13 opt-in projection proof seam; not a registered renderer or route.

Admission deliberately runs the complete existing renderer. Immutable projections
preserve its globally allocated locations (including duplicate source IDs),
outline, shared context and page numbers. They are disposable, derived text,
never master authority. Selection verifies the complete master again and uses
the existing stage-view page projector. A bounded source-ordinal-to-CVW-unit
mapping and bounded admission/residency remain required before route activation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from cvw_app.bounded_xml_index import MasterIndex, read_fragment
from cvw_app.renderer_nodes import RendererError
from cvw_app.review_contract import ReviewApplication
from cvw_app.review_renderers import DEFAULT_RENDERER_REGISTRY


def renderer_version() -> str:
    """Bind all rendering and serve-time projection code, not a caller label."""
    digest = hashlib.sha256()
    for name in ("tei_renderer.py", "tei_inline.py", "renderer_nodes.py",
                 "review_renderers.py", "review_contract.py", "bounded_xml_index.py",
                 "bounded_tei_projection.py", "bounded_tei_provenance.py"):
        digest.update(name.encode("ascii"))
        digest.update(Path(__file__).with_name(name).read_bytes())
    return "wu13-cvw-projection-v1-" + digest.hexdigest()


def _pack(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class Projection:
    master_sha256: str
    index_integrity: str
    renderer_version: str
    outline_json: str
    contexts: tuple[tuple[str, str], ...]
    segments: tuple[str, ...]
    pages: tuple[str, ...]
    integrity_sha256: str
    source_bindings: tuple[str, ...] | None = None


def _digest(projection: Projection) -> str:
    values = [
        projection.master_sha256, projection.index_integrity,
        projection.renderer_version, projection.outline_json,
        projection.contexts, projection.segments, projection.pages,
    ]
    if projection.source_bindings is not None:
        values.append(projection.source_bindings)
    return hashlib.sha256(_pack(values).encode("utf-8")).hexdigest()


PAGE_BINDING_VERSION = "wu13-outline-page-binding-v1"


def _text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _page_bindings(master: Path, index: MasterIndex, rendered: dict[str, Any],
                   pages: tuple[str, ...], *, expected_sha256: str,
                   master_member: str) -> tuple[str, ...]:
    """Bind served pages to explicit outline contributions, never body ownership.

    The outline hook owns location-to-source identity. Segment locations only
    select those already bound outline occurrences; they do not prove that all
    page text descends from an outline owner. Keep that coverage unknown.
    """
    from cvw_app.bounded_tei_provenance import render_outline_provenance

    traced_render, bindings = render_outline_provenance(
        master, expected_sha256=expected_sha256, master_member=master_member)
    if traced_render != rendered:
        raise RendererError("page provenance differs from full-render oracle")
    locations = [node["location"] for node in rendered["outline"]]
    if len(set(locations)) != len(locations) or set(bindings) != set(locations):
        raise RendererError("page provenance has missing or ambiguous outline bindings")
    for location, traced in bindings.items():
        if traced.document_node().get("location") != location or not traced.provenance.sources:
            raise RendererError("page provenance has missing or ambiguous source binding")
        for source in traced.provenance.sources:
            ordinal = source.locator.ordinal
            if (source.master_member != master_member
                    or source.master_sha256 != expected_sha256
                    or source.index_integrity != index.integrity_sha256
                    or source.indexer_version != index.indexer_version
                    or source.renderer_version != index.renderer_version
                    or type(ordinal) is not int or not 0 <= ordinal < len(index.elements)
                    or source.locator != index.elements[ordinal]):
                raise RendererError("page provenance source binding mismatch")
    records = []
    for number, descriptor in enumerate(rendered["segments"]):
        page_locations = descriptor["locations"]
        if len(set(page_locations)) != len(page_locations) or any(
            location not in bindings for location in page_locations
        ):
            raise RendererError("page provenance has missing or ambiguous page bindings")
        records.append(_pack({
            "version": PAGE_BINDING_VERSION,
            "segment": number,
            "segment_sha256": _text_digest(_pack(descriptor)),
            "served_page_sha256": _text_digest(pages[number]),
            "served_replacement": bool(descriptor.get("truncated")),
            "outline_contributions": [
                {"location": location, "provenance": asdict(bindings[location].provenance)}
                for location in page_locations
            ],
            "body_ownership": "unknown",
            "requires_check": True,
        }))
    return tuple(records)


def _selected_page_binding(projection: Projection, segment: int) -> dict[str, Any]:
    records = projection.source_bindings
    if not isinstance(records, tuple) or len(records) != len(projection.pages):
        raise RendererError("page provenance has missing page bindings")
    try:
        record = json.loads(records[segment])
    except (TypeError, ValueError) as error:
        raise RendererError("page provenance binding is malformed") from error
    if (not isinstance(record, dict)
            or record.get("version") != PAGE_BINDING_VERSION
            or type(record.get("segment")) is not int or record["segment"] != segment
            or record.get("segment_sha256") != _text_digest(projection.segments[segment])
            or record.get("served_page_sha256") != _text_digest(projection.pages[segment])
            or record.get("body_ownership") != "unknown"
            or record.get("requires_check") is not True):
        raise RendererError("page provenance binding or version mismatch")
    return record


def build_projection(master: Path, index: MasterIndex, *, expected_sha256: str,
                     master_member: str | None = None,
                     observe_render_input: Callable[[int], None] | None = None) -> Projection:
    """Full-render admission oracle. No claim of bounded admission or memory."""
    version = renderer_version()
    smallest = min(index.elements, key=lambda entry: entry.end - entry.start)
    fragment = read_fragment(master, index, smallest.ordinal, expected_sha256=expected_sha256,
                             renderer_version=version, max_fragment_bytes=index.byte_count)
    # Parse the original complete document, including declarations and comments.
    payload = master.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise RendererError("master changed during projection admission")
    try:
        exact = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RendererError("projection requires UTF-8 TEI") from error
    rendered, supported = DEFAULT_RENDERER_REGISTRY.render("tei-reader", "application/tei+xml", exact)
    if not supported:
        raise RendererError("TEI projection renderer is unavailable")
    if observe_render_input is not None:
        # Actual successful renderer input volume, not an estimate of internal
        # reparses, file reads, or HTTP transfer. Provenance rendering is separate.
        observe_render_input(len(payload))
    # Reuse the stage-view implementation, including truncated atomic segments.
    pages = tuple(_pack(ReviewApplication._served_page_nodes(None, rendered, i, 1))
                  for i in range(len(rendered["segments"])))
    values = dict(master_sha256=fragment.master_sha256,
                  index_integrity=index.integrity_sha256, renderer_version=version,
                  outline_json=_pack(rendered["outline"]),
                  contexts=tuple((key, _pack(value)) for key, value in rendered["contexts"].items()),
                  segments=tuple(_pack(value) for value in rendered["segments"]), pages=pages,
                  source_bindings=None if master_member is None else _page_bindings(
                      master, index, rendered, pages, expected_sha256=expected_sha256,
                      master_member=master_member))
    candidate = Projection(**values, integrity_sha256="")
    return Projection(**values, integrity_sha256=_digest(candidate))


def select_projection(master: Path, index: MasterIndex, projection: Projection, *,
                      expected_sha256: str, location: str, segment: int) -> dict[str, Any]:
    """Serve one global CVW location and page; no inferred source-ID mapping.

    Missing locations fail closed instead of silently selecting a neighbor.
    Source fragment provenance is not advertised as a CVW unit crosswalk.
    """
    version = renderer_version()
    if (projection.master_sha256 != expected_sha256
            or projection.index_integrity != index.integrity_sha256
            or projection.renderer_version != version
            or projection.integrity_sha256 != _digest(projection)):
        raise RendererError("projection binding or integrity mismatch; rebuild required")
    if type(segment) is not int or not 0 <= segment < len(projection.pages):
        raise RendererError("unknown global segment")
    contexts = dict(projection.contexts)
    if location not in contexts:
        raise RendererError("unknown global location; no replacement inferred")
    # Select the smallest source element solely to validate index + complete hash
    # without retaining the full master. This does not assert a unit mapping.
    smallest = min(index.elements, key=lambda entry: entry.end - entry.start)
    read_fragment(master, index, smallest.ordinal, expected_sha256=expected_sha256,
                  renderer_version=version, max_fragment_bytes=index.byte_count)
    context = json.loads(contexts[location])
    descriptor = json.loads(projection.segments[segment])
    containing = [i for i, value in enumerate(projection.segments)
                  if location in json.loads(value)["locations"]]
    if location == "start":
        containing = [0]
    result = {
        "selected_context": {"location": location, "label": context["label"],
                             "text": context["text"], "document": {"nodes": context["nodes"]}},
        "document": {"nodes": json.loads(projection.pages[segment])},
        "segment": {key: value for key, value in descriptor.items() if key != "locations"},
        "segment_count": len(projection.segments),
        "location_segment": containing[0] if containing else None,
        "location_state": "in-range" if segment in containing else "location-outside-range",
    }
    if projection.source_bindings is not None:
        result["source_bindings"] = _selected_page_binding(projection, segment)
    return result


def exact_projection(master: Path, projection: Projection, *, expected_sha256: str) -> str:
    """Proof of fail-closed exact bytes; existing /exact route stays unchanged."""
    if (projection.master_sha256 != expected_sha256
            or projection.renderer_version != renderer_version()
            or projection.integrity_sha256 != _digest(projection)):
        raise RendererError("exact projection binding mismatch")
    payload = master.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise RendererError("exact master sha256 mismatch")
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RendererError("exact master is not UTF-8") from error
