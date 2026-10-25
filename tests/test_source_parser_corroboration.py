"""Independent parser agreement and deliberate disagreement regressions."""
import hashlib
import subprocess

import pytest

from build.lib import source_parser_corroboration as parser_check


@pytest.mark.parametrize("source", [
    b'<root>before <b>bold</b> after<!-- note -->tail<?check yes?>end</root>',
    b'<!--before--><?pre x?><root xmlns="urn:test" xmlns:x="urn:attrs" x:a="yes">'
    b'a<![CDATA[b]]>c&amp;d&#x41;</root><?post y?><!--after-->',
    b'<!DOCTYPE root SYSTEM "file:///never-read-this"><root/>',
    b'<?xml version="1.0" encoding="ISO-8859-1"?><root>caf\xe9</root>',
    b'<root>\r\nx\r y</root>',
])
def test_xml_independent_parsers_agree(source):
    result = parser_check.corroborate(source, "xml")
    assert result["status"] == "pass", result
    assert result["source_sha256"] == hashlib.sha256(source).hexdigest()
    assert result["compared_event_counts"]["expat"] == result["compared_event_counts"]["lxml"]
    assert all(parser["version"] for parser in result["parsers"])


def test_xml_projection_preserves_comments_pi_tail_and_shell():
    source = b'<!--first--><a>x<b/>y<?p q?>z<!--last--></a><?after?>'
    expected = [
        ["comment", "first"], ["start", "a", []], ["text", "x"],
        ["start", "b", []], ["end", "b"], ["text", "y"],
        ["pi", "p", "q"], ["text", "z"], ["comment", "last"],
        ["end", "a"], ["pi", "after", ""],
    ]
    assert parser_check._xml_expat(source) == expected
    assert parser_check._xml_lxml(source) == expected


@pytest.mark.parametrize("encoded,decoded", [
    ("&amp;", "&"), ("&amp;#38;", "&#38;"), ("&amp;amp;", "&amp;"),
    ("&#38;", "&"), ("&#x26;", "&"),
    ("&lt;&gt;&quot;&apos;", "<>\"'"),
    ("&#13;&#10;&#9;", "\r\n\t"),
])
def test_xml_attributes_preserve_decoded_and_intentionally_literal_entities(encoded, decoded):
    source = f'<root href="{encoded}"/>'.encode("utf-8")
    expected_start = ["start", "root", [["href", decoded]]]
    assert parser_check._xml_expat(source)[0] == expected_start
    assert parser_check._xml_lxml(source)[0] == expected_start
    assert parser_check.corroborate(source, "xml")["status"] == "pass"


@pytest.mark.parametrize("source", [
    b'<!DOCTYPE a [<!ENTITY x "expanded">]><a>&x;</a>',
    b'<!DOCTYPE a [<!ENTITY x SYSTEM "file:///never-read-this">]><a>&x;</a>',
    b'<!DOCTYPE a [<!ENTITY % x SYSTEM "https://invalid.test">%x;]><a/>',
])
def test_custom_entities_never_reach_second_parser(source, monkeypatch):
    monkeypatch.setattr(parser_check, "_xml_lxml", lambda _: pytest.fail("unsafe input reached lxml"))
    result = parser_check.corroborate(source, "xml")
    assert result["status"] == "unsupported"
    assert result["findings"][0]["code"] == "unsupported-xml-entity"


def test_xml_parser_difference_is_not_silently_accepted(monkeypatch):
    monkeypatch.setattr(parser_check, "_xml_lxml", lambda _: [["start", "wrong", []]])
    assert parser_check.corroborate(b'<a/>', "xml")["status"] == "fail"


def test_malformed_xml_fails():
    assert parser_check.corroborate(b'<a><b></a>', "xml")["status"] == "fail"


@pytest.fixture
def node_required():
    if parser_check._node_path() is None:
        pytest.skip("Independent JSON corroboration requires installed Node.js")


