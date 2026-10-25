"""Safe TEI verse projection keeps the source's line and stanza boundaries."""

import pytest
from cvw_app import review_renderers


def _render(body):
    exact = f'<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>{body}</body></text></TEI>'
    rendered, _ = review_renderers.DEFAULT_RENDERER_REGISTRY.render(
        "tei-reader", "application/tei+xml", exact
    )
    return rendered


def test_exact_centered_paragraph_rendition_preserves_default_paragraphs():
    nodes = _render('<p>Amen.</p><p rend="align-center">GRATIAS TIBI DOMINE</p>'
                    '<p rend="center">Unsupported</p>')["nodes"]
    assert nodes == [
        {"type": "paragraph", "text": "Amen."},
        {"type": "paragraph", "text": "GRATIAS TIBI DOMINE", "align": "center"},
        {"type": "paragraph", "text": "Unsupported"},
    ]


def test_explicit_paragraph_ids_route_to_their_own_context_and_segment():
    rendered = _render(
        '<p xml:id="question-one">Question 1</p>'
        f'<p>{"context " * 9000}</p>'
        '<p xml:id="question-two">Question 2</p>'
    )

    assert rendered["outline"] == [
        {"location": "question-one", "label": "Question 1", "level": 6},
        {"location": "question-two", "label": "Question 2", "level": 6},
    ]
    assert "Question 1" in rendered["contexts"]["question-one"]["text"]
    assert "Question 2" not in rendered["contexts"]["question-one"]["text"]
    assert rendered["segments"][0]["locations"] == ["question-one"]
    assert rendered["segments"][-1]["locations"] == ["question-two"]


def test_corresp_alone_does_not_make_paragraph_location_ambiguous():
    rendered = _render(
        '<p corresp="#one #two">Ambiguous mapping.</p>'
        '<p xml:id="question-one">Question 1</p>'
    )

    assert [item["location"] for item in rendered["outline"]] == ["question-one"]
    assert "location" not in rendered["nodes"][0]


@pytest.mark.parametrize("node_type,alignment", [("paragraph", "left"), ("heading", "center")])
def test_paragraph_alignment_rejects_unsupported_projection(node_type, alignment):
    from cvw_app.renderer_nodes import _validate_document_nodes, RendererError

    with pytest.raises(RendererError, match="paragraph alignment"):
        _validate_document_nodes([{"type": node_type, "text": "Text", "align": alignment}], "document")


@pytest.mark.parametrize("wrapped", [False, True])
def test_explicit_block_quote_keeps_boundary_and_inline_emphasis(wrapped):
    quote = '<quote type="block">1st, <hi rend="italic">Joshua</hi>;<lb/>2nd, Judges;</quote>'
    body = f'<p>Before {quote} After</p>' if wrapped else quote
    nodes = _render(body)["nodes"]
    if wrapped:
        assert nodes[0] == {"type": "paragraph", "text": "Before"}
        assert nodes[-1] == {"type": "paragraph", "text": "After"}
        nodes = nodes[1:-1]
    assert len(nodes) == 1
    assert nodes == [{
        "type": "blockquote", "text": "", "children": [{
            "type": "paragraph", "text": "1st, Joshua; 2nd, Judges;",
            "inline": [
                {"text": "1st, ", "marks": []},
                {"text": "Joshua", "marks": ["italic"]},
                {"text": "; 2nd, Judges;", "marks": []},
            ],
        }],
    }]


def test_explicit_block_quote_keeps_multiple_paragraphs():
    nodes = _render('<quote type="block"><p>First</p><p>Second</p></quote>')["nodes"]
    assert nodes == [{
        "type": "blockquote", "text": "", "children": [
            {"type": "paragraph", "text": "First"},
            {"type": "paragraph", "text": "Second"},
        ],
    }]


def test_explicit_block_quote_with_nested_quote_keeps_paragraph_order_and_marks():
    nodes = _render(
        '<quote type="block"><p>Before</p>'
        '<quote type="block"><p><hi rend="italic">Nested</hi></p></quote>'
        '<p>After</p></quote>'
    )["nodes"]
    assert nodes == [{
        "type": "blockquote", "text": "", "children": [
            {"type": "paragraph", "text": "Before"},
            {"type": "blockquote", "text": "", "children": [{
                "type": "paragraph", "text": "Nested",
                "inline": [{"text": "Nested", "marks": ["italic"]}],
            }]},
            {"type": "paragraph", "text": "After"},
        ],
    }]


