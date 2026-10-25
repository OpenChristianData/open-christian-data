"""Chapter and empty verse carriers remain visible without changing source text."""

from cvw_app.review_renderers import DEFAULT_RENDERER_REGISTRY


def render(body):
    result, _ = DEFAULT_RENDERER_REGISTRY.render(
        "tei-reader", "application/tei+xml",
        f'<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>{body}</body></text></TEI>',
    )
    return result["nodes"]


def test_chapter_and_empty_verse_markers_keep_neighbor_order():
    nodes = render(
        '<div type="book"><head>Matthew</head>'
        '<div type="chapter" n="23" xml:id="chapter-23">'
        '<ab type="verse" n="13">Before.</ab>'
        '<ab type="verse" n="14" xml:id="verse-14" xml:space="preserve"/>'
        '<ab type="verse" n="15">After <hi rend="italic">this</hi>.</ab>'
        '</div></div>'
    )
    assert [n["text"] for n in nodes] == [
        "Matthew", "[Chapter: 23]", "Before.", "[Verse 14: empty text]", "After this."
    ]
    assert nodes[-1]["inline"][1] == {"text": "this", "marks": ["italic"]}


def test_existing_chapter_heading_and_other_empty_blocks_are_unchanged():
    nodes = render(
        '<div type="chapter" n="1"><head>Existing chapter title</head>'
        '<p/><ab/><ab type="verse" n="1">Words.</ab></div>'
        '<div type="section" n="2"><p>Section.</p></div>'
    )
    assert [n["text"] for n in nodes] == ["Existing chapter title", "Words.", "Section."]


def test_unnumbered_markers_do_not_invent_numbers_or_erase_whitespace():
    nodes = render('<div type="chapter"><ab type="verse"/>'
                   '<ab type="verse" n="2"> </ab></div>')
    assert [n["text"] for n in nodes] == ["[Chapter]", "[Verse: empty text]"]