@pytest.mark.parametrize("source", [
    '{"label":"Greek: λ; Hebrew: א; emoji: 😀","empty":[],"bool":false,"none":null}',
    '[1,1.0,1e0,-0,0.0001,123456789012345,1e100]',
    '{"z":0,"a":1,"nested":{"beta":2,"alpha":3}}',
    '"\\ud83d\\ude00"',
])
def test_json_independent_parsers_agree(source, node_required):
    result = parser_check.corroborate(source.encode("utf-8"), "json")
    assert result["status"] == "pass", result
    assert result["compared_event_counts"]["python-json"] == result["compared_event_counts"]["node-json"]
    assert len(result["parsers"]) == 2


@pytest.mark.parametrize("source", [
    b'[9007199254740993]', b'[0.10000000000000001]', b'[1e400]', b'[1e-400]',
    b'{"2":"second","1":"first"}',
])
def test_json_numeric_and_order_disagreements_surface(source, node_required):
    result = parser_check.corroborate(source, "json")
    assert result["status"] == "fail", result
    assert "disagreement" in result["findings"][0]["code"]


@pytest.mark.parametrize("source", [b'{"a":1,"a":2}', b'[NaN]', b'[Infinity]', b'{} extra', b'"\xff"'])
def test_invalid_json_rejected_before_node(source, monkeypatch):
    monkeypatch.setattr(parser_check, "_node_path", lambda: pytest.fail("invalid JSON reached Node"))
    result = parser_check.corroborate(source, "json")
    assert result["status"] == "fail"


def test_missing_node_is_unsupported(monkeypatch):
    monkeypatch.setattr(parser_check, "_node_path", lambda: None)
    result = parser_check.corroborate(b'{}', "json")
    assert result["status"] == "unsupported"
    assert result["findings"][0]["code"] == "node-unavailable"


def test_node_timeout_is_failure(monkeypatch):
    monkeypatch.setattr(parser_check, "_node_path", lambda: "node")

    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired("node", 30)

    monkeypatch.setattr(parser_check.subprocess, "run", timed_out)
    assert parser_check.corroborate(b'{}', "json")["status"] == "fail"


def test_node_nonzero_exit_is_failure(monkeypatch):
    monkeypatch.setattr(parser_check, "_node_path", lambda: "node")
    monkeypatch.setattr(parser_check.subprocess, "run", lambda *a, **k:
                        subprocess.CompletedProcess(a[0], 2, b'', b'parse rejected'))
    result = parser_check.corroborate(b'{}', "json")
    assert result["status"] == "fail"
    assert result["findings"][0]["code"] == "node-json-parse-error"


def test_exact_decimal_normalization_does_not_round():
    assert parser_check._number("1234567890123456789012345678901") == [0, "1234567890123456789012345678901", 0]
    assert parser_check._number("1.000") == parser_check._number("1e0")


@pytest.mark.parametrize("source", [
    b"\xef\xbb\xbfFirst\r\nsecond\nthird\r",
    "Greek: λ; emoji: 😀\n".encode("utf-8"),
    b"one line without terminator",
])
def test_plain_text_decoders_agree_without_stripping_bom(source, node_required):
    result = parser_check.corroborate(source, "text")
    assert result["status"] == "pass", result
    assert result["source_sha256"] == hashlib.sha256(source).hexdigest()
    assert len(result["parsers"]) == 2
    assert result["compared_event_counts"]["python-text"] == result["compared_event_counts"]["node-text"]


def test_invalid_utf8_text_rejected_before_node(monkeypatch):
    monkeypatch.setattr(parser_check, "_node_path", lambda: pytest.fail("invalid text reached Node"))
    result = parser_check.corroborate(b"bad\xff", "text")
    assert result["status"] == "fail"
    assert result["findings"][0]["code"] == "python-text-decode-error"


def test_plain_text_decoder_disagreement_surfaces(monkeypatch):
    monkeypatch.setattr(parser_check, "_node_path", lambda: "node")
    monkeypatch.setattr(parser_check.subprocess, "run", lambda *a, **k:
                        subprocess.CompletedProcess(a[0], 0,
                            b'{"version":"fixture","text":"wrong","line_endings":[]}', b''))
    result = parser_check.corroborate(b"right", "text")
    assert result["status"] == "fail"
    assert result["findings"][0]["code"] == "parser-event-disagreement"


def test_unknown_format_is_unsupported():
    assert parser_check.corroborate(b'anything', "html")["status"] == "unsupported"
