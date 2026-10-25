from pathlib import Path

import pytest
from lxml import html

from build.tei.newadvent_css import typography_map
from build.tei.newadvent_css_oracle import expected_typography_map


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def bindings():
    css = ROOT / "raw/newadvent/catholic-encyclopedia-assets-acquisition-20260911/batch-0010/000020.css"
    policy = ROOT / "plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/newadvent-css-minimal-mapping-policy-20260912.json"
    if not css.is_file():
        pytest.skip("Exact retained screen6 stylesheet fixture unavailable")
    return css.read_bytes(), policy.read_bytes()


def styles(markup, bindings):
    document = html.document_fromstring(markup)
    produced = typography_map(document, *bindings)
    expected = expected_typography_map(document, *bindings)
    assert produced == expected
    return {node.get("id"): record for node, record in produced.items() if node.get("id")}


def test_source_percentages_baseline_and_paragraph_overrides(bindings):
    found = styles('<html><body><div id="springfield2"><div class="pub" id="pub"><span id="inherited">Text</span><p id="p">Paragraph</p><h2 id="heading">Title</h2></div></div></body></html>', bindings)
    assert found["springfield2"]["declarations"]["font-size"] == "14px"
    assert found["pub"]["declarations"]["font-size"] == "11.2px"
    assert found["inherited"]["declarations"]["font-size"] == "11.2px"
    assert found["p"]["declarations"]["font-size"] == "14px"
    assert found["heading"]["declarations"]["font-size"] == "16.24px"
    assert found["heading"]["declarations"]["font-weight"] == "400"


def test_citation_and_noninherited_background_cues(bindings):
    found = styles('<div id="springfield2"><span id="apawork"><span id="child">A</span></span><span id="mlawork">M</span><span id="dedication">D</span><span class="stiki" id="sticky"><span id="stickychild">S</span></span></div>', bindings)
    for identifier in ("apawork", "mlawork"):
        assert found[identifier]["declarations"]["text-decoration"] == "underline"
    assert "text-decoration" not in found["child"]["declarations"]
    assert found["dedication"]["declarations"]["font-style"] == "italic"
    assert found["sticky"]["declarations"]["background-color"] == "white"
    assert "background-color" not in found["stickychild"]["declarations"]
    assert found["stickychild"]["declarations"]["color"] == "red"


def test_footer_cells_and_heading_weights(bindings):
    found = styles('<html><body><div id="ogdenville"><table><tr><td class="bar_white_on_color" id="cell"><span id="celltext">F</span><p id="footp">P</p></td></tr></table></div><b><div id="springfield2"><h1 id="one">1</h1><h3 id="three">3</h3><h4 id="four">4</h4><h5 id="five">5</h5><blockquote id="quote">Q</blockquote></div></b></body></html>', bindings)
    assert found["cell"]["declarations"]["font-size"] == "11.2px"
    assert found["celltext"]["declarations"]["text-align"] == "center"
    assert found["footp"]["declarations"]["font-size"] == "14px"
    assert [found[key]["declarations"]["font-weight"] for key in ("one", "three", "four", "five", "quote")] == ["400", "bold", "400", "500", "300"]
    assert found["one"]["declarations"]["line-height"] == "1.35"
    assert found["quote"]["declarations"]["letter-spacing"] == "1.92px"


def test_inline_wins_over_author_and_hints_do_not_override_author(bindings):
    found = styles('<div id="springfield2"><font class="stiki" color="blue" id="hint">H</font><span id="apawork" style="text-decoration:none;font-size:200%">I</span><p id="p" style="font-size:20px">P</p></div>', bindings)
    assert found["hint"]["declarations"]["color"] == "red"
    assert found["apawork"]["declarations"]["text-decoration"] == "none"
    assert found["apawork"]["declarations"]["font-size"] == "28px"
    assert found["p"]["declarations"]["font-size"] == "20px"


def test_unsupported_overlap_and_states_remain_explicit(bindings):
    found = styles('<div id="springfield2"><a id="link" href="x">L</a><font id="legacy" size="-2">S</font><span id="shorthand" style="font:italic 10px serif">X</span></div>', bindings)
    assert found["link"]["gates"] == []
    assert found["link"]["declarations"]["text-decoration"] == "none"
    assert found["legacy"]["declarations"]["font-size"] == "10px"
    assert "overlapping-inline-shorthand" in found["shorthand"]["gates"]


