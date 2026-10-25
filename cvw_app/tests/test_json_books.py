"""JSON book layouts preserve content and put descriptive fields behind details."""

import json
from xml.etree import ElementTree as ET

from cvw_app.json_books import render_json_book, semantic_json_book
from cvw_app.review_renderers import DEFAULT_RENDERER_REGISTRY, render_json
from cvw_app.tei_renderer import render_tei


def test_articles_read_as_headings_and_paragraphs_with_metadata_in_details():
    record = {"Metadata": {"Title": "A book", "OriginStory": "Source background."},
              "Data": [{"Article": "1", "Title": "I. Scripture", "Content": "First paragraph.\n\nSecond paragraph."}],
              "Unfamiliar": {"Retained": "Extra source value."}}
    exact = json.dumps(record)
    rendered, supported = DEFAULT_RENDERER_REGISTRY.render("json-tree", "application/json", exact)
    assert supported
    details, heading, first, second = rendered["nodes"]
    assert details["type"] == "details" and details["text"] == "About this book"
    assert "Source background." in json.dumps(details)
    assert "Extra source value." in json.dumps(details)
    assert heading == {"type": "heading", "text": "I. Scripture", "level": 2, "location": "/Data/0/Title"}
    assert [first["text"], second["text"]] == ["First paragraph.", "Second paragraph."]
    assert [entry["label"] for entry in rendered["outline"]] == ["I. Scripture"]
    assert json.loads(exact) == record


def test_large_catechism_keeps_questions_searchable_and_annotations_separate():
    record = {"Metadata": {"Title": "Catechism"}, "Data": [
        {"Number": n, "Question": f"Question {n}?", "Answer": "Answer. " * 80,
         "AnswerWithProofs": "Answer with [1].", "Proofs": [{"Id": 1, "References": ["John.1.1"]}]}
        for n in range(1, 197)]}
    rendered, supported = DEFAULT_RENDERER_REGISTRY.render("json-tree", "application/json", json.dumps(record))
    assert supported and rendered["kind"] == "json-tree"
    assert len(rendered["outline"]) == 196
    assert rendered["outline"][-1]["label"] == "196. Question 196?"
    assert len(rendered["_pages"]) > 1
    notes = [node for node in rendered["nodes"] if node["type"] == "details"][1:]
    assert len(notes) == 196 and "John.1.1" in json.dumps(notes[-1])
    assert not any(segment.get("truncated") for segment in rendered["segments"])


def test_nested_chapters_and_subquestions_keep_their_order():
    value = {"Metadata": {}, "Data": [{"Chapter": 1, "Title": "Of God", "Sections": [
        {"Section": 1, "Content": "One."}, {"Section": 2, "Content": "Two."}]}]}
    rendered = render_json_book(value)
    assert [node["text"] for node in rendered["nodes"] if node["type"] != "details"] == ["Of God", "1", "One.", "2", "Two."]
    assert [item["label"] for item in rendered["outline"]] == ["Chapter 1. Of God", "Chapter 1. Of God › 1", "Chapter 1. Of God › 2"]
    value["Data"] = [{"Number": 1, "Question": "Parent?", "Answer": "Yes.",
                      "SubQuestions": [{"Number": 2, "Question": "Child?", "Answer": "Also yes."}]}]
    assert [item["label"] for item in render_json_book(value)["outline"]] == ["1. Parent?", "1. Parent? › 2. Child?"]


def test_repeated_source_chapter_titles_have_distinct_navigation_labels():
    value = {"Metadata": {}, "Data": [
        {"Chapter": n, "Title": "Repeated source title", "Sections": [{"Section": 1, "Content": f"Text {n}."}]}
        for n in [23, 24]]}
    rendered = render_json_book(value)
    assert [item["label"] for item in rendered["outline"] if item["level"] == 3] == [
        "Chapter 23. Repeated source title › 1", "Chapter 24. Repeated source title › 1"]
    assert [node["text"] for node in rendered["nodes"] if node["type"] == "heading" and node["level"] == 2] == [
        "Repeated source title", "Repeated source title"]


def test_unknown_row_schema_keeps_the_existing_complete_data_view():
    record = {"Metadata": {}, "Data": [{"UnknownBody": "Do not hide me."}]}
    assert render_json_book(record) is None
    rendered = render_json("application/json", json.dumps(record))
    assert rendered["nodes"][0]["type"] == "json-object"
    assert "Do not hide me." in json.dumps(rendered)


