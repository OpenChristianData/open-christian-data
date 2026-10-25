from copy import deepcopy

import pytest
from lxml import etree

from build.tei.newadvent_reconstruction import project_page
from build.tei.newadvent_oracle import envelope_for_page, verify_page


URL = "https://www.newadvent.org/cathen/01001a.htm"
NS = {"t": "http://www.tei-c.org/ns/1.0"}
SOURCE = b'<html><head><title>Article</title></head><body><div id="springfield2"><h1>Article</h1><p>Opening <b>bold</b> tail.</p><h2>First</h2><p>First body</p><ul><li>One</li><li>Two</li></ul><h2>Second</h2><p>Second <a href="01002a.htm">link</a>.</p></div><div id="ogdenville"><p>Copyright statement</p></div></body></html>'


BLOCK_EM_SOURCE = b'<html><head><title>A</title></head><body><div id="springfield2"><h1>A</h1><blockquote>Before<em>\n<p>First <b>word</b> tail.</p>\n<p>Second.</p>\n</em>After</blockquote><em><h2>Section</h2><p>Body</p><div><h3>Nested</h3><p>Nested body</p></div></em><p>Outside</p></div><div id="ogdenville"><p>Publisher</p></div></body></html>'


@pytest.mark.parametrize("mutation", ["missing-start", "missing-end", "reverse", "moved-start", "endpoint", "extra", "escape", "format", "text", "tail", "heading", "invented-quote"])
def test_block_emphasis_interval_mutations(mutation):
    candidate, _ = project_page(BLOCK_EM_SOURCE, URL, "sample")
    assert verify_page(BLOCK_EM_SOURCE, URL, "sample", candidate)["status"] == "pass"
    span = candidate.xpath('.//t:span', namespaces=NS)[0]
    quote = candidate.xpath('.//t:quote', namespaces=NS)[0]
    start, end = quote.xpath('./t:anchor', namespaces=NS)
    paragraph = quote.xpath('./t:p', namespaces=NS)[0]
    if mutation == "missing-start":
        quote.remove(start)
    elif mutation == "missing-end":
        quote.remove(end)
    elif mutation == "reverse":
        quote.insert(0, end)
    elif mutation == "moved-start":
        quote.insert(quote.index(paragraph) + 1, start)
    elif mutation == "endpoint":
        span.set("to", span.get("from"))
    elif mutation == "extra":
        quote.insert(quote.index(end), etree.Element('{http://www.tei-c.org/ns/1.0}p'))
    elif mutation == "escape":
        quote.insert(quote.index(end) + 1, paragraph)
    elif mutation == "format":
        paragraph.attrib.pop("style")
    elif mutation == "text":
        paragraph.text = "Changed"
    elif mutation == "tail":
        end.tail = "Changed"
    elif mutation == "heading":
        outer = candidate.xpath('.//t:div[@ana="html-em"]', namespaces=NS)[0]
        section = outer.xpath('./t:div[@type="source-section"]', namespaces=NS)[0]
        for following in list(section)[1:]:
            outer.append(following)
    else:
        span.tag = '{http://www.tei-c.org/ns/1.0}quote'
    with pytest.raises(ValueError):
        verify_page(BLOCK_EM_SOURCE, URL, "sample", candidate)


@pytest.mark.parametrize("mutation", ["color", "greek-type", "greek-language", "greek-style", "greek-text", "greek-parent"])
def test_hex_color_and_greek_mutations_rejected(mutation):
    source = SOURCE.replace(b"Opening <b>bold</b>", '<font color="#cc3333">RELATED ARTICLES</font> <greek>Κεδές</greek>'.encode())
    candidate, _ = project_page(source, URL, "sample")
    assert verify_page(source, URL, "sample", candidate)["status"] == "pass"
    greek = candidate.xpath('.//t:seg[@type="source-greek"]', namespaces=NS)[0]
    if mutation == "color":
        candidate.xpath('.//t:hi', namespaces=NS)[0].set("style", "color:#cc3334;")
    elif mutation == "greek-type":
        greek.set("type", "other")
    elif mutation == "greek-language":
        greek.set("{http://www.w3.org/XML/1998/namespace}lang", "grc")
    elif mutation == "greek-style":
        greek.set("style", "font-style:italic;")
    elif mutation == "greek-text":
        greek.text = "Changed"
    else:
        candidate.xpath('.//t:p', namespaces=NS)[1].append(greek)
    with pytest.raises(ValueError):
        verify_page(source, URL, "sample", candidate)


def test_real_readable_tree_relationships_pass():
    candidate, _ = project_page(SOURCE, URL, "sample")
    assert verify_page(SOURCE, URL, "sample", candidate)["status"] == "pass"


def test_malformed_source_attribute_spelling_cannot_be_silently_coerced():
    source = SOURCE.replace(b'href="01002a.htm"', b'href<="01002a.htm"')
    candidate, _ = project_page(source, URL, "sample")
    assert verify_page(source, URL, "sample", candidate)["status"] == "pass"
    nonlink = candidate.xpath('.//t:seg[@ana="html-a"]', namespaces=NS)[0]
    assert 'href<' in nonlink.get("rend") and "target" not in nonlink.attrib
    nonlink.tag = "{http://www.tei-c.org/ns/1.0}ref"
    nonlink.set("target", URL)
    with pytest.raises(ValueError, match="semantic mapping/attribute"):
        verify_page(source, URL, "sample", candidate)


