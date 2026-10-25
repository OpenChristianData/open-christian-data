"""Native division navigation must open the visible index, not an empty anchor."""

import pytest

from cvw_app.renderer_nodes import _nodes_text, _validate_renderer_output
from cvw_app.review_renderers import render_xml_reader


@pytest.mark.parametrize("previous", ["<p>Prior scripture text</p>", "<ul><li>Prior scripture text</li></ul>"])
@pytest.mark.parametrize("nested", [False, True])
def test_native_index_anchor_stays_with_heading_and_list(previous, nested):
    index = ('<div2 id="iv.ii" title="Index of Citations">'
             '<h2>Index of Citations</h2><ul><li>Anon: A Letter</li></ul></div2>')
    if nested:
        index = '<div1 id="iv" title="Indexes">' + index + '</div1>'
    rendered = _validate_renderer_output(render_xml_reader(
        "application/xml", '<ThML><ThML.body>' + previous + index + '</ThML.body></ThML>'
    ))
    segment = next(item for item in rendered["segments"] if "iv.ii" in item["locations"])
    page = rendered["_pages"][segment["index"]]
    assert _nodes_text(page) == "Index of Citations Anon: A Letter"
    assert _nodes_text(rendered["nodes"]) == _nodes_text([
        node for page in rendered["_pages"] for node in page
    ])
    if nested:
        assert "iv" in segment["locations"]


def test_consecutive_native_indexes_open_their_own_entries():
    rendered = _validate_renderer_output(render_xml_reader("application/xml", '''
        <ThML><ThML.body>
        <p>Prior scripture text</p>
        <div2 id="iv.ii" title="Index of Citations">
          <h2>Index of Citations</h2><ul><li>Anon: A Letter</li></ul>
        </div2>
        <div2 id="iv.iii" title="Index of Names">
          <h2>Index of Names</h2><ul><li>Baxter: 1 2 3 4</li></ul>
        </div2>
        </ThML.body></ThML>'''))
    for location, expected in [("iv.ii", "Index of Citations Anon: A Letter"),
                               ("iv.iii", "Index of Names Baxter: 1 2 3 4")]:
        segment = next(item for item in rendered["segments"] if location in item["locations"])
        assert _nodes_text(rendered["_pages"][segment["index"]]) == expected