def test_single_text_creed_keeps_paragraphs_and_reference_material_separate():
    record = {"Metadata": {"Title": "Creed"}, "Data": {
        "Content": "I believe.\n\nAmen.", "ContentWithProofs": "I believe.[1]\n\nAmen.",
        "Proofs": [{"Id": 1, "References": ["John.1.1"]}]}}
    rendered, supported = DEFAULT_RENDERER_REGISTRY.render("json-tree", "application/json", json.dumps(record))
    assert supported
    assert [node["text"] for node in rendered["nodes"] if node["type"] == "paragraph"] == ["I believe.", "Amen."]
    assert rendered["nodes"][0]["text"] == "About this book"
    assert "John.1.1" in json.dumps(rendered["nodes"][-1])


def test_tei_semantic_layout_reads_its_own_values_and_preserves_native_ids():
    def element(value, name="root"):
        if value is None:
            return '<div type="json-null"><ab type="json-scalar"/></div>'
        if isinstance(value, dict):
            return '<div type="json-object">' + ''.join(
                f'<div type="json-member"><head type="json-key">{key}</head>{element(child, key)}</div>'
                for key, child in value.items()) + '</div>'
        if isinstance(value, list):
            return '<div type="json-array">' + ''.join(f'<div type="json-item">{element(child)}</div>' for child in value) + '</div>'
        return f'<div type="json-string" xml:id="native-{name}"><ab type="json-scalar">{value}</ab></div>'
    record = {"Metadata": {"Title": "Book", "Location": None}, "Data": [{"Title": "Original heading", "Content": "TEI text."}]}
    root = ET.fromstring('<TEI><text><body><div type="json-semantic-tree">' + element(record) + '</div></body></text></TEI>')
    rendered = semantic_json_book(root)
    assert rendered["outline"][0]["location"] == "native-Title"
    assert rendered["nodes"][-1]["text"] == "TEI text."
    scalar = next(item for item in root.iter() if item.text == "TEI text.")
    scalar.text = "Changed semantic text."
    assert semantic_json_book(root)["nodes"][-1]["text"] == "Changed semantic text."
    null_scalar = next(item for item in root.iter() if item.get("type") == "json-null")[0]
    null_scalar.text = "not a null"
    assert semantic_json_book(root) is None


def test_explicit_tei_catechism_groups_reference_material_without_losing_it():
    exact = '''<TEI><text><body><div type="catechism"><div type="question-unit" n="1">
      <label type="source-number">1</label><p xml:id="q1" ana="#question">Why?</p>
      <p xml:id="a1" ana="#answer">Because.</p><p xml:id="p1" ana="#answer-with-proofs">Because.[1]</p>
      <list type="proofs"><item>John 1:1</item></list></div></div></body></text></TEI>'''
    rendered, supported = DEFAULT_RENDERER_REGISTRY.render("tei-reader", "application/tei+xml", exact)
    assert supported
    assert [node["type"] for node in rendered["nodes"]] == ["heading", "paragraph", "details"]
    assert rendered["outline"][0] == {"location": "q1", "label": "1. Why?", "level": 2}
    assert [item["location"] for item in rendered["outline"]] == ["q1", "a1", "p1"]
    assert rendered["nodes"][1]["location"] == "a1"
    assert "Because.[1]" in json.dumps(rendered["nodes"][2])
    assert "John 1:1" in json.dumps(rendered["nodes"][2])


def test_tei_subquestions_remain_visible_and_navigable_as_book_content():
    exact = '''<TEI><text><body><div type="catechism"><div type="question-unit" n="1">
      <label type="source-number">1</label><p xml:id="q1" ana="#question">Parent?</p>
      <p xml:id="a1" ana="#answer">Yes.</p><list type="subquestions"><item n="1a">
      <label type="subquestion-number">1a</label><p xml:id="child" ana="#subquestion-question">Child <hi rend="italic">question</hi>?</p>
      <p xml:id="child-answer" ana="#subquestion-answer">Child answer.</p></item></list>
      </div></div></body></text></TEI>'''
    rendered, supported = DEFAULT_RENDERER_REGISTRY.render("tei-reader", "application/tei+xml", exact)
    assert supported
    assert [node["type"] for node in rendered["nodes"]] == ["heading", "paragraph", "heading", "paragraph"]
    child = rendered["nodes"][2]
    assert child["level"] == 3 and child["text"] == "1a. Child question?"
    assert child["location"] == "child" and child["inline"][0]["text"] == "1a. "
    assert rendered["outline"][-1]["label"] == "1. Parent? › 1a. Child question?"
    assert rendered["contexts"]["child"]["text"] == "1a. Child question? Child answer."
