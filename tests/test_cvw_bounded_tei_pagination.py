"""Construction identity and fail-closed served/context contribution tests."""

import hashlib
from dataclasses import FrozenInstanceError

import pytest

from cvw_app.bounded_tei_pagination import render_served_provenance
from cvw_app.renderer_nodes import (
    MAX_PAGE_SCALARS, MAX_STRUCTURE_CONTEXT_SCALARS, RendererError,
)
from cvw_app.review_contract import ReviewApplication
from cvw_app.tei_renderer import render_tei


def render(tmp_path, body, **kwargs):
    master = tmp_path / "master.xml"
    payload = f"<TEI><text><body>{body}</body></text></TEI>".encode()
    master.write_bytes(payload)
    output, proof = render_served_provenance(
        master, expected_sha256=hashlib.sha256(payload).hexdigest(),
        master_member="master.xml", **kwargs)
    assert output == render_tei("application/tei+xml", payload.decode())
    assert [node.document_node() for node in proof.served] == ReviewApplication._served_page_nodes(
        None, output, kwargs.get("start", 0), kwargs.get("limit", 1))
    return output, proof


def test_unchanged_duplicate_text_preserves_distinct_construction(tmp_path):
    _, proof = render(tmp_path, "<p>Same</p><p>Same</p>")
    assert all(a is b for a, b in zip(proof.served, proof.body.pages[0], strict=True))
    assert proof.served[0].provenance.sources != proof.served[1].provenance.sources
    with pytest.raises(FrozenInstanceError):
        proof.served = ()


def test_atomic_truncation_has_explicit_replacement_parents(tmp_path):
    output, proof = render(tmp_path, '<p xml:id="atomic">' + "x" * (MAX_PAGE_SCALARS + 5) + "</p>")
    assert output["segments"][0]["truncated"]
    replacement, = proof.served
    original, = proof.body.pages[0]
    assert replacement is not original
    assert replacement.provenance.derived_from == (original.provenance.occurrence,)
    assert replacement.provenance.sources == original.provenance.sources
    assert replacement.provenance.occurrence == len(proof.body.emissions)
    assert replacement.document_node()["type"] == "preformatted"
    exported = replacement.document_node()
    exported["text"] = "mutated"
    assert replacement.document_node()["text"] != "mutated"


def test_unchanged_context_preserves_actual_identity(tmp_path):
    output, initial = render(tmp_path, '<div xml:id="chapter"><head>Title</head><p>A</p></div>')
    location = output["outline"][0]["location"]
    _, proof = render(tmp_path, '<div xml:id="chapter"><head>Title</head><p>A</p></div>', context_location=location)
    assert proof.context
    assert all(any(node is emitted for emitted in proof.body.emissions) for node in proof.context)
    assert len(initial.served) == len(proof.served)


def test_context_truncation_inherits_selected_construction_nodes(tmp_path):
    body = '<div xml:id="chapter"><head>Title</head><p>' + "x" * (MAX_STRUCTURE_CONTEXT_SCALARS + 5) + "</p></div>"
    output, _ = render(tmp_path, body)
    location = output["outline"][0]["location"]
    _, proof = render(tmp_path, body, context_location=location)
    replacement, = proof.context
    assert replacement.document_node() == output["contexts"][location]["nodes"][0]
    assert replacement.document_node()["type"] == "preformatted"
    assert replacement.provenance.derived_from == tuple(
        node.provenance.occurrence for node in proof.body.nodes
    )
    assert replacement.provenance.sources == tuple(dict.fromkeys(
        source for node in proof.body.nodes for source in node.provenance.sources
    ))


