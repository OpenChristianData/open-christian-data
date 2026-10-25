"""Field labels inside TEI list items must not run into their values."""

from cvw_app.tei_renderer import render_tei


def test_toml_field_labels_have_separate_rendered_blocks():
    rendered = render_tei("application/tei+xml", '''
    <TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><list>
      <item n="quote"><label>quote</label><seg>Assist, therefore, one another.</seg></item>
      <item n="source_url"><label>source_url</label><seg/></item>
      <item n="source_title"><label>source_title</label><seg>EPISTLES 2:1</seg></item>
      <item n="number"><label>number</label><num>2</num></item>
    </list></body></text></TEI>''')
    items = rendered["nodes"][0]["children"]
    assert [[block["text"] for block in item["children"]] for item in items] == [
        ["quote", "Assist, therefore, one another."],
        ["source_url"],
        ["source_title", "EPISTLES 2:1"],
        ["number", "2"],
    ]


def test_unlabeled_inline_item_keeps_word_continuity_and_marks():
    rendered = render_tei("application/tei+xml", '''
    <TEI><text><body><list><item>un<hi rend="italic">broken</hi></item></list></body></text></TEI>''')
    paragraph = rendered["nodes"][0]["children"][0]["children"][0]
    assert paragraph["text"] == "unbroken"
    assert paragraph["inline"] == [
        {"text": "un", "marks": []}, {"text": "broken", "marks": ["italic"]},
    ]


def test_labeled_value_keeps_inline_marks_and_tail_text():
    rendered = render_tei("application/tei+xml", '''
    <TEI><text><body><list><item><label>quote</label>Before <seg><hi rend="italic">value</hi></seg> after</item></list></body></text></TEI>''')
    blocks = rendered["nodes"][0]["children"][0]["children"]
    assert [block["text"] for block in blocks] == ["quote", "Before value after"]
    assert blocks[1]["inline"] == [
        {"text": "Before ", "marks": []},
        {"text": "value", "marks": ["italic"]},
        {"text": " after", "marks": []},
    ]
