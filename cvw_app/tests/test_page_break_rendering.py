"""Visible page milestones in retained ThML and TEI, including 37c-204."""

import pytest

from cvw_app.review_renderers import DEFAULT_RENDERER_REGISTRY


def render(body, kind):
    if kind == "tei-reader":
        exact = '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>' + body + '</body></text></TEI>'
    else:
        exact = '<ThML><ThML.body>' + body + '</ThML.body></ThML>'
    return DEFAULT_RENDERER_REGISTRY.render(kind, "application/xml", exact)[0]


@pytest.mark.parametrize("kind", ["tei-reader", "xml-reader"])
def test_hodge_page_two_stays_between_its_neighboring_headings(kind):
    heading = "head" if kind == "tei-reader" else "h2"
    result = render(
        f'<{heading}>ANTHROPOLOGY</{heading}>'
        '<pb n="2"/>'
        f'<{heading}>SYSTEMATIC THEOLOGY</{heading}>', kind
    )
    assert [(node["type"], node["text"]) for node in result["nodes"]] == [
        ("heading", "ANTHROPOLOGY"),
        ("paragraph", "[Page break: 2]"),
        ("heading", "SYSTEMATIC THEOLOGY"),
    ]


@pytest.mark.parametrize("kind", ["tei-reader", "xml-reader"])
@pytest.mark.parametrize("attribute,label", [
    ('n="iv"', "[Page break: iv]"),
    ("", "[Page break]"),
    ('n="&lt;script&gt;"', "[Page break: <script>]"),
])
def test_inline_page_break_keeps_surrounding_text_and_does_not_guess_numbers(kind, attribute, label):
    nodes = render(f'<p>Before<pb {attribute}/>after.</p>', kind)["nodes"]
    assert nodes == [{"type": "paragraph", "text": f"Before {label} after."}]


def test_page_break_survives_note_and_verse_projection():
    nodes = render('<p>Before<pb n="2"/><note>Note</note>after.</p>'
                   '<lg><l>First</l><pb n="3"/><l>Second</l></lg>', "tei-reader")["nodes"]
    assert [node["text"] for node in nodes] == [
        "Before [Page break: 2]", "Note", "after.",
        "First\n[Page break: 3]\nSecond",
    ]