@pytest.mark.parametrize("wrapped", [False, True])
def test_verse_lines_and_indentation_survive_projection(wrapped):
    verse = '<lg><l>  First line</l><l>    Second line</l></lg>'
    rendered = _render(f'<quote>{verse}</quote>' if wrapped else verse)
    assert rendered["nodes"] == [{"type": "preformatted", "text": "  First line\n    Second line"}]


def test_nested_stanzas_and_empty_lines_remain_distinct():
    rendered = _render('<quote><lg><lg><l>First</l><l/><l>Third</l></lg><lg><l>Next stanza</l></lg></lg></quote>')
    assert rendered["nodes"] == [
        {"type": "preformatted", "text": "First\n\nThird"},
        {"type": "preformatted", "text": "Next stanza"},
    ]


def test_verse_inside_prose_keeps_surrounding_text_order():
    rendered = _render('<p>Before<quote><lg><l>One</l><l>Two</l></lg></quote>After</p>')
    assert rendered["nodes"] == [
        {"type": "paragraph", "text": "Before"},
        {"type": "preformatted", "text": "One\nTwo"},
        {"type": "paragraph", "text": "After"},
    ]


def test_inline_verse_note_stays_between_its_source_text_pieces():
    rendered = _render('<quote><lg><l>  Before<note>Note text</note> after</l><l>Next line</l></lg></quote>')
    assert rendered["nodes"] == [
        {"type": "preformatted", "text": "  Before"},
        {"type": "blockquote", "text": "Note text"},
        {"type": "preformatted", "text": " after"},
        {"type": "preformatted", "text": "Next line"},
    ]


def test_standalone_stanza_heading_remains_in_outline():
    rendered = _render('<div xml:id="poem"><lg><head>Poem title</head><l>First</l><l>Second</l></lg></div>')
    assert rendered["outline"][0]["label"] == "Poem title"
    assert [node["text"] for node in rendered["nodes"]] == ["Poem title", "First", "Second"]


def test_source_heading_in_anonymous_block_remains_a_heading_and_outline_anchor():
    rendered = _render(
        '<div xml:id="chapter"><p>Introductory text</p>'
        '<ab xml:id="chapter-heading" type="source-heading" subtype="h3">CHAPTER I</ab>'
        '<p>Chapter text</p></div>'
    )
    heading = next(node for node in rendered["nodes"] if node["type"] == "heading")
    outline_entry = rendered["outline"][0]
    assert heading == {
        "type": "heading",
        "text": "CHAPTER I",
        "level": 3,
        "location": outline_entry["location"],
    }
    assert outline_entry["label"] == "CHAPTER I"
    assert outline_entry["level"] == 3


def test_explicit_line_break_contract_still_applies_inside_verse():
    rendered = _render('<quote><lg><l>con<lb break="no"/>tinue<lb/>next</l></lg></quote>')
    assert rendered["nodes"] == [{"type": "preformatted", "text": "continue\nnext"}]


def test_ordinary_prose_and_inline_notes_keep_existing_projection():
    rendered = _render('<p> One   <hi>two</hi><note> note  text </note> three </p>')
    assert rendered["nodes"] == [
        {"type": "paragraph", "text": "One two"},
        {"type": "blockquote", "text": "note text"},
        {"type": "paragraph", "text": "three"},
    ]


def test_quoted_paragraphs_do_not_join_their_boundary_words():
    rendered = _render('<quote><p>First paragraph</p><p>Second paragraph</p></quote>')
    assert rendered["nodes"] == [
        {"type": "paragraph", "text": "First paragraph"},
        {"type": "paragraph", "text": "Second paragraph"},
    ]


def test_simple_list_items_keep_list_semantics_and_order():
    rendered = _render(
        '<list><item><ref target="#one">First entry</ref></item>'
        '<item>Second entry</item></list>'
    )
    group = rendered["nodes"][0]
    assert group["type"] == "list" and group["ordered"] is False
    assert [item["children"][0]["text"] for item in group["children"]] == ["First entry", "Second entry"]