@pytest.mark.parametrize("mutation", [
    "copied-parent", "unbound-parent", "copied-replacement", "reused-replacement",
])
def test_context_replacement_rejects_missing_or_reused_identity(tmp_path, monkeypatch, mutation):
    from cvw_app import tei_renderer

    finalize = tei_renderer._finalize_structure

    def changed(*args, **kwargs):
        callback = kwargs.get("_on_context_replacement")

        def observe(originals, replacement):
            if mutation == "copied-parent":
                originals = [dict(original) for original in originals]
            elif mutation == "unbound-parent":
                originals = [{"type": "paragraph", "text": "foreign"}]
            elif mutation == "copied-replacement":
                replacement = dict(replacement)
            callback(originals, replacement)
            if mutation == "reused-replacement":
                callback(originals, replacement)

        kwargs["_on_context_replacement"] = observe if callback else None
        return finalize(*args, **kwargs)

    monkeypatch.setattr(tei_renderer, "_finalize_structure", changed)
    with pytest.raises(RendererError, match="construction identity"):
        render(tmp_path, "<p>" + "x" * (MAX_STRUCTURE_CONTEXT_SCALARS + 5) + "</p>",
               context_location="start")


def test_split_pages_derive_from_actual_original(tmp_path):
    output, proof = render(tmp_path, "<p>" + "word " * (MAX_PAGE_SCALARS // 4 + 1) + "</p>", limit=2)
    original, = proof.body.nodes
    fragments = [node for page in proof.body.pages for node in page]
    assert len(fragments) == len(output["segments"]) == 2
    assert " ".join(node.document_node()["text"] for node in fragments) == original.document_node()["text"]
    assert all(node.provenance.derived_from == (original.provenance.occurrence,) for node in fragments)
    assert all(node.provenance.sources == original.provenance.sources for node in fragments)
    assert all(a is b for a, b in zip(proof.served, fragments, strict=True))


@pytest.mark.parametrize("attributes,ordered", [("", False), (' type="ordered"', True)])
def test_list_pages_retain_original_and_item_construction(tmp_path, attributes, ordered):
    body = f"<list{attributes}>" + ("<item>" + "x" * (MAX_PAGE_SCALARS // 2) + "</item>") * 3 + "</list>"
    output, proof = render(tmp_path, body, limit=3)
    original, = proof.body.nodes
    wrappers = [node for page in proof.body.pages for node in page]
    assert len(wrappers) == 3
    items = [node for node in proof.body.emissions
             if node.provenance.occurrence in original.provenance.derived_from]
    assert len(items) == 3
    for index, wrapper in enumerate(wrappers):
        assert wrapper.provenance.derived_from == (
            original.provenance.occurrence, items[index].provenance.occurrence)
        assert wrapper.provenance.sources == original.provenance.sources
        assert wrapper.document_node()["children"] == [items[index].document_node()]
        assert wrapper is proof.served[index]
        if ordered:
            assert wrapper.document_node()["start"] == index + 1
    assert [node["text"] for page in output["_pages"] for node in page[0]["children"]] == [
        node["text"] for node in output["nodes"][0]["children"]]


def test_selected_multiple_pages_keep_unchanged_and_replacement_lineage(tmp_path):
    output, proof = render(tmp_path, '<p>A</p><p xml:id="atomic">' + "x" * (MAX_PAGE_SCALARS + 5) + "</p><p>B</p>", limit=3)
    assert len(output["segments"]) == 3
    assert proof.served[0] is proof.body.pages[0][0]
    assert proof.served[2] is proof.body.pages[2][0]
    assert proof.served[1].provenance.derived_from == (proof.body.pages[1][0].provenance.occurrence,)


@pytest.mark.parametrize("kwargs", [
    {"start": -1}, {"limit": 0}, {"start": True}, {"limit": 1.5},
    {"start": 100}, {"context_location": "absent"}, {"context_location": []},
])
def test_invalid_selection_fails_closed(tmp_path, kwargs):
    with pytest.raises(RendererError):
        render(tmp_path, "<p>A</p>", **kwargs)


def test_equal_copied_served_node_is_not_an_unchanged_identity(tmp_path, monkeypatch):
    def copied(self, rendered, start, limit, *, _on_served_node=None):
        original = rendered["_pages"][0][0]
        _on_served_node(dict(original), (original,), replacement=False)

    monkeypatch.setattr(ReviewApplication, "_served_page_nodes", copied)
    with pytest.raises(RendererError, match="unchanged served node"):
        render(tmp_path, "<p>A</p>")


def test_equal_copied_replacement_parent_is_rejected(tmp_path, monkeypatch):
    def copied(self, rendered, start, limit, *, _on_served_node=None):
        original = rendered["_pages"][0][0]
        _on_served_node({"type": "preformatted", "text": "A"}, (dict(original),), replacement=True)

    monkeypatch.setattr(ReviewApplication, "_served_page_nodes", copied)
    with pytest.raises(RendererError, match="construction identity"):
        render(tmp_path, "<p>A</p>")


def test_equal_long_leaves_keep_distinct_split_parents(tmp_path):
    leaf = "<p>" + "word " * (MAX_PAGE_SCALARS // 4 + 1) + "</p>"
    _, proof = render(tmp_path, leaf * 2, limit=4)
    first, second = proof.body.nodes
    fragments = [node for page in proof.body.pages for node in page]
    assert len(fragments) == 4
    assert [node.provenance.derived_from for node in fragments] == [
        (first.provenance.occurrence,), (first.provenance.occurrence,),
        (second.provenance.occurrence,), (second.provenance.occurrence,),
    ]
    assert first.provenance.sources != second.provenance.sources


def test_equal_copied_split_parent_is_rejected(tmp_path, monkeypatch):
    from cvw_app import renderer_nodes

    validate = renderer_nodes._validate_renderer_output

    def copied_parent(value, *, _on_page_split=None, _on_list_page=None,
                      _on_json_page=None, _on_context_replacement=None):
        def copied(original, fragment):
            _on_page_split(dict(original), fragment)
        return validate(value, _on_page_split=copied if _on_page_split else None,
                        _on_list_page=_on_list_page, _on_json_page=_on_json_page,
                        _on_context_replacement=_on_context_replacement)

    monkeypatch.setattr(renderer_nodes, "_validate_renderer_output", copied_parent)
    with pytest.raises(RendererError, match="construction identity"):
        render(tmp_path, "<p>" + "word " * (MAX_PAGE_SCALARS // 4 + 1) + "</p>")


@pytest.mark.parametrize("mutation", ["parent", "child", "reused"])
def test_list_page_requires_actual_parent_and_child_identities(tmp_path, monkeypatch, mutation):
    from cvw_app import renderer_nodes
    validate = renderer_nodes._validate_renderer_output

    def changed(value, *, _on_page_split=None, _on_list_page=None,
                _on_json_page=None, _on_context_replacement=None):
        def observe(original, wrapper):
            if mutation == "parent":
                original = dict(original)
            elif mutation == "child":
                wrapper["children"] = [dict(child) for child in wrapper["children"]]
            _on_list_page(original, wrapper)
            if mutation == "reused":
                _on_list_page(original, wrapper)
        return validate(value, _on_page_split=_on_page_split,
                        _on_list_page=observe if _on_list_page else None,
                        _on_json_page=_on_json_page,
                        _on_context_replacement=_on_context_replacement)

    monkeypatch.setattr(renderer_nodes, "_validate_renderer_output", changed)
    with pytest.raises(RendererError, match="construction identity"):
        render(tmp_path, "<list>" + ("<item>" + "x" * (MAX_PAGE_SCALARS // 2) + "</item>") * 3 + "</list>")


def test_ordered_list_page_observer_sees_complete_groups_and_start_offsets(tmp_path):
    body = '<list type="ordered">' + ('<item>' + 'x' * (MAX_PAGE_SCALARS // 3) + '</item>') * 4 + '</list>'
    _, proof = render(tmp_path, body, limit=2)
    original, = proof.body.nodes
    first, second = [node for page in proof.body.pages for node in page]
    assert [len(node.document_node()["children"]) for node in (first, second)] == [3, 1]
    assert [node.document_node()["start"] for node in (first, second)] == [1, 4]
    item_occurrences = original.provenance.derived_from
    assert first.provenance.derived_from == (original.provenance.occurrence, *item_occurrences[:3])
    assert second.provenance.derived_from == (original.provenance.occurrence, item_occurrences[3])
