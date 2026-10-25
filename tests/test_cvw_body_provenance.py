"""Actual renderer ownership proof, separate from route activation."""
import hashlib
from dataclasses import FrozenInstanceError

import pytest

from cvw_app.bounded_tei_provenance import render_body_provenance
from cvw_app.renderer_nodes import RendererError, MAX_PAGE_SCALARS
from cvw_app.tei_renderer import render_tei


def render(tmp_path, body):
    master = tmp_path / "master.xml"
    payload = f"<TEI><text><body>{body}</body></text></TEI>".encode()
    master.write_bytes(payload)
    output, proof = render_body_provenance(
        master, expected_sha256=hashlib.sha256(payload).hexdigest(),
        master_member="master.xml")
    assert output == render_tei("application/tei+xml", payload.decode())
    return output, proof


def test_inline_paragraph_and_page_own_normalized_contributions(tmp_path):
    output, proof = render(tmp_path, '<p xml:id="x" rend="align-center">A<hi rend="italic"> B</hi><pb n="2"/> C</p>')
    node = proof.nodes[0]
    assert node.document_node() == output["nodes"][0]
    assert len(node.provenance.sources) == 3
    assert proof.pages == ((node,),)
    with pytest.raises(FrozenInstanceError):
        proof.nodes = ()


def test_list_replacement_retains_original_and_label_lineage(tmp_path):
    output, proof = render(tmp_path, '<list><label>Key</label><item>A<hi>B</hi></item><item>A</item></list>')
    wrapper = proof.nodes[0]
    first_item, second_item = output["nodes"][0]["children"]
    traced_item = next(item for item in proof.emissions if item.document_node() == first_item)
    parents = [proof.emissions[index] for index in traced_item.provenance.derived_from]
    assert [parent.document_node()["type"] for parent in parents] == ["paragraph", "paragraph"]
    replacement = parents[1]
    original = proof.emissions[replacement.provenance.derived_from[0]]
    assert original.document_node()["type"] == "list-item"
    assert replacement.document_node()["type"] == "paragraph"
    assert original.provenance.sources == replacement.provenance.sources
    assert len(wrapper.provenance.sources) == 5
    assert second_item["children"][0]["text"] == "A"


def test_duplicate_text_keeps_distinct_body_and_page_owners(tmp_path):
    _, proof = render(tmp_path, '<p>Same</p><p>Same</p>')
    assert proof.nodes[0].document_node() == proof.nodes[1].document_node()
    assert proof.nodes[0].provenance.sources != proof.nodes[1].provenance.sources
    assert proof.pages[0] == proof.nodes


def test_fragment_blockquote_and_nested_list_derive_children(tmp_path):
    _, proof = render(tmp_path, '<quote type="block"><p>A<hi>B</hi></p><list><item>C</item></list></quote>')
    assert proof.nodes[0].document_node()["type"] == "blockquote"
    assert len(proof.nodes[0].provenance.derived_from) == 2


def test_table_cells_rows_and_wrapper_join_body_provenance(tmp_path):
    output, proof = render(
        tmp_path,
        '<table><row><cell>A<hi rend="italic">B</hi></cell></row><row/></table>',
    )
    table = proof.nodes[0]
    assert table.document_node() == output["nodes"][0]
    assert table.document_node()["type"] == "table"
    assert [child.document_node()["type"] for child in proof.emissions
            if child.document_node()["type"] == "table-row"] == [
        "table-row", "table-row",
    ]
    assert len(table.provenance.derived_from) == 2
    assert {
        source.locator.expanded_name for source in table.provenance.sources
    } >= {"table", "row", "cell", "hi"}


def test_generic_pending_text_and_tail_keep_source_owners(tmp_path):
    output, proof = render(
        tmp_path,
        '<div>before<anchor xml:id="a"/>tail<gap reason="lost"/></div>',
    )
    assert [node["type"] for node in output["nodes"]] == ["paragraph"]
    assert output["nodes"][0]["text"].startswith("before")
    assert output["nodes"][0]["text"].endswith("[lost gap]")
    assert {source.locator.expanded_name for source in proof.nodes[0].provenance.sources} >= {
        "TEI", "text", "body", "div", "anchor", "gap",
    }


@pytest.mark.parametrize("body", [
    '<p>A<l>line</l>B</p>',
])
def test_unbound_body_branch_fails_closed(tmp_path, body):
    with pytest.raises(RendererError, match="construction identity"):
        render(tmp_path, body)


def test_split_page_retains_explicit_page_lineage(tmp_path):
    _, proof = render(tmp_path, '<p>' + 'word ' * (MAX_PAGE_SCALARS // 4 + 1) + '</p>')
    original, = proof.nodes
    fragments = [node for page in proof.pages for node in page]
    assert len(fragments) > 1
    assert " ".join(node.document_node()["text"] for node in fragments) == original.document_node()["text"]
    assert all(node.provenance.derived_from == (original.provenance.occurrence,) for node in fragments)
    assert all(node.provenance.sources == original.provenance.sources for node in fragments)


def test_actual_callback_rejects_foreign_inline_owner(tmp_path, monkeypatch):
    from xml.etree import ElementTree
    import cvw_app.tei_renderer as renderer
    original = renderer.inline_node

    def foreign(node_type, element, *, _on_contributions=None, **extra):
        node = original(node_type, element, **extra)
        if _on_contributions:
            _on_contributions(node, (ElementTree.Element("hi"),))
        return node

    monkeypatch.setattr(renderer, "inline_node", foreign)
    with pytest.raises(RendererError, match="parser or fragment identity"):
        render(tmp_path, '<p>A</p>')