def test_calibrated_html_sizes_and_author_precedence(bindings):
    hints = ("1", "2", "3", "4", "5", "6", "7", "-2", "+1", "-999", "+999")
    found = styles('<div id="springfield2">' + ''.join(f'<font id="f{i}" size="{size}">T</font>' for i, size in enumerate(hints)) + '<font id="overridden" class="pub" size="7">O</font><font id="bad" size="large">B</font></div>', bindings)
    assert [found[f"f{i}"]["declarations"]["font-size"] for i in range(len(hints))] == ["10px", "13px", "16px", "18px", "24px", "32px", "48px", "10px", "18px", "10px", "48px"]
    assert found["overridden"]["declarations"]["font-size"] == "11.2px"
    assert "unsupported-html-font-size" in found["bad"]["gates"]


def test_excluded_ancestor_size_and_unsupported_inline_values(bindings):
    found = styles('<html><body><div style="font-size:20px"><div id="springfield2"><span id="child">T</span><p id="paragraph">P</p><span id="invalid" style="font-weight:potato">B</span><span id="longhand" style="text-decoration-line:underline">U</span></div></div></body></html>', bindings)
    assert found["springfield2"]["declarations"]["font-size"] == "20px"
    assert found["child"]["declarations"]["font-size"] == "20px"
    assert found["paragraph"]["declarations"]["font-size"] == "14px"
    assert "unsupported-inline-typography" in found["invalid"]["gates"]
    assert "overlapping-inline-shorthand" in found["longhand"]["gates"]


def test_browser_calibrated_native_sizes_and_heading_override(bindings):
    found = styles('<html><body><p><small id="small">S</small><big id="big">B</big><sup id="sup">U</sup><sub id="sub">D</sub></p><h1><small id="heading-small">H</small></h1></body></html>', bindings)
    for name in ("small", "sup", "sub"):
        assert float(found[name]["declarations"]["font-size"][:-2]) == pytest.approx(14 / 1.2)
    assert found["big"]["declarations"]["font-size"] == "16.8px"
    assert found["heading-small"]["declarations"]["font-size"] == "12.18px"


def test_core_page_integration_and_typography_mutation(bindings):
    from build.tei.newadvent_reconstruction import project_page
    from build.tei.newadvent_oracle import verify_page
    source = b'<html><head><title>A</title></head><body><div id="springfield2"><h1>A</h1><p><font size="-2">Small</font> <span id="apawork">Citation</span></p></div><div id="ogdenville"><p>Publisher</p></div></body></html>'
    url = "https://www.newadvent.org/cathen/01001a.htm"
    css, policy = bindings
    candidate, _ = project_page(source, url, "sample", css_bytes=css, policy_bytes=policy)
    assert verify_page(source, url, "sample", candidate, css_bytes=css, policy_bytes=policy)["status"] == "pass"
    heading = candidate.xpath('//*[local-name()="head"]')[0]
    heading.set("style", heading.get("style").replace("font-size:20.3px;", "font-size:14px;"))
    with pytest.raises(ValueError, match="semantic mapping/attribute"):
        verify_page(source, url, "sample", candidate, css_bytes=css, policy_bytes=policy)


@pytest.mark.parametrize("relative,digest,count", [
    ("batch-0013/000085.html", "a217a9c82b8267f76c2562973ed574b64a1e320b1b368746afed6d6534165c83", 9),
    ("batch-0002/000046.html", "ede270e62fcb93ab86103d2ecd8838e0f957784bb59326b57ae06a9b1abea4c0", 12),
])
def test_retained_table_header_defaults(bindings, relative, digest, count):
    import hashlib
    from build.tei.newadvent_reconstruction import _parse_page
    path = ROOT / "raw/newadvent/catholic-encyclopedia-complete-acquisition-20260911" / relative
    if not path.is_file():
        pytest.skip("Exact retained table source fixture unavailable")
    payload = path.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == digest
    document = _parse_page(payload)
    actual = typography_map(document, *bindings)
    assert actual == expected_typography_map(document, *bindings)
    headers = [node for node in document.iter() if node.tag == "th"]
    assert len(headers) == count
    assert all(actual[node]["declarations"]["font-weight"] == "bold" and actual[node]["declarations"]["text-align"] == "center" for node in headers)


