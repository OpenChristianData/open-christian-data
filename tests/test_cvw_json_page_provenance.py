"""Generic JSON projection wrappers; no native JSON-to-TEI route is implied."""
import hashlib

import pytest

from cvw_app import renderer_nodes, tei_renderer
from cvw_app.bounded_tei_provenance import render_body_provenance
from cvw_app.renderer_nodes import MAX_PAGE_SCALARS, RendererError


def synthetic_projection(tmp_path, monkeypatch, kind, mutation=None):
    master = tmp_path / "master.xml"
    payload = b"<TEI><text><body><p>A</p><p>A</p><p>A</p></body></text></TEI>"
    master.write_bytes(payload)

    def project(root, *, _on_body_node, **kwargs):
        body = root.find("./text/body")
        properties = []
        for index, source in enumerate(body):
            value = {"type": "json-value", "text": "x" * (MAX_PAGE_SCALARS // 2),
                     "value_kind": "string"}
            prop = {"type": "json-property", "text": "same", "key": "same",
                    "location": f"property-{index}", "children": [value]}
            _on_body_node(source, value, ())
            _on_body_node(source, prop, ())
            properties.append(prop)
        parent = {"type": kind, "text": "container", "children": properties}
        _on_body_node(body, parent, ())
        outline = [{"location": prop["location"], "label": "same", "level": 1}
                   for prop in properties]
        contexts = {"start": {"location": "start", "label": "Start",
                              "text": renderer_nodes._nodes_text([parent]), "nodes": [parent]}}
        for prop in properties:
            contexts[prop["location"]] = {"location": prop["location"], "label": "same",
                                           "text": renderer_nodes._nodes_text([parent]), "nodes": [parent]}
        return {"kind": "json-tree", "nodes": [parent], "outline": outline, "contexts": contexts}

    monkeypatch.setattr(tei_renderer, "_render_tei_root", project)
    validate = renderer_nodes._validate_renderer_output

    def altered(value, *, _on_json_page=None, **kwargs):
        def observe(parent, wrapper):
            if mutation == "parent":
                parent = dict(parent)
            elif mutation == "child":
                wrapper["children"] = [dict(child) for child in wrapper["children"]]
            elif mutation == "unbound":
                wrapper["children"] = [{"type": "json-property", "text": "foreign"}]
            _on_json_page(parent, wrapper)
            if mutation == "reused":
                _on_json_page(parent, wrapper)
        return validate(value, _on_json_page=observe, **kwargs)

    if mutation:
        monkeypatch.setattr(renderer_nodes, "_validate_renderer_output", altered)
    return render_body_provenance(master, expected_sha256=hashlib.sha256(payload).hexdigest(),
                                  master_member="master.xml")


@pytest.mark.parametrize("kind", ["json-object", "json-array"])
def test_json_wrappers_bind_actual_parent_and_included_properties(tmp_path, monkeypatch, kind):
    output, proof = synthetic_projection(tmp_path, monkeypatch, kind)
    original, = proof.nodes
    pages = [node for page in proof.pages for node in page]
    assert len(pages) == 3
    properties = original.provenance.derived_from
    assert len(set(properties)) == 3
    for index, wrapper in enumerate(pages):
        assert wrapper.document_node() == output["_pages"][index][0]
        assert wrapper.document_node()["type"] == kind
        assert wrapper.provenance.derived_from == (original.provenance.occurrence, properties[index])
        assert wrapper.provenance.sources == original.provenance.sources
        assert output["_pages"][index][0]["children"][0] is output["nodes"][0]["children"][index]
    plain = renderer_nodes._validate_renderer_output(output)
    assert plain == output


@pytest.mark.parametrize("kind", ["json-object", "json-array"])
@pytest.mark.parametrize("mutation", ["parent", "child", "unbound", "reused"])
def test_json_wrapper_proof_rejects_missing_or_reused_identity(tmp_path, monkeypatch, kind, mutation):
    with pytest.raises(RendererError, match="construction identity"):
        synthetic_projection(tmp_path, monkeypatch, kind, mutation)


@pytest.mark.parametrize("mutation", ["unbound", "copied", "ambiguous", "mixed", "wrong-kind"])
def test_json_page_observer_requires_one_actual_construction_parent(mutation):
    child = {"type": "json-property", "text": "same"}
    other = dict(child)
    parent = {"type": "json-object", "children": [child]}
    nodes = [parent]
    page = [child]
    if mutation == "unbound":
        nodes = []
    elif mutation == "copied":
        page = [dict(child)]
    elif mutation == "ambiguous":
        nodes.append({"type": "json-array", "children": [child]})
    elif mutation == "mixed":
        nodes.append({"type": "json-object", "children": [other]})
        page.append(other)
    else:
        parent["type"] = "blockquote"
    observed = []
    with pytest.raises(RendererError, match="unique construction parent"):
        renderer_nodes._wrapped_pages([page], nodes,
                                      _on_json_page=lambda *args: observed.append(args))
    assert not observed

