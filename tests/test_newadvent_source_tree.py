"""HTML source-name conservation across independent tree builder routes."""
import pytest

from build.tei.newadvent_source_tree import parse_source, interpreted_tree_bytes, interpreted_tree_sha256


@pytest.mark.parametrize("builder", ["dom", "etree"])
def test_malformed_names_and_browser_topology(builder):
    source = '<!DOCTYPE html><html><head><title>Dives</title><description="Latin for rich."><meta charset="utf-8"></head><body><div id="springfield2"><h1>Dives</h1><p>before <a href<="wrong">visible</a> after</p></div><div id="ogdenville">footer</div></body></html>'
    root = parse_source(source, treebuilder=builder)
    main = root.xpath("//*[@id='springfield2']")[0]
    wrapper = main.getparent()
    assert wrapper.tag == 'description="latin'
    assert wrapper.getparent().tag == "body"
    link = next(main.iter("a"))
    assert link.attrib == {"href<": "wrong"}
    assert link.get("href") is None
    assert root.xpath("//*[@id='springfield2']/h1")[0].text == "Dives"
    assert "%3D%22" in root.getroottree().getpath(wrapper)
    assert root.getroottree().docinfo.doctype == "<!DOCTYPE html>"


@pytest.mark.parametrize("source", [
    '<title>T</title><description="Latin for rich."><div id="springfield2">a<!--x-->b<i>c</i>d</div>',
    '<table>outside<tr><td>A<b>B</table>after',
    '<p><b>one<i>two</b>three</i>four<a href<="bad">five</a>',
    '<svg viewBox="0 0 1 1"><a xlink:href="x">z</a></svg>',
])
def test_builders_have_identical_names_attributes_text_and_topology(source):
    dom = parse_source(source, treebuilder="dom")
    etree = parse_source(source, treebuilder="etree")
    assert interpreted_tree_bytes(dom) == interpreted_tree_bytes(etree)
    assert list(dom.itertext()) == list(etree.itertext())
    assert interpreted_tree_sha256(dom) == interpreted_tree_sha256(etree)


def test_source_paths_distinguish_literal_encoding_and_duplicate_names():
    root = parse_source('<x%22></x%22><x%22></x%22><x"></x">', treebuilder="etree")
    paths = [root.getroottree().getpath(node) for node in root.iter()]
    assert len(paths) == len(set(paths))
    assert any("x%2522[2]" in path for path in paths)
    assert any("x%22[1]" in path for path in paths)


def test_hash_accounts_for_names_attributes_comments_and_tail_policy():
    root = parse_source('<p>A<!--comment-->B<a href<="x">C</a>D</p>', treebuilder="dom")
    assert "".join(root.itertext()) == "ABCD"
    assert b"comment" in interpreted_tree_bytes(root)
    link = next(root.iter("a"))
    old = interpreted_tree_sha256(root)
    before = interpreted_tree_sha256(link)
    link.tail = "changed"
    assert interpreted_tree_sha256(link) == before
    assert interpreted_tree_sha256(link, with_tail=True) != before
    assert interpreted_tree_sha256(root) != old
    link.attrib = {"href": "x"}
    assert interpreted_tree_sha256(link) != before


def test_moving_implied_table_children_preserves_parent_links():
    root = parse_source('<table><tr><td>A</td></tr></table>', treebuilder="dom")
    group = next(root.iter("tbody"))
    table = group.getparent()
    row = group[0]
    group.addprevious(row)
    table.remove(group)
    assert row.getparent() is table
    assert list(table) == [row]
    assert row.getprevious() is None
    assert group.getparent() is None


def test_unsupported_queries_fail_closed():
    root = parse_source('<p>A</p>', treebuilder="etree")
    with pytest.raises(ValueError, match="Unsupported"):
        root.xpath("//a")


@pytest.mark.parametrize("builder", ["dom", "etree"])
def test_document_shell_accounts_for_comments_and_nonleading_doctype(builder):
    root = parse_source('<!--before--><!doctype html><p>body</p></html><!--after-->', treebuilder=builder)
    info = root.getroottree().docinfo
    assert info.doctype == "<!DOCTYPE html>"
    assert info.declarations == [{"document_child_position": 2, "name": "html", "public_id": None, "system_id": None}]
    assert info.document_comments == [
        {"document_child_position": 1, "text": "before"},
        {"document_child_position": 4, "text": "after"},
    ]
    assert "not literal source bytes" in info.doctype_semantics
    assert "bind these fields separately" in info.metadata_scope
    assert "".join(root.itertext()) == "body"
    assert b"after" not in interpreted_tree_bytes(root)