def test_nested_quote_index_lists_render_each_item_as_a_list_item():
    rendered = _render(
        '<quote rend="Greek"><quote rend="Index"><list rend="Index1">'
        '<item><seg rend="Greek"><ref target="#one">logos</ref></seg></item>'
        '<item><ref target="#two">theos</ref></item>'
        '</list></quote></quote>'
    )
    assert [item["children"][0]["text"] for item in rendered["nodes"][0]["children"]] == ["logos", "theos"]


def test_quote_index_milestones_do_not_flatten_wrapped_lists():
    rendered = _render(
        '<quote rend="Greek"><milestone unit="index1" n="1"/>'
        '<quote rend="Index"><list rend="Index1">'
        '<item><seg rend="Greek"><ref target="#one">logos</ref></seg></item>'
        '</list></quote></quote>'
    )
    assert rendered["nodes"][0]["children"][0]["children"] == [{"type": "paragraph", "text": "logos"}]


def test_list_item_paragraphs_keep_order_and_boundaries():
    rendered = _render('<list><item><p>First entry</p><p>Its continuation</p></item><item><p>Next entry</p></item></list>')
    items = rendered["nodes"][0]["children"]
    assert len(items) == 2
    assert [[part["text"] for part in item["children"]] for item in items] == [["First entry", "Its continuation"], ["Next entry"]]


@pytest.mark.parametrize("wrapped", [False, True])
def test_xml_formatting_does_not_become_verse_indentation(wrapped):
    verse = '<lg>\n  <l>\n    <seg>  A</seg>\n  </l>\n  <l>\n    <seg>    B</seg>\n  </l>\n</lg>'
    rendered = _render(f'<quote>{verse}</quote>' if wrapped else verse)
    assert rendered["nodes"] == [{"type": "preformatted", "text": "  A\n    B"}]


def test_pretty_printed_inline_words_keep_a_separator():
    rendered = _render('<lg><l>\n <seg>A</seg>\n <hi>B</hi>\n</l><l>\n<seg>con</seg>\n<lb break="no"/>\n<seg>tinue</seg>\n</l></lg>')
    assert rendered["nodes"] == [{"type": "preformatted", "text": "A B\ncontinue"}]


def test_inherited_xml_space_preserve_and_default_reset():
    rendered = _render('<div xml:space="preserve"><quote><lg><l>\n  <seg>A</seg>\n</l><l xml:space="default">\n  <seg>B</seg>\n</l></lg></quote></div>')
    assert rendered["nodes"] == [{"type": "preformatted", "text": "\n  A\n\nB"}]


@pytest.mark.parametrize("wrapped", [False, True])
def test_stanza_gap_and_note_keep_their_existing_meaning(wrapped):
    verse = '<lg><l>One</l><gap reason="illegible" extent="1 line"/><note>Stanza note</note><l>Three</l></lg>'
    rendered = _render(f'<quote>{verse}</quote>' if wrapped else verse)
    assert rendered["nodes"] == [
        {"type": "preformatted", "text": "One"},
        {"type": "paragraph", "text": "[illegible gap; extent 1 line]"},
        {"type": "blockquote", "text": "Stanza note"},
        {"type": "preformatted", "text": "Three"},
    ]


def test_page_boundary_does_not_invent_a_stanza_boundary():
    rendered = _render('<lg><l>A</l><pb n="2"/><l>B</l></lg>')
    assert rendered["nodes"] == [{"type": "preformatted", "text": "A\n[Page break: 2]\nB"}]


@pytest.mark.parametrize("line,expected", [
    ('v<gap reason="illegible">\n   <desc>•</desc>\n </gap>ltus', 'v • ltus'),
    ('\n   Lead, kindly Light,\n ', 'Lead, kindly Light,'),
    ('A<lb/>\n   B', 'A\nB'),
    ('con<lb break="no"/>\ntinue', 'continue'),
    ('<seg>A</seg><hi>\n  <seg>B</seg></hi>', 'A B'),
    ('<hi><seg>A</seg>\n  </hi><seg>B</seg>', 'A B'),
])
def test_formatting_across_inline_boundaries_keeps_readable_words(line, expected):
    rendered = _render(f'<lg><l>{line}</l></lg>')
    assert rendered["nodes"] == [{"type": "preformatted", "text": expected}]
