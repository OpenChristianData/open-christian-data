from pathlib import Path

import pytest
from lxml import etree

from build.tei.newadvent_reconstruction import project_page


NS = {"t": "http://www.tei-c.org/ns/1.0"}
TEI = "{http://www.tei-c.org/ns/1.0}"
ROOT = Path(__file__).resolve().parents[1]


def page(body):
    return f'<html><head><title>Test</title></head><body><div id="springfield2">{body}</div><div id="ogdenville"><p>Publisher</p></div></body></html>'.encode()


def test_hex_color_and_explicit_greek_carrier():
    source = page('<p><font color="#Cc3333">RELATED ARTICLES</font> before <greek>Κεδές</greek> after.</p>')
    result, _ = project_page(source, "https://www.newadvent.org/cathen/03475b.htm", "test")
    assert result.xpath('.//t:hi/@style', namespaces=NS) == ["color:#cc3333;"]
    greek = result.xpath('.//t:seg[@type="source-greek"]', namespaces=NS)[0]
    assert greek.text == "Κεδές" and greek.tail == " after."
    assert greek.get("ana") == "html-greek" and greek.get("style") is None
    assert greek.get("{http://www.w3.org/XML/1998/namespace}lang") is None
    validate(result)


@pytest.mark.parametrize("color", ["#cc3", "#cc33333", "#gg3333", "#cc3333;display:none", " #cc3333"])
def test_malformed_or_unmapped_font_colors_rejected(color):
    with pytest.raises(ValueError, match="font color"):
        project_page(page(f'<p><font color="{color}">text</font></p>'), "https://www.newadvent.org/cathen/", "test")


def test_unrecognized_custom_carrier_still_rejected():
    with pytest.raises(ValueError, match="Unsupported source element"):
        project_page(page('<p><unknowncarrier>text</unknowncarrier></p>'), "https://www.newadvent.org/cathen/", "test")


def test_block_emphasis_p5_accounting_and_native_rendering():
    from tests.test_newadvent_oracle import BLOCK_EM_SOURCE
    from build.tei.newadvent_oracle import verify_page
    url = "https://www.newadvent.org/cathen/01137a.htm"
    result, evidence = project_page(BLOCK_EM_SOURCE, url, "test")
    assert verify_page(BLOCK_EM_SOURCE, url, "test", result)["status"] == "pass"
    assert result.xpath('.//t:quote/t:p/@style', namespaces=NS) == ["font-style:italic;", "font-style:italic;"]
    assert result.xpath('.//t:div[@ana="html-em"]/@rend', namespaces=NS) == ["italic"]
    assert [event["tei_tag"] for event in evidence["events"] if event["source_tag"] == "em"] == ["span", "div"]
    assert len(result.xpath('.//t:quote', namespaces=NS)) == 1
    validate(result)