def test_browser_recovered_footer_emphasis_remains_effective():
    source = b'<html><head><title>A</title></head><body><div id="springfield2"><h1>A</h1><p><em>Unclosed source emphasis</div>\n\n<div id="ogdenville"><p>Publisher</p></div></body></html>'
    candidate, _ = project_page(source, URL, "sample")
    assert candidate[1].get("style") == "font-style:italic;"
    assert verify_page(source, URL, "sample", candidate)["status"] == "pass"
    envelope = envelope_for_page(source, URL, "source")
    assert any(item["disposition"] == "browser-recovered-inherited-formatting-context" for item in envelope["body_regions"])
    candidate[1].attrib.pop("style")
    with pytest.raises(ValueError, match="semantic mapping/attribute"):
        verify_page(source, URL, "sample", candidate)


def test_retained_link_targets_are_self_contained_and_source_bound():
    source = SOURCE.replace(b'<p>Opening', b'<p><a href="../images/full.png">Full diagram</a></p><p>Opening')
    full_image = "https://www.newadvent.org/images/full.png"
    images = {full_image: ("image/png", b"exact linked binary")}
    targets = {"https://www.newadvent.org/cathen/01002a.htm": "other-retained-page"}
    candidate, _ = project_page(source, URL, "sample", images, targets)
    links = candidate.xpath(".//t:ref", namespaces=NS)
    assert links[0].get("target").startswith("data:image/png;base64,")
    assert links[0].get("corresp") == full_image
    assert links[1].get("target") == "#other-retained-page"
    assert verify_page(source, URL, "sample", candidate, images, targets)["status"] == "pass"
    links[1].set("target", "#wrong-page")
    with pytest.raises(ValueError, match="semantic mapping/attribute"):
        verify_page(source, URL, "sample", candidate, images, targets)


@pytest.mark.parametrize("mutation", ["omit", "duplicate", "reorder", "text", "link", "format", "move-heading-body"])
def test_readable_semantic_mutations_rejected(mutation):
    candidate, _ = project_page(SOURCE, URL, "sample")
    paragraphs = candidate.xpath(".//t:p", namespaces=NS)
    if mutation == "omit":
        paragraphs[1].getparent().remove(paragraphs[1])
    elif mutation == "duplicate":
        paragraphs[1].getparent().append(deepcopy(paragraphs[1]))
    elif mutation == "reorder":
        items = candidate.xpath(".//t:item", namespaces=NS)
        items[0].getparent().append(items[0])
    elif mutation == "text":
        paragraphs[0].text = "Invented"
    elif mutation == "link":
        candidate.xpath(".//t:ref", namespaces=NS)[0].set("target", URL)
    elif mutation == "format":
        candidate.xpath(".//t:hi", namespaces=NS)[0].set("rend", "italic")
    else:
        # Keep the flat node order/text intact while moving content across its
        # heading boundary: a conservation-only check would miss this.
        sections = candidate.xpath('.//t:div[@type="source-section"]', namespaces=NS)
        first_body = paragraphs[1].getparent()
        sections[0].insert(list(sections[0]).index(sections[1]) + 1, first_body)
    with pytest.raises(ValueError):
        verify_page(SOURCE, URL, "sample", candidate)


def test_image_payload_and_alt_are_independently_checked():
    source = b'<html><body><div id="springfield2"><h1>A</h1><p><img src="../images/a.png" alt="Plan"></p></div><div id="ogdenville"><p>Footer</p></div></body></html>'
    images = {"https://www.newadvent.org/images/a.png": ("image/png", b"pixels")}
    candidate, _ = project_page(source, URL, "sample", images)
    assert verify_page(source, URL, "sample", candidate, images)["status"] == "pass"
    candidate.xpath(".//t:figDesc", namespaces=NS)[0].text = "Changed"
    with pytest.raises(ValueError, match="alternative text"):
        verify_page(source, URL, "sample", candidate, images)


def test_browser_numeric_reference_meaning_is_preserved():
    source = SOURCE.replace(b"Opening", b"&#151; &#x96; &#147;Quoted&#148;")
    candidate, _ = project_page(source, URL, "sample")
    assert "— – “Quoted”" in "".join(candidate.itertext())
    assert "\x97" not in "".join(candidate.itertext())
    assert verify_page(source, URL, "sample", candidate)["status"] == "pass"


def test_literal_control_is_not_misclassified_as_numeric_reference():
    with pytest.raises(ValueError, match="Literal UTF-8 C1"):
        project_page(SOURCE.replace(b"Opening", "\x97".encode("utf-8")), URL, "sample")


def test_complete_envelope_rejects_unexplained_appendix_outside_selected_main():
    envelope = envelope_for_page(SOURCE, URL, "article")
    assert [row["disposition"] for row in envelope["body_regions"]] == ["readable-main", "readable-publisher-footer"]
    extra = SOURCE.replace(b"</body>", b'<div id="unexpected-appendix"><p>Additional work content</p></div></body>')
    with pytest.raises(ValueError, match="Unexplained source body region"):
        envelope_for_page(extra, URL, "article")
