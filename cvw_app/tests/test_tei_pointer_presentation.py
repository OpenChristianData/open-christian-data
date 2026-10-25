"""Review-only visibility of TEI markers and literal pointer relationships."""

import pytest

from cvw_app.review_renderers import DEFAULT_RENDERER_REGISTRY


def render(body):
    exact = f'<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>{body}</body></text></TEI>'
    result, _ = DEFAULT_RENDERER_REGISTRY.render(
        "tei-reader", "application/tei+xml", exact
    )
    return result


@pytest.mark.parametrize("wrapper", ["p", "note", "l", "div"])
def test_empty_anchor_and_pointer_are_visible_in_each_text_projection(wrapper):
    result = render(
        f'<{wrapper}>Before<anchor xml:id="iv-p1.1" '
        'type="scripture-commentary-marker" n="Bible:1Cor.1.30" '
        'corresp="#verse"/><ptr target="#iv-p1.1 #verse"/>After'
        f'</{wrapper}>'
    )
    text = " ".join(node["text"] for node in result["nodes"])
    assert text.index("Before") < text.index("[TEI review: anchor")
    assert text.index("[TEI review: anchor") < text.index("[TEI review: ptr") < text.index("After")
    for field in ('xml:id="iv-p1.1"', 'type="scripture-commentary-marker"',
                  'n="Bible:1Cor.1.30"', 'corresp="#verse"',
                  'target="#iv-p1.1 #verse"'):
        assert field in text
    assert text.count("[TEI review: anchor") == 1
    assert text.count("[TEI review: ptr") == 1


def test_index_refs_preserve_content_without_review_scaffolding():
    result = render(
        '<p><ref xml:id="xxviii-p30.1" type="scripture" '
        'n="Bible:Gen.1.2">Genesis 1:2</ref></p>'
        '<p><anchor xml:id="xi-p1.1" type="scripture-commentary-marker" '
        'n="Bible:Ps.45.7"/></p>'
        '<p><anchor xml:id="xxxix.i-p0.2" type="index-insertion" subtype="scripRef"/>'
        '<ref target="#xxviii-p30.1">Genesis entry</ref></p>'
        '<p><anchor xml:id="xxxix.ii-p0.2" type="index-insertion" subtype="scripCom"/>'
        '<ref target="#xi-p1.1">Psalms entry</ref></p>'
    )
    text = " ".join(node["text"] for node in result["nodes"])
    for identity in ("xi-p1.1", "xxxix.i-p0.2", "xxxix.ii-p0.2"):
        assert f'xml:id="{identity}"' in text
    assert "[TEI review: ref" not in text
    assert "Genesis entry" in text
    assert "Psalms entry" in text
    assert "Genesis 1:2" in text
    assert 'subtype="scripCom"' in text
    assert 'subtype="scripRef"' in text


def test_reference_annotations_remain_inert_and_preserve_inline_emphasis():
    result = render('<p><ref target="javascript:alert(1)"><hi rend="italic">Label</hi></ref> tail</p>')
    node = result["nodes"][0]
    assert node["inline"] == [
        {"text": "Label", "marks": ["italic"]},
        {"text": " tail", "marks": []},
    ]
    assert "href" not in node


@pytest.mark.parametrize("wrapper", ["p", "note", "l", "div"])
def test_citation_refs_do_not_inject_scaffolding_in_any_text_projection(wrapper):
    result = render(
        f'<{wrapper}>See (<ref xml:id="citation" type="scripture" '
        'n="Bible:Matt.5.1" target="#passage">Matthew 5:1, 2</ref>), then '
        f'<ref target="#index">Genesis</ref>.</{wrapper}>'
    )
    text = " ".join(node["text"] for node in result["nodes"])
    assert text == "See (Matthew 5:1, 2), then Genesis."


def test_reference_fix_preserves_existing_paragraph_navigation():
    result = render('<p xml:id="passage">See <ref target="#passage">Matthew</ref>.</p>')
    assert result["nodes"][0]["location"] == "passage"
    assert result["contexts"]["passage"]["text"] == "See Matthew."
    assert result["outline"][0]["location"] == "passage"


def test_plain_text_and_unattributed_reference_stay_unchanged():
    assert render('<p>Before <ref>label</ref> after.</p>')["nodes"] == [
        {"type": "paragraph", "text": "Before label after."}
    ]
