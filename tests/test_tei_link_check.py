"""Regression checks for document-local fragments, independent of text equality."""
import json
import pytest
from build.lib.tei_link_check import check_links
from build.tools.check_tei_links import main


def document(body, header=""):
    return (f'<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader>{header}</teiHeader>'
            f'<text><body>{body}</body></text></TEI>').encode()


def test_closure_and_external_limits():
    report = check_links(document('<p xml:id="a"/><ref target="#a https://example.org/#other"/>'))
    assert report["status"] == "pass" and len(report["checked"]) == 1
    assert report["external_tokens_not_checked"] == 1
    assert report["intended_source_target"] == "not-assessed"


@pytest.mark.parametrize("target,count", [('<p n="a"/>', 0), ('<p xml:id="a"/><p xml:id="a"/>', 2)])
def test_ids_as_data_and_duplicate_targets_fail(target, count):
    report = check_links(document(target + '<ref target="#a"/>'))
    assert report["status"] == "fail"
    assert any(f.get("count") == count for f in report["findings"])


def test_lists_percent_encoding_and_header_targets():
    report = check_links(document('<ref target="#a #caf%C3%A9"/>', '<p xml:id="a"/><p xml:id="caf\u00e9"/>'))
    assert report["status"] == "pass" and len(report["checked"]) == 2


def test_base_and_complex_fragment_explicitly_incomplete():
    report = check_links(document('<p xml:base="other.xml"><ref target="#a"/></p><ref target="#xpointer(/)"/>'))
    assert report["status"] == "incomplete" and len(report["unsupported"]) == 2


def test_empty_fragment_and_foreign_attributes():
    assert check_links(document('<ref target="#"/>'))["status"] == "fail"
    assert check_links(document('<x xmlns="urn:foreign" target="#missing"/>'))["status"] == "pass"


def test_wrong_existing_target_needs_source_comparison():
    report = check_links(document('<p xml:id="a"/><p xml:id="b"/><ref target="#b"/>'))
    assert report["status"] == "pass" and report["intended_source_target"] == "not-assessed"


def test_corpus_can_resolve_across_children():
    data = b'<teiCorpus xmlns="http://www.tei-c.org/ns/1.0"><TEI><text><body><p xml:id="a"/></body></text></TEI><TEI><text><body><ref target="#a"/></body></text></TEI></teiCorpus>'
    assert check_links(data)["status"] == "pass"


def test_cli_exit_and_preservation(tmp_path, capsys):
    path = tmp_path / "candidate.xml"
    data = document('<ref target="#missing"/>')
    path.write_bytes(data)
    assert main([str(path)]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "fail"
    assert path.read_bytes() == data
    path.write_text('<!DOCTYPE TEI SYSTEM "missing.dtd"><TEI/>')
    assert main([str(path)]) == 2
