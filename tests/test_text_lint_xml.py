"""Every parent text and child tail is scanned once, with no invented reading stream."""
import json
import pytest
from build.lib.text_lint import lint_xml_file
from build.tools.lint_text import main


def test_parent_nested_note_inline_tail_and_index_coverage(tmp_path):
    path = tmp_path / "source.xml"
    text = '<doc><head>\ufffd</head><p>\ufffd<note>\ufffd</note>\ufffd<hi>\ufffd</hi>\ufffd</p><index>\ufffd</index></doc>'
    path.write_text(text, encoding="utf-8")
    report = lint_xml_file(path)
    assert len(report["observations"]) == 7
    assert len(set(o["locator"] for o in report["observations"])) == 7
    assert report["coverage"]["characters"] == 7
    assert report["text_correctness"] == "not_assessed"
    assert path.read_text(encoding="utf-8") == text


def test_comments_pis_attributes_are_outside_scope_but_tails_count(tmp_path):
    path = tmp_path / "source.xml"
    path.write_text('<d title="\ufffd"><!--\ufffd-->\ufffd<?pi bad?>\ufffd</d>', encoding="utf-8")
    report = lint_xml_file(path)
    assert len(report["observations"]) == 2
    assert "Attributes" in report["coverage"]["limits"]


def test_no_lexical_or_alternative_joining(tmp_path):
    path = tmp_path / "source.xml"
    path.write_text('<p>Herzog<note>1</note>vol of <choice><sic>of</sic><corr>in</corr></choice></p>')
    report = lint_xml_file(path)
    assert report["observations"] == []
    assert "adjacent_repetition" in report["rules_not_run"]


@pytest.mark.parametrize("marker", ["Ã©", "Î¼", "Ïƒ", "á¼"])
def test_common_latin1_mojibake_markers_are_located(tmp_path, marker):
    path = tmp_path / "source.xml"
    path.write_text(f"<p>{marker}</p>", encoding="utf-8")
    report = lint_xml_file(path)
    findings = [item for item in report["observations"]
                if item["rule"] == "encoding_sequence_present"]
    assert [item["text"] for item in findings] == [marker]
    assert findings[0]["editorial_assessment"] == "not_determined"


@pytest.mark.parametrize("text", ['<d>', '<!DOCTYPE d [<!ENTITY e SYSTEM "file:///missing">]><d>&e;</d>'])
def test_unsupported_xml_is_blocked(tmp_path, text):
    path = tmp_path / "source.xml"
    path.write_text(text)
    with pytest.raises(ValueError):
        lint_xml_file(path)


def test_xml_cli_and_determinism(tmp_path, capsys):
    path = tmp_path / "source.xml"
    path.write_text('<d>\ufffd</d>', encoding="utf-8")
    assert main([str(path), "--xml-segments"]) == 0
    first = capsys.readouterr().out
    assert json.loads(first)["text_correctness"] == "not_assessed"
    assert main([str(path), "--xml-segments"]) == 0
    assert first == capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        main([str(path), "--xml-segments", "--language", "en"])
    assert exc.value.code == 2


def test_wide_namespace_tree_locators_and_comment_tails(tmp_path):
    from lxml import etree

    path = tmp_path / "source.xml"
    path.write_text('<d xmlns="urn:test">' + '<p>text</p>' * 20000 +
                    '<p>\ufffd</p><!--ignored-->\ufffd<?pi ignored?>\ufffd</d>', encoding="utf-8")
    report = lint_xml_file(path)
    assert report["coverage"]["units"] == 20003
    tree = etree.parse(str(path))
    for observation in report["observations"]:
        locator = observation["locator"]
        if locator.endswith("/following-text()"):
            node, = tree.xpath(locator.removesuffix("/following-text()"))
            assert node.tail == "\ufffd"
        else:
            assert tree.xpath(locator) == ["\ufffd"]


def test_deep_xml_does_not_depend_on_python_recursion(tmp_path):
    path = tmp_path / "deep.xml"
    path.write_text('<d>' * 600 + '\ufffd' + '</d>' * 600, encoding="utf-8")
    report = lint_xml_file(path)
    assert len(report["observations"]) == 1
    assert report["coverage"]["characters"] == 1


def test_header_original_corrected_and_tails_have_separate_context(tmp_path):
    path = tmp_path / "alternatives.xml"
    path.write_text('<TEI><teiHeader><note>\ufffd</note></teiHeader><text><body><p>'
                    '<choice><sic>\ufffd<hi>\ufffd</hi>\ufffd</sic><corr>\ufffd</corr></choice>\ufffd'
                    '</p></body></text></TEI>', encoding="utf-8")
    report = lint_xml_file(path)
    from collections import Counter
    assert Counter((o["region"], o["reading"]) for o in report["observations"]) == {
        ("header", None): 1, ("body", "sic"): 3, ("body", "corr"): 1, ("body", None): 1}
