"""Crosswalk incidence is derived from actual construction identities."""

from dataclasses import FrozenInstanceError, replace
import hashlib

import pytest

from cvw_app.bounded_tei_crosswalk import _crosswalk, render_contribution_crosswalk
from cvw_app.renderer_nodes import MAX_PAGE_SCALARS, RendererError
from cvw_app.tei_renderer import render_tei


def render(tmp_path, body, **kwargs):
    payload = f"<TEI><text><body>{body}</body></text></TEI>".encode()
    master = tmp_path / "crosswalk.xml"
    master.write_bytes(payload)
    rendered, crosswalk = render_contribution_crosswalk(
        master, expected_sha256=hashlib.sha256(payload).hexdigest(),
        master_member="tei/master.xml", **kwargs)
    assert rendered == render_tei("application/tei+xml", payload.decode())
    return rendered, crosswalk


def test_duplicate_text_and_ids_have_separate_source_records(tmp_path):
    _, crosswalk = render(tmp_path, '<p xml:id="same">Equal</p><p xml:id="same">Equal</p>')
    assert len(crosswalk.records) == 2
    a, b = crosswalk.records
    assert a.source.locator != b.source.locator
    assert a.source.master_member == "tei/master.xml"
    assert len(a.outputs) == len(b.outputs) == 3
    assert {output.surface for output in a.outputs} == {"body", "page", "served"}
    assert all(output.node is a.emissions[0] for output in a.outputs)
    assert all(output.node is not a.emissions[0] for output in b.outputs)


def test_output_incidence_is_complete_and_bidirectional(tmp_path):
    _, crosswalk = render(tmp_path, '<p>Text <hi>emphasis</hi> tail</p>')
    assert len(crosswalk.records) >= 2
    for output in crosswalk.outputs:
        actual = tuple(record.source for record in crosswalk.records
                       if any(item is output for item in record.outputs))
        assert set(actual) == set(output.node.provenance.sources)
    assert not crosswalk.source_free_outputs
    assert len(crosswalk.outputs) == (
        len(crosswalk.proof.body.nodes)
        + sum(len(page) for page in crosswalk.proof.body.pages)
        + len(crosswalk.proof.served))


def test_atomic_replacement_retains_source_and_distinct_served_identity(tmp_path):
    _, crosswalk = render(tmp_path, '<p xml:id="atomic">' + "x" * (MAX_PAGE_SCALARS + 5) + '</p>')
    record, = crosswalk.records
    original = crosswalk.proof.body.nodes[0]
    served, = [item for item in record.outputs if item.surface == "served"]
    replacement = served.node
    assert replacement is not original
    assert any(node is replacement for node in record.emissions)
    assert replacement.provenance.derived_from == (original.provenance.occurrence,)
    assert all(item.node is original for item in record.outputs if item.surface != "served")


def test_context_has_explicit_selected_location(tmp_path):
    body = '<div xml:id="chapter"><head>Title</head><p>A</p></div>'
    rendered, _ = render(tmp_path, body)
    location = rendered["outline"][0]["location"]
    _, crosswalk = render(tmp_path, body, context_location=location)
    context = [item for item in crosswalk.outputs if item.surface == "context"]
    assert context
    assert all(item.context_location == location for item in context)
    assert all(any(item.node is emitted for emitted in crosswalk.proof.body.emissions)
               for item in context)


def test_crosswalk_is_immutable_and_export_is_detached(tmp_path):
    _, crosswalk = render(tmp_path, '<p>A</p>')
    with pytest.raises(FrozenInstanceError):
        crosswalk.records = ()
    with pytest.raises(FrozenInstanceError):
        crosswalk.records[0].outputs = ()
    node = crosswalk.outputs[0].node
    exported = node.document_node()
    exported["text"] = "changed"
    assert node.document_node()["text"] == "A"


@pytest.mark.parametrize("mutation", ["copy", "missing", "parent", "duplicate"])
def test_incomplete_or_foreign_construction_fails_closed(tmp_path, mutation):
    _, crosswalk = render(tmp_path, '<p>A</p>')
    proof = crosswalk.proof
    node = proof.body.nodes[0]
    if mutation == "copy":
        proof = replace(proof, body=replace(proof.body, nodes=(replace(node),)))
    elif mutation == "missing":
        proof = replace(proof, body=replace(proof.body, emissions=()), served=())
    elif mutation == "parent":
        forged = replace(node, provenance=replace(node.provenance, derived_from=(999,)))
        proof = replace(proof, body=replace(proof.body, emissions=(forged,)))
    else:
        proof = replace(proof, served=(replace(node),))
    with pytest.raises(RendererError, match="crosswalk"):
        _crosswalk(proof, None)


def test_unselected_split_pages_keep_source_incidence(tmp_path):
    _, crosswalk = render(tmp_path, '<p>Good</p><p>' + 'word ' * (MAX_PAGE_SCALARS // 4 + 1) + '</p>')
    original = crosswalk.proof.body.nodes[1]
    record = next(record for record in crosswalk.records
                  if any(node is original for node in record.emissions))
    fragments = [item.node for item in record.outputs if item.surface == "page"]
    assert len(fragments) == 2
    assert all(any(node is emitted for emitted in record.emissions) for node in fragments)
    assert all(node.provenance.derived_from == (original.provenance.occurrence,) for node in fragments)
    assert " ".join(node.document_node()["text"] for node in fragments) == original.document_node()["text"]
    assert not [item for item in record.outputs if item.surface == "served"]


def test_unselected_list_wrappers_keep_conservative_parent_incidence(tmp_path):
    _, crosswalk = render(tmp_path, '<p>Good</p><list>' + ('<item>' + 'x' * (MAX_PAGE_SCALARS // 2) + '</item>') * 3 + '</list>')
    wrappers = [item for item in crosswalk.outputs
                if item.surface == "page" and item.node.document_node()["type"] == "list"]
    assert len(wrappers) == 3
    assert not [item for item in crosswalk.outputs
                if item.surface == "served" and item.node.document_node()["type"] == "list"]
    original = crosswalk.proof.body.nodes[1]
    for wrapper in wrappers:
        assert wrapper.node.provenance.derived_from[0] == original.provenance.occurrence
        # Original-list contribution is conservative dependency, not a claim
        # that all siblings' text appears on every page.
        assert wrapper.node.provenance.sources == original.provenance.sources
        for source in wrapper.node.provenance.sources:
            record = next(record for record in crosswalk.records if record.source is source)
            assert any(item is wrapper for item in record.outputs)


def test_stale_master_binding_is_rejected(tmp_path):
    master = tmp_path / "stale.xml"
    master.write_text('<TEI><text><body><p>A</p></body></text></TEI>', encoding="utf-8")
    with pytest.raises(RendererError):
        render_contribution_crosswalk(master, expected_sha256="0" * 64, master_member="master.xml")