def test_table_header_author_and_inherited_alignment_precedence(bindings):
    found = styles('<html><body><table><tr><th id="default">D</th><th id="inline" style="font-weight:400;text-align:left">I</th><th id="hint" align="right">H</th></tr></table><table style="text-align:right"><tr><th id="inherited">R</th></tr></table></body></html>', bindings)
    assert found["default"]["declarations"]["font-weight"] == "bold"
    assert found["default"]["declarations"]["text-align"] == "center"
    assert found["inline"]["declarations"]["font-weight"] == "400"
    assert found["inline"]["declarations"]["text-align"] == "left"
    assert found["hint"]["declarations"]["text-align"] == "right"
    assert found["inherited"]["declarations"]["text-align"] == "right"


@pytest.mark.parametrize("declaration", ["font-weight:bold;", "text-align:center;"])
def test_table_header_typography_mutation_rejected(bindings, declaration):
    from build.tei.newadvent_reconstruction import project_page
    from build.tei.newadvent_oracle import verify_page
    source = b'<html><head><title>A</title></head><body><div id="springfield2"><h1>A</h1><table><tr><th>Heading</th></tr></table></div><div id="ogdenville"><p>Publisher</p></div></body></html>'
    url = "https://www.newadvent.org/cathen/01001a.htm"
    css, policy = bindings
    candidate, _ = project_page(source, url, "sample", css_bytes=css, policy_bytes=policy)
    assert verify_page(source, url, "sample", candidate, css_bytes=css, policy_bytes=policy)["status"] == "pass"
    cell = candidate.xpath('//*[local-name()="cell"]')[0]
    cell.set("style", cell.get("style").replace(declaration, ""))
    with pytest.raises(ValueError, match="semantic mapping/attribute"):
        verify_page(source, url, "sample", candidate, css_bytes=css, policy_bytes=policy)


@pytest.mark.parametrize("relative,digest,table_count", [
    ("batch-0004/000045.html", "b1e697ea41aa7b3091eb86e94f6d7fa789a89e422613a509b6a16f1604433b19", 4),
    ("batch-0013/000021.html", "d87261ac6615e18abd87dc8f5332358ea56fa21d1d592381ceb2755f9f8043f9", 9),
])
def test_retained_table_box_alignment_does_not_center_cell_text(bindings, relative, digest, table_count):
    import hashlib
    from build.tei.newadvent_reconstruction import _parse_page
    path = ROOT / "raw/newadvent/catholic-encyclopedia-complete-acquisition-20260911" / relative
    if not path.is_file():
        pytest.skip("Exact retained table source fixture unavailable")
    payload = path.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == digest
    document = _parse_page(payload)
    actual = typography_map(document, *bindings)
    assert actual == expected_typography_map(document, *bindings)
    tables = [node for node in document.iter() if node.tag == "table" and node.get("align") == "center"]
    assert len(tables) == table_count
    assert all(actual[node]["declarations"]["text-align"] == "start" for node in tables)


def test_table_box_alignment_preserved_without_invented_cell_centering(bindings):
    from build.tei.newadvent_reconstruction import project_page
    from build.tei.newadvent_oracle import verify_page
    source = b'<html><head><title>A</title></head><body><div id="springfield2"><h1>A</h1><table align="center"><tr><th>Year</th></tr><tr><td>1901</td><td align="right">123</td></tr></table></div><div id="ogdenville"><p>Publisher</p></div></body></html>'
    url = "https://www.newadvent.org/cathen/01001a.htm"
    css, policy = bindings
    candidate, _ = project_page(source, url, "sample", css_bytes=css, policy_bytes=policy)
    assert verify_page(source, url, "sample", candidate, css_bytes=css, policy_bytes=policy)["status"] == "pass"
    table = candidate.xpath('//*[local-name()="table"]')[0]
    assert '"align":"center"' in table.get("rend")
    cells = candidate.xpath('//*[local-name()="cell"]')
    assert "text-align:center;" in cells[0].get("style")
    assert "text-align:start;" in cells[1].get("style")
    assert "text-align:right;" in cells[2].get("style")
    cells[1].set("style", cells[1].get("style").replace("text-align:start;", "text-align:center;"))
    with pytest.raises(ValueError, match="semantic mapping/attribute"):
        verify_page(source, url, "sample", candidate, css_bytes=css, policy_bytes=policy)


@pytest.mark.parametrize("helper", [typography_map, expected_typography_map])
def test_bindings_reject_mutation_and_empty_css_is_no_author_styles(bindings, helper):
    document = html.document_fromstring('<p>Text</p>')
    css, policy = bindings
    with pytest.raises(ValueError, match="stylesheet"):
        helper(document, css + b" ", policy)
    with pytest.raises(ValueError, match="policy"):
        helper(document, css, policy + b" ")
    assert all(record["declarations"] == {} for record in helper(document).values())
