"""Hymnary's explicit source line breaks remain visible in native review."""
from cvw_app.review_renderers import render_tei


def test_hymn_field_keeps_stanzas_controls_and_literal_backslash():
    rendered = render_tei("application/tei+xml", '''<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>
      <div xml:id="hymnary-row-00001"><head>Hymn</head>
      <ab type="hymn-text">1 First line<lb n="CRLF"/>Second line<lb n="CRLF"/><lb n="LF"/>Refrain:<lb n="LF"/>Verf\\söhner <g ref="#control">[source control U+0008]</g>end</ab>
      <list><item>Author name: Example</item></list></div>
      </body></text></TEI>''')
    nodes = rendered["nodes"]
    assert nodes[0]["text"] == "Hymn"
    assert nodes[1]["type"] == "preformatted"
    assert nodes[1]["text"] == "1 First line\nSecond line\n\nRefrain:\nVerf\\söhner [source control U+0008]end"
    assert nodes[2]["type"] == "list"
    assert nodes[2]["children"][0]["children"][0]["text"] == "Author name: Example"
    assert rendered["outline"][0]["location"] == "hymnary-row-00001"


def test_ordinary_ab_keeps_existing_prose_projection():
    rendered = render_tei("application/tei+xml", '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><ab>United States and<lb/>most other parts</ab></body></text></TEI>')
    assert rendered["nodes"] == [{"type": "paragraph", "text": "United States and most other parts"}]