def validate(projected):
    root = etree.fromstring(b'<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc><titleStmt><title>Test</title></titleStmt><publicationStmt><p>Test only</p></publicationStmt><sourceDesc><p>Synthetic source</p></sourceDesc></fileDesc></teiHeader><text><body/></text></TEI>')
    root.find(f"{TEI}text/{TEI}body").append(projected)
    schema = etree.XMLSchema(etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd")))
    schema.assertValid(root)


def test_headings_group_following_paragraphs_at_source_levels():
    result, _ = project_page(page('<h1>Article</h1><p>Intro</p><h2>One</h2><p>A</p><h3>Child</h3><p>B</p><h2>Two</h2><p>C</p>'), "https://www.newadvent.org/cathen/01001a.htm", "test")
    sections = result.xpath('.//t:div[@type="source-section"]', namespaces=NS)
    assert [node.get("subtype") for node in sections] == ["h1", "h2", "h3", "h2"]
    assert sections[2].getparent() is sections[1]
    assert sections[3].getparent() is sections[0]
    assert "".join(sections[1].itertext()) == "OneAChildB"
    validate(result)


def test_mixed_order_list_numbering_and_table_spans_survive():
    source = page('<h1>Article</h1><p>Before <b>bold</b> after <a href="01002a.htm#x">link</a>.</p><ol start="3"><li value="4">Item</li></ol><table><tr><th colspan="2">Header</th></tr><tr><td>A</td><td rowspan="2">B</td></tr></table>')
    result, _ = project_page(source, "https://www.newadvent.org/cathen/01001a.htm", "test")
    assert result.xpath('.//t:ref/@target', namespaces=NS) == ["https://www.newadvent.org/cathen/01002a.htm#x"]
    assert result.xpath('.//t:list/@n', namespaces=NS) == ["3"]
    assert result.xpath('.//t:item/@n', namespaces=NS) == ["4"]
    assert result.xpath('.//t:cell[@role="label"]/@cols', namespaces=NS) == ["2"]
    assert result.xpath('.//t:cell/@rows', namespaces=NS) == ["2"]
    assert "Before bold after link." in "".join(result.itertext())
    validate(result)


def test_inline_run_keeps_source_whitespace():
    result, _ = project_page(page(' <a href="01002a.htm">A</a> <b>B</b> '), "https://www.newadvent.org/cathen/01001a.htm", "test")
    assert "".join(result[0].itertext()) == " A B "
    validate(result)


def test_missing_image_fails_and_retained_image_keeps_alternative_text():
    source = page('<h1>Article</h1><p><img src="../images/a.png" alt="Plan of the abbey"></p>')
    with pytest.raises(ValueError, match="image is not retained"):
        project_page(source, "https://www.newadvent.org/cathen/01001a.htm", "test")
    result, _ = project_page(source, "https://www.newadvent.org/cathen/01001a.htm", "test", {"https://www.newadvent.org/images/a.png": ("image/png", b"synthetic-image")})
    assert result.xpath('.//t:figDesc/text()', namespaces=NS) == ["Plan of the abbey"]
    assert result.xpath('.//t:graphic/@url', namespaces=NS) == ["data:image/png;base64,c3ludGhldGljLWltYWdl"]
    validate(result)


def test_unknown_source_element_fails_closed():
    with pytest.raises(ValueError, match="Unsupported source element"):
        project_page(page('<canvas>unmapped</canvas>'), "https://www.newadvent.org/cathen/01001a.htm", "test")


def test_direct_nested_list_preserves_parent_without_guessing_item_attachment():
    from build.tei.newadvent_oracle import verify_page
    source = page('<h1>Cosmology</h1><ul><li>Topic</li><ul><li>First cause</li></ul><li>Next topic</li></ul>')
    url = "https://www.newadvent.org/cathen/04413a.htm"
    result, _ = project_page(source, url, "test")
    nested = result.xpath('.//t:item[@ana="source-direct-nested-list"]', namespaces=NS)[0]
    assert nested.getprevious().text == "Topic"
    assert verify_page(source, url, "test", result)["status"] == "pass"
    validate(result)


def test_empty_ad_layout_inside_quotation_keeps_neighboring_paragraphs():
    from build.tei.newadvent_oracle import verify_page
    source = page('<h1>History</h1><blockquote><p>Quoted first.</p><div class="CMtag_300x250" style="height:300px"></div><p>Quoted next.</p></blockquote><p>After quotation.</p>')
    url = "https://www.newadvent.org/cathen/00001a.htm"
    result, _ = project_page(source, url, "test")
    assert result.xpath('.//t:quote/t:milestone/@unit', namespaces=NS) == ["empty-html-div"]
    assert "".join(result.xpath('.//t:quote', namespaces=NS)[0].itertext()) == "Quoted first.Quoted next."
    assert verify_page(source, url, "test", result)["status"] == "pass"
    validate(result)


def test_definition_lists_and_source_font_presentation_remain_readable():
    from build.tei.newadvent_oracle import verify_page
    source = page('<h1>Article</h1><p><font size="-2">Small citation</font> <font size="+1" color="red">Large red</font><span lang="la" style="font-style:italic;">Latin</span></p><dl><dt>Term</dt><dd>Definition</dd></dl>')
    url = "https://www.newadvent.org/cathen/01001a.htm"
    result, _ = project_page(source, url, "test")
    assert result.xpath('.//t:hi/@style', namespaces=NS) == ["font-size:x-small;", "font-size:large;color:red;"]
    assert result.xpath('.//t:list[@type="gloss"]/t:label/text()', namespaces=NS) == ["Term"]
    assert verify_page(source, url, "test", result)["status"] == "pass"
    validate(result)
    result.xpath('.//t:hi', namespaces=NS)[0].attrib.pop("style")
    with pytest.raises(ValueError, match="semantic mapping/attribute"):
        verify_page(source, url, "test", result)
